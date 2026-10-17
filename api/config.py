import os
from dataclasses import dataclass, field

try:  # opcional: en Docker las variables llegan desde docker compose (.env)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _token() -> str:
    """El token de InfluxDB llega por variable o, mejor, desde un archivo (INFLUX_TOKEN_FILE)."""
    ruta = os.getenv("INFLUX_TOKEN_FILE")
    if ruta and os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return f.read().strip()
    return os.getenv("INFLUX_TOKEN", "")


@dataclass
class Settings:
    database_url: str = "sqlite:///./local.db"           # PostgreSQL: clientes, sensores, alertas, marcas de seq
    api_keys: list[str] = field(default_factory=list)
    max_body_bytes: int = 16384
    auto_create_tables: bool = True
    auto_enrolar_sensores: bool = True                   # el sensor se registra con su primera lectura
    influx_url: str = ""                                 # vacío => almacenamiento en memoria (solo pruebas)
    influx_org: str = "duoc"
    influx_bucket: str = "sensores"
    influx_token: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        keys = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./local.db"),
            api_keys=keys,
            max_body_bytes=int(os.getenv("MAX_BODY_BYTES", "16384")),
            auto_create_tables=os.getenv("AUTO_CREATE_TABLES", "true").lower() == "true",
            auto_enrolar_sensores=os.getenv("AUTO_ENROLAR_SENSORES", "true").lower() == "true",
            influx_url=os.getenv("INFLUX_URL", ""),
            influx_org=os.getenv("INFLUX_ORG", "duoc"),
            influx_bucket=os.getenv("INFLUX_BUCKET", "sensores"),
            influx_token=_token(),
        )
