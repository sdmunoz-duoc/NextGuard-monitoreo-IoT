from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

# BigInteger no autoincrementa en SQLite; esta variante lo resuelve sin afectar a PostgreSQL.
BigInt = BigInteger().with_variant(Integer, "sqlite")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class Dispositivo(Base):
    __tablename__ = "dispositivo"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    ubicacion: Mapped[str | None] = mapped_column(String(120))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)

    lecturas: Mapped[list["Lectura"]] = relationship(back_populates="dispositivo", cascade="all, delete-orphan")


class Lectura(Base):
    __tablename__ = "lectura"
    __table_args__ = (
        UniqueConstraint("dispositivo_id", "seq", name="uq_lectura_dispositivo_seq"),
        CheckConstraint("seq >= 0", name="ck_lectura_seq_positivo"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True)
    dispositivo_id: Mapped[int] = mapped_column(BigInt, ForeignKey("dispositivo.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ts_dispositivo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ts_servidor: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora, index=True)
    rssi: Mapped[int | None] = mapped_column(Integer)
    fw_version: Mapped[str | None] = mapped_column(String(32))

    dispositivo: Mapped[Dispositivo] = relationship(back_populates="lecturas")
    mediciones: Mapped[list["Medicion"]] = relationship(back_populates="lectura", cascade="all, delete-orphan")


class Medicion(Base):
    __tablename__ = "medicion"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True)
    lectura_id: Mapped[int] = mapped_column(BigInt, ForeignKey("lectura.id", ondelete="CASCADE"), nullable=False, index=True)
    magnitud: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    valor: Mapped[float] = mapped_column(Float, nullable=False)
    unidad: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    lectura: Mapped[Lectura] = relationship(back_populates="mediciones")
