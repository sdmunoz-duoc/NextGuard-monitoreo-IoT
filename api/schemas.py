from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_RE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
TIPO_RE = r"^[a-z0-9_.]{1,32}$"


def a_utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


class MedicionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: str = Field(pattern=TIPO_RE)
    valor: float = Field(allow_inf_nan=False)
    unidad: str = Field(default="", max_length=16)


class LecturaIn(BaseModel):
    """Contrato de la clase: {sensor, cliente, ubicacion, tipo, valor, unidad}.
    Extensión propia: `mediciones` (varias magnitudes en un envío), `seq` (idempotencia), `rssi`, `fw_version`."""
    model_config = ConfigDict(extra="forbid")

    sensor: str = Field(pattern=ID_RE)
    cliente: str = Field(pattern=ID_RE)
    ubicacion: str | None = Field(default=None, max_length=120)
    tipo: str | None = Field(default=None, pattern=TIPO_RE)
    valor: float | None = Field(default=None, allow_inf_nan=False)
    unidad: str = Field(default="", max_length=16)
    mediciones: list[MedicionIn] | None = Field(default=None, min_length=1, max_length=32)
    seq: int | None = Field(default=None, ge=0, le=2**62)
    timestamp: datetime | None = None
    rssi: int | None = Field(default=None, ge=-127, le=0)
    fw_version: str | None = Field(default=None, max_length=32)

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, v):
        return a_utc(v)

    @model_validator(mode="after")
    def _una_forma(self):
        simple = self.tipo is not None or self.valor is not None
        if simple and self.mediciones is not None:
            raise ValueError("Use (tipo, valor, unidad) o 'mediciones', no ambos")
        if simple and (self.tipo is None or self.valor is None):
            raise ValueError("'tipo' y 'valor' van juntos")
        if not simple and self.mediciones is None:
            raise ValueError("Falta la medición: use (tipo, valor, unidad) o 'mediciones'")
        return self

    def lista_mediciones(self) -> list[MedicionIn]:
        if self.mediciones is not None:
            return self.mediciones
        return [MedicionIn(tipo=self.tipo, valor=self.valor, unidad=self.unidad)]


class LoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lecturas: list[LecturaIn] = Field(min_length=1, max_length=100)


class ClienteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_cliente: str = Field(pattern=ID_RE)
    nombre: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ClienteOut(BaseModel):
    id_cliente: str
    nombre: str
    email: str | None
    creado_en: datetime
    sensores: int | None = None


class SensorOut(BaseModel):
    sensor: str
    ubicacion: str | None
    tipo: str | None
    creado_en: datetime
    ultima_lectura: datetime | None


class MedicionOut(BaseModel):
    tipo: str
    valor: float
    unidad: str


class LecturaOut(BaseModel):
    cliente: str
    sensor: str
    ubicacion: str | None
    seq: int | None
    ts_dispositivo: datetime | None
    ts_servidor: datetime
    rssi: int | None
    fw_version: str | None
    mediciones: list[MedicionOut]


class RespuestaLectura(BaseModel):
    estado: str
    duplicado: bool
    sensor_nuevo: bool


class RespuestaLote(BaseModel):
    insertadas: int
    duplicadas: int
