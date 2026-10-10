"""API de ingesta de lecturas de sensores (FastAPI + SQLAlchemy).

Ejecutar en local:   uvicorn main:app --reload --port 8000   (desde scripts/api)
Variables (.env):    DATABASE_URL, API_KEYS, MAX_BODY_BYTES, AUTO_CREATE_TABLES
"""
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from config import Settings
from db import Base, make_engine
from models import Dispositivo, Lectura, Medicion
from schemas import LecturaIn, LecturaOut, LoteIn, MedicionOut, RespuestaLectura, RespuestaLote, _a_utc


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_tables:
            Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="API de sensores", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.SessionLocal = SessionLocal

    # ---------- Infraestructura ----------

    @app.middleware("http")
    async def limitar_tamano(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > settings.max_body_bytes:
            return JSONResponse({"detail": "Payload demasiado grande"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validacion(request: Request, exc: RequestValidationError):
        # No se devuelve el valor recibido ("input"): si es NaN/Inf no se puede serializar
        # a JSON y la respuesta 422 terminaba en 500 (p. ej. lectura fallida del DHT).
        errores = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse({"detail": errores}, status_code=422)

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def verificar_api_key(x_api_key: str | None = Header(default=None)):
        # Sin claves configuradas se rechaza todo (fail closed).
        if not x_api_key or not any(hmac.compare_digest(x_api_key, k) for k in settings.api_keys):
            raise HTTPException(status_code=401, detail="API key inválida o ausente")

    # ---------- Lógica de guardado ----------

    def _guardar(db: Session, p: LecturaIn) -> tuple[Lectura, bool]:
        disp = db.scalar(select(Dispositivo).where(Dispositivo.device_id == p.device_id))
        if disp is None:
            disp = Dispositivo(device_id=p.device_id, ubicacion=p.ubicacion)
            db.add(disp)
            db.flush()
        elif p.ubicacion and not disp.ubicacion:
            disp.ubicacion = p.ubicacion

        existente = db.scalar(select(Lectura).where(Lectura.dispositivo_id == disp.id, Lectura.seq == p.seq))
        if existente is not None:
            return existente, False

        lectura = Lectura(
            dispositivo_id=disp.id,
            seq=p.seq,
            ts_dispositivo=p.ts_dispositivo,
            ts_servidor=datetime.now(timezone.utc),
            rssi=p.rssi,
            fw_version=p.fw_version,
            mediciones=[Medicion(magnitud=m.magnitud, valor=m.valor, unidad=m.unidad) for m in p.mediciones],
        )
        db.add(lectura)
        db.flush()
        return lectura, True

    def guardar_con_reintento(db: Session, p: LecturaIn) -> tuple[int, bool]:
        """Confirma la transacción. Ante una carrera (dos envíos simultáneos con el mismo
        device_id/seq) el UNIQUE lanza IntegrityError y se reintenta como duplicado."""
        for intento in range(2):
            try:
                lectura, creada = _guardar(db, p)
                db.commit()
                return lectura.id, creada
            except IntegrityError:
                db.rollback()
                if intento == 1:
                    raise
        raise RuntimeError("inalcanzable")

    def _a_salida(l: Lectura) -> LecturaOut:
        return LecturaOut(
            id=l.id,
            device_id=l.dispositivo.device_id,
            seq=l.seq,
            ts_dispositivo=_a_utc(l.ts_dispositivo),
            ts_servidor=_a_utc(l.ts_servidor),
            rssi=l.rssi,
            fw_version=l.fw_version,
            mediciones=[MedicionOut.model_validate(m) for m in l.mediciones],
        )

    # ---------- Endpoints ----------

    @app.get("/health")
    def health(response: Response):
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            return {"status": "ok", "db": "ok"}
        except SQLAlchemyError:
            response.status_code = 503
            return {"status": "degradado", "db": "sin conexión"}

    @app.post("/api/v1/lecturas", response_model=RespuestaLectura, status_code=201,
              dependencies=[Depends(verificar_api_key)])
    def crear_lectura(p: LecturaIn, response: Response, db: Session = Depends(get_db)):
        lectura_id, creada = guardar_con_reintento(db, p)
        if not creada:
            response.status_code = 200
        return RespuestaLectura(id=lectura_id, duplicado=not creada)

    @app.post("/api/v1/lecturas/batch", response_model=RespuestaLote,
              dependencies=[Depends(verificar_api_key)])
    def crear_lote(lote: LoteIn, db: Session = Depends(get_db)):
        insertadas = duplicadas = 0
        for p in lote.lecturas:
            _, creada = guardar_con_reintento(db, p)
            insertadas += creada
            duplicadas += not creada
        return RespuestaLote(insertadas=insertadas, duplicadas=duplicadas)

    @app.get("/api/v1/lecturas", response_model=list[LecturaOut], dependencies=[Depends(verificar_api_key)])
    def listar_lecturas(
        device_id: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
        desde: datetime | None = None,
        hasta: datetime | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
        db: Session = Depends(get_db),
    ):
        q = select(Lectura).options(selectinload(Lectura.mediciones), selectinload(Lectura.dispositivo))
        if device_id:
            q = q.join(Dispositivo).where(Dispositivo.device_id == device_id)
        if desde:
            q = q.where(Lectura.ts_servidor >= _a_utc(desde))
        if hasta:
            q = q.where(Lectura.ts_servidor <= _a_utc(hasta))
        q = q.order_by(Lectura.ts_servidor.desc(), Lectura.id.desc()).limit(limit)
        return [_a_salida(l) for l in db.scalars(q)]

    return app


app = create_app()
