"""
Carga inicial de data/*.json -> tabla resoluciones de Postgres.
Tambien migra data/_estado_codigos.json -> tabla estado_codigos.

Es idempotente: si las tablas ya tienen filas, no hace nada.
Para forzar la migracion sobre tablas con datos, usar --force.

Uso:
  python migrate.py            # solo migra si las tablas estan vacias
  python migrate.py --force    # migra siempre (UPSERT; preserva datos nuevos)
"""

import glob
import json
import os
import sys
from datetime import datetime

import db

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
ESTADO_PATH = os.path.join(DATA_DIR, "_estado_codigos.json")

# Todas las columnas de resoluciones excepto created_at / updated_at.
COLUMNAS = [
    "fecha", "numero", "entidad", "tipo_servicio", "resolucion",
    "autoriza_prestacion", "tipo_empresa", "categoria",
    "rut", "nombre_cmf", "tipo_entidad_cmf", "vigencia",
    "rut_completo", "codigo_institucion", "razon_social", "nombre_fantasia",
    "vigencia_detalle", "num_inscripcion", "fecha_inscripcion",
    "antecedentes_inscripcion", "fecha_cancelacion", "telefono", "fax",
    "domicilio", "region", "ciudad", "comuna", "email", "sitio_web",
    "codigo_postal",
]

DEFAULTS = {"autoriza_prestacion": False, "tipo_empresa": "Otra"}


def _cargar_jsons() -> dict[tuple[str, str], dict]:
    """De mas viejo a mas nuevo: el archivo mas reciente sobrescribe.
    Asi cada (fecha, numero) queda con la version mas enriquecida."""
    consolidado: dict[tuple[str, str], dict] = {}
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "????-??-??.json")))
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                registros = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  AVISO: no se pudo leer {path}: {exc}")
            continue
        for r in registros:
            clave = (r.get("fecha", ""), r.get("numero", ""))
            if not clave[0] or not clave[1]:
                continue
            consolidado[clave] = r
    return consolidado


def _normalizar(r: dict) -> tuple:
    valores = []
    for c in COLUMNAS:
        v = r.get(c, DEFAULTS.get(c, ""))
        if v is None:
            v = DEFAULTS.get(c, "")
        valores.append(v)
    return tuple(valores)


def _migrar_resoluciones(conn, force: bool) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM resoluciones")
        existentes = cur.fetchone()[0]

    if existentes and not force:
        print(f"  resoluciones ya tiene {existentes} fila(s); omitiendo (usa --force para sobreescribir)")
        return 0

    consolidado = _cargar_jsons()
    if not consolidado:
        print("  No hay JSONs en data/ que migrar.")
        return 0

    placeholders = ", ".join(["%s"] * len(COLUMNAS))
    update_set   = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNAS if c not in ("fecha", "numero"))
    sql = (
        f"INSERT INTO resoluciones ({', '.join(COLUMNAS)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (fecha, numero) DO UPDATE SET {update_set}, updated_at = now()"
    )
    valores = [_normalizar(r) for r in consolidado.values()]
    with conn.cursor() as cur:
        cur.executemany(sql, valores)
    return len(valores)


def _migrar_estado(conn, force: bool) -> int:
    if not os.path.exists(ESTADO_PATH):
        print("  No existe _estado_codigos.json; omitiendo.")
        return 0

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM estado_codigos")
        existentes = cur.fetchone()[0]

    if existentes and not force:
        print(f"  estado_codigos ya tiene {existentes} fila(s); omitiendo (usa --force)")
        return 0

    with open(ESTADO_PATH, encoding="utf-8") as f:
        estado = json.load(f)

    pendientes = estado.get("sin_codigo", {})
    ultima     = estado.get("ultima_corrida", "")

    with conn.cursor() as cur:
        for rut, datos in pendientes.items():
            cur.execute(
                """
                INSERT INTO estado_codigos
                  (rut, entidad, rut_completo, fecha_resolucion,
                   tipo_servicio, tipo_empresa, codigo_institucion,
                   email, primera_deteccion, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (rut) DO UPDATE SET
                   entidad            = EXCLUDED.entidad,
                   rut_completo       = EXCLUDED.rut_completo,
                   fecha_resolucion   = EXCLUDED.fecha_resolucion,
                   tipo_servicio      = EXCLUDED.tipo_servicio,
                   tipo_empresa       = EXCLUDED.tipo_empresa,
                   codigo_institucion = EXCLUDED.codigo_institucion,
                   email              = EXCLUDED.email,
                   primera_deteccion  = EXCLUDED.primera_deteccion,
                   updated_at         = now()
                """,
                (
                    rut,
                    datos.get("entidad", ""),
                    datos.get("rut_completo", ""),
                    datos.get("fecha_resolucion") or None,
                    datos.get("tipo_servicio", ""),
                    datos.get("tipo_empresa", ""),
                    datos.get("codigo_institucion", "No asignado"),
                    datos.get("email", ""),
                    datos.get("primera_deteccion") or datetime.today().strftime("%Y-%m-%d"),
                ),
            )

        if ultima:
            cur.execute(
                "INSERT INTO meta (clave, valor) VALUES ('ultima_corrida', %s) "
                "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
                (ultima,),
            )

    return len(pendientes)


def main(force: bool = False) -> None:
    print(f"Migracion {'forzada' if force else 'inicial'} de JSON -> Postgres")
    with db.conectar() as conn:
        print("Tabla resoluciones...")
        n1 = _migrar_resoluciones(conn, force)
        print(f"  {n1} fila(s) cargadas/actualizadas.")

        print("Tabla estado_codigos...")
        n2 = _migrar_estado(conn, force)
        print(f"  {n2} fila(s) cargadas/actualizadas.")
    print("Listo.")


if __name__ == "__main__":
    force = "--force" in sys.argv
    main(force=force)
