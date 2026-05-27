"""
Descarga las resoluciones del sitio CMF Chile y las upsertea en la tabla
'resoluciones' de Postgres.

Estructura real de la pagina CMF (columnas):
  0: N°   1: FECHA   2: MATERIA   3: ARCHIVO

La entidad y el tipo de servicio se extraen del texto de MATERIA,
que siempre sigue el patron:
  "AUTORIZA LA PRESTACION DEL SERVICIO DE <TIPO_SERVICIO> DE <ENTIDAD>."
"""

import os
import re
import sys
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

import db
import issues

URL = (
    "https://www.cmfchile.cl/institucional/resoluciones/"
    "resoluciones_mercados_entidad.php?mercado=&entidad=ALL"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Referer": "https://www.cmfchile.cl/",
}

# Columnas fijas de la tabla CMF (actualizar si el sitio cambia)
COL_NUMERO  = 0
COL_FECHA   = 1
COL_MATERIA = 2

# Ventana de busqueda: solo se conservan resoluciones de los ultimos N dias
DIAS_HISTORICO = 90

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")  # solo para data/debug.html

# Tipos de servicio en orden de especificidad (mas largo primero para evitar
# que "ASESORIA" consuma a "ASESORIA DE INVERSION")
_TIPOS_SERVICIO = [
    r"ASESOR[IÍ]A\s+DE\s+INVERSI[OÓ]N",
    r"ASESOR[IÍ]A\s+CREDITICIA",
    r"ASESOR[IÍ]A",
    r"INTERMEDIACI[OÓ]N\s+DE\s+INSTRUMENTOS\s+FINANCIEROS",
    r"INTERMEDIACI[OÓ]N\s+DE\s+VALORES",
    r"INTERMEDIACI[OÓ]N",
    r"SISTEMA\s+ALTERNATIVO\s+DE\s+TRANSACCI[OÓ]N",
    r"ENRUTAMIENTO\s+DE\s+[OÓ]RDENES",
    r"GESTI[OÓ]N\s+DE\s+CARTERAS",
    r"DISTRIBUCI[OÓ]N\s+DE\s+SEGUROS",
    r"FACTORAJE",
    r"ARRENDAMIENTO\s+FINANCIERO",
]

_MATERIA_RE = re.compile(
    r"AUTORIZA\s+LA\s+PRESTACI[OÓ]N\s+DE(?:L?|\s+LOS?)\s+SERVICIOS?\s+(?:DE\s+)?"
    r"(" + "|".join(_TIPOS_SERVICIO) + r")"
    r"(?:\s+Y\s+(?:" + "|".join(_TIPOS_SERVICIO) + r"))*"
    r"\s+(?:DE|A)\s+([\s\S]+?)\.?\s*$",
    re.IGNORECASE,
)

_SERVICIO_A_TIPO: dict[str, str] = {
    "ASESORÍA DE INVERSIÓN":                    "Asesor de Inversiones",
    "ASESORÍA CREDITICIA":                      "Asesor Crediticio",
    "ASESORÍA":                                 "Asesor de Inversiones",
    "INTERMEDIACIÓN DE INSTRUMENTOS FINANCIEROS": "Intermediario Financiero",
    "INTERMEDIACIÓN DE VALORES":                "Corredor de Valores",
    "INTERMEDIACIÓN":                           "Intermediario Financiero",
    "SISTEMA ALTERNATIVO DE TRANSACCIÓN":       "Sistema Alt. de Transacción",
    "ENRUTAMIENTO DE ÓRDENES":                  "Enrutador de Órdenes",
    "GESTIÓN DE CARTERAS":                      "Gestor de Carteras",
    "DISTRIBUCIÓN DE SEGUROS":                  "Distribuidor de Seguros",
    "FACTORAJE":                                "Factoring",
    "ARRENDAMIENTO FINANCIERO":                 "Leasing",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def to_iso(s: str) -> str:
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s


def _normalizar_servicio(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw).strip().upper()
    reemplazos = {"Í": "I", "Ó": "O", "É": "E", "Á": "A", "Ú": "U",
                  "í": "i", "ó": "o", "é": "e", "á": "a", "ú": "u"}
    for k, v in reemplazos.items():
        s = s.replace(k, v)
    for clave in _SERVICIO_A_TIPO:
        clave_norm = clave.upper()
        for k, v in reemplazos.items():
            clave_norm = clave_norm.replace(k, v)
        if clave_norm == s:
            return clave
    return raw.strip()


def extraer_entidad_y_servicio(materia: str) -> tuple[str, str, str]:
    m = _MATERIA_RE.search(materia)
    if not m:
        return "", materia, "Otra"
    servicio_raw = m.group(1).strip()
    entidad = re.sub(r"\s+", " ", m.group(2)).strip().rstrip(".")
    servicio = _normalizar_servicio(servicio_raw)
    tipo_empresa = _SERVICIO_A_TIPO.get(servicio, "Otra")
    return entidad, servicio, tipo_empresa


# ---------------------------------------------------------------------------
# Parsing HTML
# ---------------------------------------------------------------------------

def parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")

    if not tables:
        raise RuntimeError(
            "No se encontro ninguna tabla en la pagina. "
            "Ver data/debug.html para diagnostico."
        )

    target = max(tables, key=lambda t: len(t.find_all("tr")))
    rows = target.find_all("tr")

    if len(rows) < 2:
        raise RuntimeError(
            f"La tabla tiene solo {len(rows)} fila(s). "
            "Puede que el sitio haya cambiado su estructura."
        )

    records: list[dict] = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) <= COL_MATERIA:
            continue

        numero  = cells[COL_NUMERO].get_text(" ", strip=True)
        fecha   = to_iso(cells[COL_FECHA].get_text(" ", strip=True))
        materia = cells[COL_MATERIA].get_text(" ", strip=True)

        es_autoriza = materia.upper().startswith("AUTORIZA LA PRESTACI")
        entidad, tipo_servicio, tipo_empresa = extraer_entidad_y_servicio(materia)

        records.append({
            "fecha":               fecha,
            "numero":              numero,
            "entidad":             entidad,
            "tipo_servicio":       tipo_servicio,
            "resolucion":          materia,
            "autoriza_prestacion": es_autoriza,
            "tipo_empresa":        tipo_empresa,
        })

    return records


# ---------------------------------------------------------------------------
# Persistencia en Postgres
# ---------------------------------------------------------------------------

# UPSERT solo de los campos base (los que el scraper recalcula). El resto
# (categoria, rut, enriquecimiento) NO se toca: queda como estaba si la fila
# ya existia, vacio si es nueva. Asi la pipeline sigue siendo incremental.
_UPSERT_SQL = """
INSERT INTO resoluciones
    (fecha, numero, entidad, tipo_servicio, resolucion,
     autoriza_prestacion, tipo_empresa)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (fecha, numero) DO UPDATE SET
    entidad             = EXCLUDED.entidad,
    tipo_servicio       = EXCLUDED.tipo_servicio,
    resolucion          = EXCLUDED.resolucion,
    autoriza_prestacion = EXCLUDED.autoriza_prestacion,
    tipo_empresa        = EXCLUDED.tipo_empresa,
    updated_at          = now()
WHERE
    -- evita updates espurios que solo cambian updated_at
    resoluciones.entidad             IS DISTINCT FROM EXCLUDED.entidad
 OR resoluciones.tipo_servicio       IS DISTINCT FROM EXCLUDED.tipo_servicio
 OR resoluciones.resolucion          IS DISTINCT FROM EXCLUDED.resolucion
 OR resoluciones.autoriza_prestacion IS DISTINCT FROM EXCLUDED.autoriza_prestacion
 OR resoluciones.tipo_empresa        IS DISTINCT FROM EXCLUDED.tipo_empresa
"""


def _guardar(records: list[dict]) -> int:
    """Upsertea records. Devuelve cuantas filas YA tenian num_inscripcion
    antes del upsert (info para el log: cuantas no van a re-procesarse en
    enricher porque ya tienen detalle)."""
    if not records:
        return 0
    fechas  = [r["fecha"]  for r in records]
    numeros = [r["numero"] for r in records]
    with db.conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM resoluciones r "
                "JOIN unnest(%s::date[], %s::text[]) AS k(fecha, numero) "
                "  ON r.fecha = k.fecha AND r.numero = k.numero "
                "WHERE r.num_inscripcion <> ''",
                (fechas, numeros),
            )
            row = cur.fetchone()
            conservados = int(row[0]) if row else 0

            cur.executemany(_UPSERT_SQL, [
                (r["fecha"], r["numero"], r["entidad"], r["tipo_servicio"],
                 r["resolucion"], r["autoriza_prestacion"], r["tipo_empresa"])
                for r in records
            ])
    return conservados


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def run(fecha: str | None = None) -> list[dict]:
    os.makedirs(DATA_DIR, exist_ok=True)

    print("Descargando pagina CMF...")
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        html = resp.text
    except requests.RequestException as exc:
        # Registramos como incidencia visible en el dashboard y propagamos la
        # excepcion. run.py la captura para que el resto del pipeline (tareas,
        # mailer, dashboard) siga corriendo contra los datos previos en la DB.
        print(f"ERROR al descargar: {exc}")
        try:
            issues.registrar(
                "scraper_error_red", "error",
                f"Fallo la descarga del listado CMF: {exc}",
                {"error": str(exc), "url": URL},
            )
        except Exception as exc_inc:
            # Si tampoco se puede escribir la incidencia (DB caida), solo log.
            print(f"  (ademas no se pudo registrar la incidencia: {exc_inc})")
        raise

    debug_path = os.path.join(DATA_DIR, "debug.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(html)

    print("Parseando tabla...")
    records = parse(html)

    fecha_limite = (datetime.today() - timedelta(days=DIAS_HISTORICO)).strftime("%Y-%m-%d")
    records = [r for r in records if r.get("fecha", "") >= fecha_limite]

    conservados = _guardar(records)

    ap = [r for r in records if r["autoriza_prestacion"]]
    print(f"  {len(records)} resoluciones (ultimos {DIAS_HISTORICO} dias), {len(ap)} AUTORIZA LA PRESTACION")
    print(f"  {conservados} entidad(es) ya tenian datos de detalle (se conservan)")
    if fecha:
        print(f"  Fecha de corrida: {fecha}")

    return records


def repair_entidades() -> None:
    """Re-extrae entidad/tipo_servicio/tipo_empresa para registros donde
    entidad quedo vacia (fallo del regex antiguo). Solo modifica filas con
    autoriza_prestacion=true y entidad=''."""
    reparados = 0
    with db.conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fecha, numero, resolucion FROM resoluciones "
                "WHERE entidad = '' AND autoriza_prestacion = TRUE"
            )
            filas = cur.fetchall()
            for fecha, numero, resolucion in filas:
                entidad, servicio, tipo = extraer_entidad_y_servicio(resolucion or "")
                if entidad:
                    cur.execute(
                        "UPDATE resoluciones SET entidad=%s, tipo_servicio=%s, "
                        "tipo_empresa=%s, updated_at=now() "
                        "WHERE fecha=%s AND numero=%s",
                        (entidad, servicio, tipo, fecha, numero),
                    )
                    reparados += 1
    if reparados:
        print(f"  Total reparados: {reparados}")
    else:
        print("  No habia registros con entidad vacia.")


if __name__ == "__main__":
    fecha_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(fecha_arg)
