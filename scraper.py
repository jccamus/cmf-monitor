"""
Descarga las resoluciones del sitio CMF Chile y guarda un JSON por día
en la carpeta data/.

Estructura real de la página CMF (columnas):
  0: N°   1: FECHA   2: MATERIA   3: ARCHIVO

La entidad y el tipo de servicio se extraen del texto de MATERIA,
que siempre sigue el patrón:
  "AUTORIZA LA PRESTACIÓN DEL SERVICIO DE <TIPO_SERVICIO> DE <ENTIDAD>."
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

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

# Ventana de búsqueda: solo se conservan resoluciones de los últimos N días
DIAS_HISTORICO = 90

# Tipos de servicio en orden de especificidad (más largo primero para evitar
# que "ASESORÍA" consuma a "ASESORÍA DE INVERSIÓN")
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
    # Encabezado: acepta "DEL SERVICIO", "DE LOS SERVICIOS", etc.
    r"AUTORIZA\s+LA\s+PRESTACI[OÓ]N\s+DE(?:L?|\s+LOS?)\s+SERVICIOS?\s+(?:DE\s+)?"
    # Primer tipo de servicio (grupo 1)
    r"(" + "|".join(_TIPOS_SERVICIO) + r")"
    # Opcional: "Y segundo_servicio" (descartado, solo capturamos el primero)
    r"(?:\s+Y\s+(?:" + "|".join(_TIPOS_SERVICIO) + r"))*"
    # Preposición + entidad (grupo 2) — [\s\S]+? para capturar aunque haya saltos de línea
    r"\s+(?:DE|A)\s+([\s\S]+?)\.?\s*$",
    re.IGNORECASE,
)

# Mapeo tipo de servicio → categoría de empresa
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
    """Convierte DD.MM.YYYY, DD-MM-YYYY o DD/MM/YYYY a YYYY-MM-DD."""
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s


def _normalizar_servicio(raw: str) -> str:
    """Convierte el texto capturado del regex a la clave canónica."""
    s = re.sub(r"\s+", " ", raw).strip().upper()
    # Normalizar vocales acentuadas
    reemplazos = {"Í": "I", "Ó": "O", "É": "E", "Á": "A", "Ú": "U",
                  "í": "i", "ó": "o", "é": "e", "á": "a", "ú": "u"}
    for k, v in reemplazos.items():
        s = s.replace(k, v)
    # Buscar la clave canónica
    for clave in _SERVICIO_A_TIPO:
        clave_norm = clave.upper()
        for k, v in reemplazos.items():
            clave_norm = clave_norm.replace(k, v)
        if clave_norm == s:
            return clave
    return raw.strip()


def extraer_entidad_y_servicio(materia: str) -> tuple[str, str, str]:
    """
    Retorna (entidad, tipo_servicio, tipo_empresa) extraídos del texto
    de la resolución. Si no coincide el patrón, retorna ("", materia, "Otra").
    """
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
            "categoria":           "",
            "tipo_empresa":        tipo_empresa,
        })

    return records


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

# Campos que el scraper recalcula en cada corrida (deterministas desde el texto
# de 'resolucion'). El resto de claves las añaden classifier.py y enricher.py;
# esas deben conservarse de una corrida a la siguiente.
CAMPOS_BASE = {
    "fecha", "numero", "entidad", "tipo_servicio",
    "resolucion", "autoriza_prestacion", "tipo_empresa",
}


def _cargar_historico() -> dict[tuple[str, str], dict]:
    """Mapa (fecha, numero) -> registro mas reciente ya guardado en data/.

    Recorre los JSON en orden ascendente, asi que para cada clave queda la
    version del archivo mas nuevo (la que tiene mas datos de enriquecimiento).
    """
    historico: dict[tuple[str, str], dict] = {}
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "????-??-??.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                prev = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for r in prev:
            historico[(r.get("fecha", ""), r.get("numero", ""))] = r
    return historico


def _fusionar_enriquecimiento(
    records: list[dict], historico: dict[tuple[str, str], dict]
) -> int:
    """Copia a cada registro recien scrapeado los campos que classifier/enricher
    ya habian calculado en corridas anteriores. Asi enricher.py vuelve a ser
    incremental (salta lo que ya tiene 'num_inscripcion').
    Retorna cuantas entidades conservaron sus datos de detalle."""
    conservados = 0
    for r in records:
        prev = historico.get((r.get("fecha", ""), r.get("numero", "")))
        if not prev:
            continue
        for k, v in prev.items():
            if k not in CAMPOS_BASE and k not in r:
                r[k] = v
        # 'categoria' la trae el scraper vacia; conservar la previa si existe.
        if prev.get("categoria"):
            r["categoria"] = prev["categoria"]
        if r.get("num_inscripcion"):
            conservados += 1
    return conservados


def run(fecha: str | None = None) -> list[dict]:
    os.makedirs(DATA_DIR, exist_ok=True)

    print("Descargando pagina CMF...")
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        html = resp.text
    except requests.RequestException as exc:
        print(f"ERROR al descargar: {exc}")
        sys.exit(1)

    debug_path = os.path.join(DATA_DIR, "debug.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(html)

    print("Parseando tabla...")
    records = parse(html)

    # Filtrar por la ventana de DIAS_HISTORICO días
    fecha_limite = (datetime.today() - timedelta(days=DIAS_HISTORICO)).strftime("%Y-%m-%d")
    records = [r for r in records if r.get("fecha", "") >= fecha_limite]

    # Conservar lo que classifier/enricher ya calcularon en corridas anteriores,
    # para no re-clasificar ni re-scrapear el detalle de cada entidad cada día.
    conservados = _fusionar_enriquecimiento(records, _cargar_historico())

    ap = [r for r in records if r["autoriza_prestacion"]]
    print(f"  {len(records)} resoluciones (ultimos {DIAS_HISTORICO} dias), {len(ap)} AUTORIZA LA PRESTACION")
    print(f"  {conservados} entidad(es) ya tenian datos de detalle (se conservan)")

    if fecha is None:
        fecha = datetime.today().strftime("%Y-%m-%d")
    out_path = os.path.join(DATA_DIR, f"{fecha}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  Guardado: {out_path}")

    return records


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def repair_entidades() -> None:
    """
    Re-extrae entidad/tipo_servicio/tipo_empresa en todos los JSON históricos
    para registros donde entidad quedó vacía (fallo del regex antiguo).
    Solo modifica registros con autoriza_prestacion=True y entidad="".
    """
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "????-??-??.json")))
    total_reparados = 0
    for path in paths:
        with open(path, encoding="utf-8") as f:
            records = json.load(f)
        changed = 0
        for r in records:
            if r.get("entidad") == "" and r.get("autoriza_prestacion"):
                entidad, servicio, tipo = extraer_entidad_y_servicio(
                    r.get("resolucion", "")
                )
                if entidad:
                    r["entidad"]       = entidad
                    r["tipo_servicio"] = servicio
                    r["tipo_empresa"]  = tipo
                    changed += 1
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            print(f"  Reparados {changed} registro(s) en {os.path.basename(path)}")
            total_reparados += changed
    if total_reparados:
        print(f"  Total reparados: {total_reparados}")
    else:
        print("  No habia registros con entidad vacia.")


if __name__ == "__main__":
    fecha_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(fecha_arg)
