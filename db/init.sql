-- PostgreSQL: configuración del sistema (quién es quién). Las lecturas viven en InfluxDB.
-- Se ejecuta una sola vez, al inicializar el volumen pg-data (docker-entrypoint-initdb.d).
-- La API también crea estas tablas con SQLAlchemy cuando AUTO_CREATE_TABLES=true (local/pruebas).

CREATE TABLE IF NOT EXISTS clientes (
    id_cliente  VARCHAR(64) PRIMARY KEY,
    nombre      VARCHAR(120) NOT NULL,
    email       VARCHAR(200),
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sensores (
    id              BIGSERIAL PRIMARY KEY,
    id_cliente      VARCHAR(64) NOT NULL REFERENCES clientes(id_cliente) ON DELETE CASCADE,
    sensor          VARCHAR(64) NOT NULL,
    ubicacion       VARCHAR(120),
    tipo            VARCHAR(32),
    ciclo_s         INTEGER,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultima_lectura  TIMESTAMPTZ,
    CONSTRAINT uq_sensor_cliente UNIQUE (id_cliente, sensor)
);

CREATE TABLE IF NOT EXISTS alertas (
    id            BIGSERIAL PRIMARY KEY,
    sensor_id     BIGINT NOT NULL REFERENCES sensores(id) ON DELETE CASCADE,
    magnitud      VARCHAR(32) NOT NULL,
    condicion     VARCHAR(8) NOT NULL CHECK (condicion IN ('>', '>=', '<', '<=')),
    umbral        DOUBLE PRECISION NOT NULL,
    duracion_s    INTEGER NOT NULL DEFAULT 0,
    destinatario  VARCHAR(200) NOT NULL,
    canal         VARCHAR(16) NOT NULL DEFAULT 'correo',
    activa        BOOLEAN NOT NULL DEFAULT TRUE
);

-- Marca de idempotencia: un (sensor, seq) solo se acepta una vez. Reintentos del ESP32 => 200 duplicado.
CREATE TABLE IF NOT EXISTS lecturas_vistas (
    sensor_id  BIGINT NOT NULL REFERENCES sensores(id) ON DELETE CASCADE,
    seq        BIGINT NOT NULL CHECK (seq >= 0),
    visto_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sensor_id, seq)
);
