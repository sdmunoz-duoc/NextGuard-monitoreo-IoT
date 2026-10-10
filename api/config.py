import os
from dataclasses import dataclass, field

try:  # opcional: en Docker las variables llegan desde docker compose (.env)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass
class Settings:
    database_url: str = "sqlite:///./local.db"
    api_keys: list[str] = field(default_factory=list)
    max_body_bytes: int = 16384
    auto_create_tables: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        keys = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./local.db"),
            api_keys=keys,
            max_body_bytes=int(os.getenv("MAX_BODY_BYTES", "16384")),
            auto_create_tables=os.getenv("AUTO_CREATE_TABLES", "true").lower() == "true",
        )
