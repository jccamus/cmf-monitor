-- Esquema CMF Monitor (Postgres).
--
-- Una sola tabla 'resoluciones' como fuente de verdad de todas las
-- resoluciones scrapeadas. PK compuesta (fecha, numero), que es la clave
-- natural usada por scraper/classifier/enricher para deduplicar.
--
-- La tabla 'estado_codigos' reemplaza a data/_estado_codigos.json y
-- contiene la "lista de pendientes" entre corridas: entidades autorizadas
-- que aun no tienen codigo de institucion asignado.

CREATE TABLE IF NOT EXISTS resoluciones (
    -- Identidad (scraper.py)
    fecha               DATE        NOT NULL,
    numero              TEXT        NOT NULL,
    entidad             TEXT        NOT NULL DEFAULT '',
    tipo_servicio       TEXT        NOT NULL DEFAULT '',
    resolucion          TEXT        NOT NULL DEFAULT '',
    autoriza_prestacion BOOLEAN     NOT NULL DEFAULT FALSE,
    tipo_empresa        TEXT        NOT NULL DEFAULT 'Otra',

    -- Clasificacion (classifier.py)
    categoria           TEXT        NOT NULL DEFAULT '',

    -- Enriquecimiento paso 1 - busqueda (enricher.py)
    rut                 TEXT        NOT NULL DEFAULT '',
    nombre_cmf          TEXT        NOT NULL DEFAULT '',
    tipo_entidad_cmf    TEXT        NOT NULL DEFAULT '',
    vigencia            TEXT        NOT NULL DEFAULT '',

    -- Enriquecimiento paso 2 - detalle (enricher.py)
    rut_completo             TEXT NOT NULL DEFAULT '',
    codigo_institucion       TEXT NOT NULL DEFAULT '',
    razon_social             TEXT NOT NULL DEFAULT '',
    nombre_fantasia          TEXT NOT NULL DEFAULT '',
    vigencia_detalle         TEXT NOT NULL DEFAULT '',
    num_inscripcion          TEXT NOT NULL DEFAULT '',
    fecha_inscripcion        TEXT NOT NULL DEFAULT '',
    antecedentes_inscripcion TEXT NOT NULL DEFAULT '',
    fecha_cancelacion        TEXT NOT NULL DEFAULT '',
    telefono                 TEXT NOT NULL DEFAULT '',
    fax                      TEXT NOT NULL DEFAULT '',
    domicilio                TEXT NOT NULL DEFAULT '',
    region                   TEXT NOT NULL DEFAULT '',
    ciudad                   TEXT NOT NULL DEFAULT '',
    comuna                   TEXT NOT NULL DEFAULT '',
    email                    TEXT NOT NULL DEFAULT '',
    sitio_web                TEXT NOT NULL DEFAULT '',
    codigo_postal            TEXT NOT NULL DEFAULT '',

    -- Auditoria
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (fecha, numero)
);

CREATE INDEX IF NOT EXISTS idx_resoluciones_autoriza
    ON resoluciones (autoriza_prestacion, fecha DESC);

CREATE INDEX IF NOT EXISTS idx_resoluciones_rut
    ON resoluciones (rut) WHERE rut <> '';


CREATE TABLE IF NOT EXISTS estado_codigos (
    -- RUT sin DV (tal como llega del paso 1 del enricher: campo 'rut').
    rut                 TEXT PRIMARY KEY,
    entidad             TEXT NOT NULL DEFAULT '',
    rut_completo        TEXT NOT NULL DEFAULT '',
    fecha_resolucion    DATE,
    tipo_servicio       TEXT NOT NULL DEFAULT '',
    tipo_empresa        TEXT NOT NULL DEFAULT '',
    codigo_institucion  TEXT NOT NULL DEFAULT '',
    email               TEXT NOT NULL DEFAULT '',
    primera_deteccion   DATE NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- Fecha de la ultima corrida exitosa de tareas.py (clave 'ultima_corrida').
CREATE TABLE IF NOT EXISTS meta (
    clave   TEXT PRIMARY KEY,
    valor   TEXT NOT NULL
);


-- Incidencias detectadas en cada corrida diaria. Cada PASO del pipeline
-- registra aqui cosas que el equipo de operacion deberia revisar (datos
-- faltantes, fallas de envio, regex que no parseo una resolucion, etc.).
--
-- Al inicio de cada corrida se borran las incidencias de HOY (no las
-- historicas), asi la seccion "hoy" del dashboard siempre refleja el
-- ultimo estado y no acumula duplicados al re-correr el pipeline.
CREATE TABLE IF NOT EXISTS incidencias (
    id          BIGSERIAL PRIMARY KEY,
    fecha       DATE        NOT NULL DEFAULT CURRENT_DATE,
    tipo        TEXT        NOT NULL,           -- 'email_entidad_faltante', 'smtp_no_configurado', etc.
    gravedad    TEXT        NOT NULL DEFAULT 'aviso',  -- 'aviso' | 'error'
    mensaje     TEXT        NOT NULL,
    contexto    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incidencias_fecha
    ON incidencias (fecha DESC);
