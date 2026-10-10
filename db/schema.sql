-- Esquema PostgreSQL para la red de sensores.
-- En Docker lo aplica el contenedor db al inicializar el volumen (docker-entrypoint-initdb.d).
-- La API también puede crear las tablas con SQLAlchemy (AUTO_CREATE_TABLES=true, solo local/pruebas).
--
-- Aplicar a mano:  psql "host=localhost dbname=sensores user=sensores_app" -f schema.sql

CREATE TABLE IF NOT EXISTS dispositivo (
    id          BIGSERIAL PRIMARY KEY,
    device_id   VARCHAR(64) NOT NULL UNIQUE,
    ubicacion   VARCHAR(120),
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Una lectura = un envío del dispositivo. (dispositivo_id, seq) es la clave de
-- idempotencia: un reintento con el mismo seq NO genera una fila nueva.
CREATE TABLE IF NOT EXISTS lectura (
    id             BIGSERIAL PRIMARY KEY,
    dispositivo_id BIGINT NOT NULL REFERENCES dispositivo(id) ON DELETE CASCADE,
    seq            BIGINT NOT NULL CHECK (seq >= 0),
    ts_dispositivo TIMESTAMPTZ,                       -- NULL si el ESP32 aún no tenía hora NTP
    ts_servidor    TIMESTAMPTZ NOT NULL DEFAULT now(),
    rssi           SMALLINT,
    fw_version     VARCHAR(32),
    CONSTRAINT uq_lectura_dispositivo_seq UNIQUE (dispositivo_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_lectura_ts_servidor ON lectura (ts_servidor);
CREATE INDEX IF NOT EXISTS ix_lectura_dispositivo_ts ON lectura (dispositivo_id, ts_servidor DESC);

-- Formato largo: agregar PM2.5, PM10, CO2, etc. NO requiere migrar el esquema.
CREATE TABLE IF NOT EXISTS medicion (
    id         BIGSERIAL PRIMARY KEY,
    lectura_id BIGINT NOT NULL REFERENCES lectura(id) ON DELETE CASCADE,
    magnitud   VARCHAR(32) NOT NULL,                  -- temperatura, humedad, pm2_5, ...
    valor      DOUBLE PRECISION NOT NULL,
    unidad     VARCHAR(16) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_medicion_lectura ON medicion (lectura_id);
CREATE INDEX IF NOT EXISTS ix_medicion_magnitud ON medicion (magnitud);

-- Usuario de solo lectura para Grafana: lo crea db/02-roles.sh (grafana_ro, solo SELECT).
