"""API de ingesta de lecturas de sensores (FastAPI).

Lecturas -> InfluxDB 2.x. Clientes, sensores, alertas y marcas de idempotencia -> PostgreSQL.
Ejecutar en local:   uvicorn main:app --reload --port 8000   (desde api/; sin INFLUX_URL usa memoria)
Variables:           DATABASE_URL, API_KEYS, INFLUX_URL, INFLUX_TOKEN(_FILE), INFLUX_ORG, INFLUX_BUCKET
Toda la API trabaja en UTC.
"""
import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

os.environ.setdefault("TZ", "UTC")

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.exc import IntegrityError, SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from config import Settings  # noqa: E402
from db import Base, make_engine  # noqa: E402
from models import Cliente, LecturaVista, Sensor  # noqa: E402
from schemas import (ClienteIn, ClienteOut, ID_RE, LecturaIn, LecturaOut, LoteIn, RespuestaLectura,  # noqa: E402
                     RespuestaLote, SensorOut, a_utc)
from store import Store, StoreError, crear_store  # noqa: E402

# Rango físico aceptado por magnitud (el resto de los tipos no se valida por rango).
RANGOS = {
    "temperatura": (-40.0, 80.0),        # DHT11/DHT22
    "humedad": (0.0, 100.0),
    "calidad_aire_mv": (0.0, 3300.0),    # MQ135 tras el divisor de tensión
    "calidad_aire_raw": (0.0, 4095.0),   # ADC de 12 bits
}
MAX_FUTURO = timedelta(minutes=5)         # desfase de reloj tolerado en 'timestamp'


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)
    almacen = store or crear_store(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_tables:
            Base.metadata.create_all(engine)
        yield
        almacen.close()
        engine.dispose()

    app = FastAPI(title="API de sensores", version="2.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.SessionLocal = SessionLocal
    app.state.store = almacen

    # ---------- Infraestructura ----------

    @app.middleware("http")
    async def limitar_tamano(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > settings.max_body_bytes:
            return JSONResponse({"detail": "Payload demasiado grande"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validacion(request: Request, exc: RequestValidationError):
        # No se devuelve el valor recibido ("input"): si es NaN/Inf no se puede serializar a JSON.
        errores = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse({"detail": errores}, status_code=422)

    @app.exception_handler(StoreError)
    async def almacen_caido(request: Request, exc: StoreError):
        return JSONResponse({"detail": "Almacén de lecturas no disponible"}, status_code=503)

    @app.exception_handler(SQLAlchemyError)
    async def bd_caida(request: Request, exc: SQLAlchemyError):
        return JSONResponse({"detail": "Base de datos de configuración no disponible"}, status_code=503)

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

    # ---------- Lógica ----------

    def _validar(p: LecturaIn, ahora: datetime) -> None:
        for m in p.lista_mediciones():
            rango = RANGOS.get(m.tipo)
            if rango and not rango[0] <= m.valor <= rango[1]:
                raise HTTPException(422, f"'{m.tipo}' fuera de rango físico ({rango[0]:g} a {rango[1]:g}): {m.valor:g}")
        if p.timestamp and p.timestamp - ahora > MAX_FUTURO:
            raise HTTPException(422, "'timestamp' está en el futuro")

    def _sensor(db: Session, p: LecturaIn) -> tuple[Sensor, bool]:
        if db.get(Cliente, p.cliente) is None:
            raise HTTPException(403, f"Cliente '{p.cliente}' no registrado")
        sel = select(Sensor).where(Sensor.id_cliente == p.cliente, Sensor.sensor == p.sensor)
        s = db.scalar(sel)
        if s is not None:
            return s, False
        if not settings.auto_enrolar_sensores:
            raise HTTPException(403, f"Sensor '{p.sensor}' no registrado para el cliente '{p.cliente}'")
        try:
            tipo = p.tipo or (p.mediciones[0].tipo if p.mediciones else None)
            s = Sensor(id_cliente=p.cliente, sensor=p.sensor, ubicacion=p.ubicacion, tipo=tipo)
            db.add(s)
            db.commit()
            return s, True
        except IntegrityError:               # carrera: otro envío lo enroló primero
            db.rollback()
            return db.scalar(sel), False

    def _reclamar(db: Session, sensor_id: int, seq: int) -> bool:
        """True si el (sensor, seq) era nuevo; False si ya se había recibido (reintento)."""
        try:
            db.add(LecturaVista(sensor_id=sensor_id, seq=seq))
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False

    def _liberar(db: Session, sensor_id: int, seq: int) -> None:
        db.query(LecturaVista).filter(LecturaVista.sensor_id == sensor_id, LecturaVista.seq == seq).delete()
        db.commit()

    def procesar(db: Session, p: LecturaIn) -> tuple[bool, bool]:
        """Devuelve (creada, sensor_nuevo). Orden: rango/fecha -> cliente/sensor -> idempotencia -> escritura."""
        ahora = datetime.now(timezone.utc)
        _validar(p, ahora)
        sensor, nuevo = _sensor(db, p)
        if p.seq is not None and not _reclamar(db, sensor.id, p.seq):
            return False, nuevo
        try:
            almacen.escribir(p.cliente, p.sensor, p.ubicacion or sensor.ubicacion,
                             [(m.tipo, m.valor, m.unidad) for m in p.lista_mediciones()],
                             p.seq, p.rssi, p.timestamp, p.fw_version, ahora)
        except StoreError:
            if p.seq is not None:
                _liberar(db, sensor.id, p.seq)   # el reintento del ESP32 debe poder volver a intentarlo
            raise
        sensor.ultima_lectura = ahora
        db.commit()
        return True, nuevo

    def _a_salida(l: dict) -> LecturaOut:
        ts_disp = l.get("ts_dispositivo")
        if isinstance(ts_disp, str):
            ts_disp = datetime.fromisoformat(ts_disp)
        return LecturaOut(cliente=l["cliente"], sensor=l["sensor"], ubicacion=l.get("ubicacion"), seq=l.get("seq"),
                          ts_dispositivo=a_utc(ts_disp), ts_servidor=a_utc(l["ts_servidor"]), rssi=l.get("rssi"),
                          fw_version=l.get("fw_version"), mediciones=l["mediciones"])

    def _rango(desde: datetime | None, hasta: datetime | None) -> tuple[datetime, datetime]:
        ahora = datetime.now(timezone.utc)
        h = a_utc(hasta) or ahora
        d = a_utc(desde) or (h - timedelta(hours=24))
        return d, h

    # ---------- Endpoints ----------

    @app.get("/health")
    def health(response: Response):
        ok_pg = ok_store = False
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            ok_pg = True
        except SQLAlchemyError:
            pass
        ok_store = almacen.ping()
        if not (ok_pg and ok_store):
            response.status_code = 503
        return {"status": "ok" if ok_pg and ok_store else "degradado",
                "postgres": "ok" if ok_pg else "sin conexión", "influxdb": "ok" if ok_store else "sin conexión"}

    @app.post("/api/v1/lecturas", response_model=RespuestaLectura, status_code=201,
              dependencies=[Depends(verificar_api_key)])
    def crear_lectura(p: LecturaIn, response: Response, db: Session = Depends(get_db)):
        creada, nuevo = procesar(db, p)
        if not creada:
            response.status_code = 200
        return RespuestaLectura(estado="guardado" if creada else "duplicado", duplicado=not creada, sensor_nuevo=nuevo)

    @app.post("/api/v1/lecturas/batch", response_model=RespuestaLote, dependencies=[Depends(verificar_api_key)])
    def crear_lote(lote: LoteIn, db: Session = Depends(get_db)):
        ins = dup = 0
        for p in lote.lecturas:
            creada, _ = procesar(db, p)
            ins += creada
            dup += not creada
        return RespuestaLote(insertadas=ins, duplicadas=dup)

    @app.get("/api/v1/lecturas", response_model=list[LecturaOut], dependencies=[Depends(verificar_api_key)])
    def listar_lecturas(
        cliente: str | None = Query(default=None, pattern=ID_RE),
        sensor: str | None = Query(default=None, pattern=ID_RE),
        desde: datetime | None = None,
        hasta: datetime | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        d, h = _rango(desde, hasta)
        return [_a_salida(l) for l in almacen.listar(cliente, sensor, d, h, limit)]

    @app.post("/clientes", response_model=ClienteOut, status_code=201, dependencies=[Depends(verificar_api_key)])
    def crear_cliente(c: ClienteIn, db: Session = Depends(get_db)):
        if db.get(Cliente, c.id_cliente) is not None:
            raise HTTPException(409, f"El cliente '{c.id_cliente}' ya está registrado")
        fila = Cliente(id_cliente=c.id_cliente, nombre=c.nombre, email=c.email)
        try:
            db.add(fila)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, f"El cliente '{c.id_cliente}' ya está registrado")
        return ClienteOut(id_cliente=fila.id_cliente, nombre=fila.nombre, email=fila.email,
                          creado_en=a_utc(fila.creado_en), sensores=0)

    @app.get("/clientes", response_model=list[ClienteOut], dependencies=[Depends(verificar_api_key)])
    def listar_clientes(db: Session = Depends(get_db)):
        cuentas = dict(db.execute(select(Sensor.id_cliente, func.count()).group_by(Sensor.id_cliente)).all())
        return [ClienteOut(id_cliente=c.id_cliente, nombre=c.nombre, email=c.email, creado_en=a_utc(c.creado_en),
                           sensores=cuentas.get(c.id_cliente, 0))
                for c in db.scalars(select(Cliente).order_by(Cliente.id_cliente))]

    def _cliente_o_404(db: Session, id_cliente: str) -> Cliente:
        c = db.get(Cliente, id_cliente)
        if c is None:
            raise HTTPException(404, f"Cliente '{id_cliente}' no encontrado")
        return c

    @app.get("/clientes/{id_cliente}", response_model=ClienteOut, dependencies=[Depends(verificar_api_key)])
    def obtener_cliente(id_cliente: str, db: Session = Depends(get_db)):
        c = _cliente_o_404(db, id_cliente)
        n = db.scalar(select(func.count()).select_from(Sensor).where(Sensor.id_cliente == id_cliente))
        return ClienteOut(id_cliente=c.id_cliente, nombre=c.nombre, email=c.email, creado_en=a_utc(c.creado_en),
                          sensores=n)

    @app.get("/clientes/{id_cliente}/sensores", response_model=list[SensorOut],
             dependencies=[Depends(verificar_api_key)])
    def sensores_de_cliente(id_cliente: str, db: Session = Depends(get_db)):
        _cliente_o_404(db, id_cliente)
        return [SensorOut(sensor=s.sensor, ubicacion=s.ubicacion, tipo=s.tipo, creado_en=a_utc(s.creado_en),
                          ultima_lectura=a_utc(s.ultima_lectura))
                for s in db.scalars(select(Sensor).where(Sensor.id_cliente == id_cliente).order_by(Sensor.sensor))]

    @app.get("/clientes/{id_cliente}/sensores/{sensor}/lecturas", response_model=list[LecturaOut],
             dependencies=[Depends(verificar_api_key)])
    def lecturas_de_sensor(
        id_cliente: str,
        sensor: str,
        desde: datetime | None = None,
        hasta: datetime | None = None,
        limite: int = Query(default=100, ge=1, le=1000),
        db: Session = Depends(get_db),
    ):
        import re
        if not re.match(ID_RE, sensor):
            raise HTTPException(422, "Nombre de sensor inválido")
        _cliente_o_404(db, id_cliente)
        d, h = _rango(desde, hasta)
        return [_a_salida(l) for l in almacen.listar(id_cliente, sensor, d, h, limite)]

    return app


app = create_app()
