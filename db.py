"""
Acceso a Postgres. Usa psycopg v3.

Lee el DSN de la variable de entorno DATABASE_URL. Si no esta definida,
arma uno desde POSTGRES_HOST/PORT/DB/USER/PASSWORD con defaults locales.

La primera vez que se abre una conexion, ejecuta schema.sql para crear
las tablas si no existen. Asi el contenedor de la app puede arrancar
contra una DB recien creada sin pasos manuales.
"""
import os
from contextlib import contextmanager
from typing import Iterator, TYPE_CHECKING

# psycopg solo es necesario en tiempo de ejecucion (contenedor app).
# Mantenerlo como import diferido permite que herramientas locales sin la
# dependencia (preview.py, lint, IDE) carguen los modulos sin instalarla.
if TYPE_CHECKING:
    import psycopg

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

_schema_aplicado = False


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db   = os.environ.get("POSTGRES_DB",   "cmf")
    user = os.environ.get("POSTGRES_USER", "cmf")
    pwd  = os.environ.get("POSTGRES_PASSWORD", "cmf")
    return f"host={host} port={port} dbname={db} user={user} password={pwd}"


def _aplicar_schema(conn: "psycopg.Connection") -> None:
    global _schema_aplicado
    if _schema_aplicado:
        return
    if not os.path.exists(SCHEMA_PATH):
        _schema_aplicado = True
        return
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    _schema_aplicado = True


@contextmanager
def conectar() -> Iterator["psycopg.Connection"]:
    """Context manager que entrega una conexion lista para usar.
    Aplica schema.sql la primera vez que se invoca en el proceso."""
    import psycopg  # import diferido (ver nota arriba)
    conn = psycopg.connect(_dsn(), autocommit=False)
    try:
        _aplicar_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
