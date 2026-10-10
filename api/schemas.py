from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

ID_RE = r"^[A-Za-z0-9_-]{1,64}$"
MAGNITUD_RE = r"^[a-z0-9_.]{1,32}$"


def _a_utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


class MedicionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    magnitud: str = Field(pattern=MAGNITUD_RE)
    valor: float = Field(allow_inf_nan=False)
    unidad: str = Field(default="", max_length=16)


class LecturaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(pattern=ID_RE)
    seq: int = Field(ge=0, le=2**62)
    ts_dispositivo: datetime | None = None
    rssi: int | None = Field(default=None, ge=-127, le=0)
    fw_version: str | None = Field(default=None, max_length=32)
    ubicacion: str | None = Field(default=None, max_length=120)
    mediciones: list[MedicionIn] = Field(min_length=1, max_length=32)

    @field_validator("ts_dispositivo")
    @classmethod
    def _utc(cls, v):
        return _a_utc(v)


class LoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lecturas: list[LecturaIn] = Field(min_length=1, max_length=100)


class MedicionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    magnitud: str
    valor: float
    unidad: str


class LecturaOut(BaseModel):
    id: int
    device_id: str
    seq: int
    ts_dispositivo: datetime | None
    ts_servidor: datetime
    rssi: int | None
    fw_version: str | None
    mediciones: list[MedicionOut]


class RespuestaLectura(BaseModel):
    id: int
    duplicado: bool


class RespuestaLote(BaseModel):
    insertadas: int
    duplicadas: int
