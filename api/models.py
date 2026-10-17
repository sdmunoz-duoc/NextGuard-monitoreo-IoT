"""Metadatos en PostgreSQL (SQLite en pruebas). Las lecturas NO se guardan aquí: van a InfluxDB."""
from datetime import datetime, timezone

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from db import Base

BigInt = BigInteger().with_variant(Integer, "sqlite")   # autoincremento también en SQLite


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class Cliente(Base):
    __tablename__ = "clientes"

    id_cliente: Mapped[str] = mapped_column(String(64), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)


class Sensor(Base):
    __tablename__ = "sensores"
    __table_args__ = (UniqueConstraint("id_cliente", "sensor", name="uq_sensor_cliente"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True)
    id_cliente: Mapped[str] = mapped_column(ForeignKey("clientes.id_cliente", ondelete="CASCADE"), nullable=False)
    sensor: Mapped[str] = mapped_column(String(64), nullable=False)
    ubicacion: Mapped[str | None] = mapped_column(String(120))
    tipo: Mapped[str | None] = mapped_column(String(32))
    ciclo_s: Mapped[int | None] = mapped_column(Integer)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
    ultima_lectura: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Alerta(Base):
    __tablename__ = "alertas"
    __table_args__ = (CheckConstraint("condicion IN ('>', '>=', '<', '<=')", name="ck_alerta_condicion"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True)
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensores.id", ondelete="CASCADE"), nullable=False)
    magnitud: Mapped[str] = mapped_column(String(32), nullable=False)
    condicion: Mapped[str] = mapped_column(String(8), nullable=False)
    umbral: Mapped[float] = mapped_column(Float, nullable=False)
    duracion_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    destinatario: Mapped[str] = mapped_column(String(200), nullable=False)
    canal: Mapped[str] = mapped_column(String(16), nullable=False, default="correo")
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LecturaVista(Base):
    """Marca de idempotencia: la clave primaria (sensor_id, seq) impide aceptar dos veces el mismo envío."""
    __tablename__ = "lecturas_vistas"
    __table_args__ = (CheckConstraint("seq >= 0", name="ck_vista_seq"),)

    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensores.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    visto_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora)
