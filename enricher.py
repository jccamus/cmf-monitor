"""
Enriquece el JSON diario en dos pasos por entidad:
  1. Búsqueda CMF → RUT, Tipo Entidad, Vigencia, URL de detalle
  2. Página de detalle → todos los campos del registro oficial

Los campos de detalle incluyen: rut_completo, codigo_institucion,
razon_social, nombre_fantasia, num_inscripcion, fecha_inscripcion,
antecedentes_inscripcion, fecha_cancelacion, telefono, fax, domicilio,
region, ciudad, comuna, email, sitio_web, codigo_postal.

Por defecto solo procesa registros AUTORIZA LA PRESTACIÓN.
Solo re-procesa registros sin 'num_inscripcion' (los nuevos o sin detalle).
"""

import json
import os
import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")

CMF_HOME   = "https://www.cmfchile.cl/"
SEARCH_URL = (
    "https://www.cmfchile.cl/institucional/mercados/"
    "consulta_busqueda.php?entidad_web=G&valor={}&boton_busqueda="
)
DETAIL_BASE = "https://www.cmfchile.cl/institucional/mercados/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9",
    "Referer": "https://www.cmfchile.cl/",
}

DELAY_SEG = 2.0
TIMEOUT   = 25

VACIO_BUSQUEDA = {
    "rut": "", "nombre_cmf": "", "tipo_entidad_cmf": "",
    "vigencia": "No encontrado", "detail_url": "",
}

# Mapa etiqueta (normalizada sin tildes, mayúsculas) → clave JSON
CAMPOS_DETALLE: dict[str, str] = {
    "RUT":                         "rut_completo",
    "CODIGO DE LA INSTITUCION":    "codigo_institucion",
    "RAZON SOCIAL":                "razon_social",
    "NOMBRE DE FANTASIA":          "nombre_fantasia",
    "VIGENCIA":                    "vigencia_detalle",
    "NUMERO DE INSCRIPCION":       "num_inscripcion",
    "FECHA DE INSCRIPCION":        "fecha_inscripcion",
    "ANTECEDENTES DE INSCRIPCION": "antecedentes_inscripcion",
    "FECHA DE CANCELACION":        "fecha_cancelacion",
    "TELEFONO":                    "telefono",
    "FAX":                         "fax",
    "DOMICILIO":                   "domicilio",
    "REGION":                      "region",
    "CIUDAD":                      "ciudad",
    "COMUNA":                      "comuna",
    "E-MAIL DE CONTACTO":          "email",
    "SITIO WEB":                   "sitio_web",
    "CODIGO POSTAL":               "codigo_postal",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _col(headers: list[str], *keywords: str) -> int | None:
    """Índice de la primera columna que contiene algún keyword.
    No usa 'or' encadenado para evitar que índice 0 sea tratado como falsy."""
    for kw in keywords:
        for i, h in enumerate(headers):
            if kw in h:
                return i
    return None


def _crear_sesion() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(CMF_HOME, timeout=TIMEOUT)
    except requests.RequestException:
        pass
    return s


# ---------------------------------------------------------------------------
# PASO 1 — Búsqueda: RUT + link de detalle
# ---------------------------------------------------------------------------

def _parse_busqueda(html: str, nombre_buscado: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        raw_hdrs = [c.get_text(" ", strip=True).upper() for c in rows[0].find_all(["th", "td"])]
        if not any("R.U.T" in h or h == "RUT" for h in raw_hdrs):
            continue

        i_rut    = _col(raw_hdrs, "R.U.T", "RUT")
        i_nombre = _col(raw_hdrs, "NOMBRE")
        i_tipo   = _col(raw_hdrs, "TIPO ENTIDAD", "TIPO")
        i_vig    = _col(raw_hdrs, "VIGENCIA")

        def cell(row, i: int | None) -> str:
            if i is None:
                return ""
            cells = row.find_all(["td", "th"])
            return cells[i].get_text(" ", strip=True) if i < len(cells) else ""

        def detail_link(row) -> str:
            if i_nombre is None:
                return ""
            cells = row.find_all(["td", "th"])
            if i_nombre >= len(cells):
                return ""
            a = cells[i_nombre].find("a", href=True)
            if not a:
                return ""
            href = a["href"]
            return href if href.startswith("http") else DETAIL_BASE + href

        resultados = []
        for row in rows[1:]:
            if not row.find_all(["td", "th"]):
                continue
            resultados.append({
                "rut":              cell(row, i_rut),
                "nombre_cmf":       cell(row, i_nombre),
                "tipo_entidad_cmf": cell(row, i_tipo),
                "vigencia":         cell(row, i_vig),
                "detail_url":       detail_link(row),
            })

        if not resultados:
            return VACIO_BUSQUEDA.copy()

        nb = nombre_buscado.upper()
        for res in resultados:
            if res["nombre_cmf"].upper() == nb:
                return res
        for res in resultados:
            nc = res["nombre_cmf"].upper()
            if nb in nc or nc in nb:
                return res
        return resultados[0]

    return VACIO_BUSQUEDA.copy()


def _buscar(nombre: str, sesion: requests.Session) -> dict:
    intentos = [nombre, _sin_tildes(nombre)]
    palabras = nombre.split()
    if len(palabras) > 1:
        intentos.append(palabras[0])
    # Fallback extra para nombres con & u otros caracteres especiales
    if "&" in nombre or "/" in nombre:
        limpio = nombre.replace("&", " ").replace("/", " ")
        limpio = " ".join(limpio.split())  # normalizar espacios
        intentos.append(limpio)
        intentos.append(_sin_tildes(limpio))
        palabras_limpias = limpio.split()
        if len(palabras_limpias) > 1:
            intentos.append(palabras_limpias[0])

    seen: set[str] = set()
    for intento in intentos:
        if intento in seen:
            continue
        seen.add(intento)
        url = SEARCH_URL.format(urllib.parse.quote(intento, safe=""))
        for retry in range(2):
            try:
                r = sesion.get(url, timeout=TIMEOUT)
                r.raise_for_status()
                r.encoding = "utf-8"
                res = _parse_busqueda(r.text, nombre)
                if res["rut"]:
                    return res
                break
            except requests.RequestException:
                if retry == 0:
                    time.sleep(3)

    return VACIO_BUSQUEDA.copy()


# ---------------------------------------------------------------------------
# PASO 2 — Detalle: todos los campos del registro oficial
# ---------------------------------------------------------------------------

def _detalle_vacio() -> dict:
    base = {v: "" for v in CAMPOS_DETALLE.values()}
    base["codigo_institucion"] = "No asignado"
    return base


def _fetch_detail(detail_url: str, sesion: requests.Session) -> dict:
    base = _detalle_vacio()
    if not detail_url:
        return base

    for retry in range(2):
        try:
            r = sesion.get(detail_url, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = "utf-8"
            break
        except requests.RequestException:
            if retry == 0:
                time.sleep(3)
            else:
                return base

    soup = BeautifulSoup(r.text, "lxml")
    encontro_codigo = False

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label_norm = _sin_tildes(cells[0].get_text(" ", strip=True).upper().strip())
        value = cells[1].get_text(" ", strip=True)
        key = CAMPOS_DETALLE.get(label_norm)
        if key:
            base[key] = value
            if key == "codigo_institucion":
                encontro_codigo = True

    if not encontro_codigo:
        base["codigo_institucion"] = "No asignado"

    return base


# ---------------------------------------------------------------------------
# Función principal por entidad
# ---------------------------------------------------------------------------

def buscar_entidad(nombre: str, sesion: requests.Session) -> dict:
    """Busca la entidad y obtiene todos sus datos de detalle."""
    busqueda = _buscar(nombre, sesion)
    detail_url = busqueda.pop("detail_url", "")

    time.sleep(DELAY_SEG)
    detalle = _fetch_detail(detail_url, sesion)

    return {**busqueda, **detalle}


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def run(
    fecha: str | None = None,
    solo_autorizadas: bool = True,
) -> list[dict]:

    if fecha is None:
        fecha = datetime.today().strftime("%Y-%m-%d")

    path = os.path.join(DATA_DIR, f"{fecha}.json")
    if not os.path.exists(path):
        print(f"No existe {path}. Ejecuta scraper.py primero.")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        records: list[dict] = json.load(f)

    # Procesar entidades que aun no estan completas: o falta 'num_inscripcion'
    # (jamas se enriquecio) o ya esta inscrita pero codigo_institucion sigue
    # "No asignado" (CMF asigna el codigo despues de la inscripcion, asi que
    # hay que volver a consultar la ficha hasta que aparezca).
    pendientes = [
        r for r in records
        if r.get("entidad")
        and (not solo_autorizadas or r.get("autoriza_prestacion"))
        and (not r.get("num_inscripcion")
             or r.get("codigo_institucion", "") in ("", "No asignado"))
    ]

    if not pendientes:
        print("Todos los registros ya tienen datos de detalle.")
        return records

    print(f"Enriqueciendo {len(pendientes)} entidades (busqueda + detalle)...")
    sesion = _crear_sesion()
    time.sleep(1)

    cache: dict[str, dict] = {}
    for i, r in enumerate(pendientes, 1):
        entidad = r["entidad"]
        print(f"  [{i}/{len(pendientes)}] {entidad}")

        if entidad not in cache:
            cache[entidad] = buscar_entidad(entidad, sesion)
            time.sleep(DELAY_SEG)

        datos = cache[entidad]
        r.update(datos)

        rut_fmt = datos.get("rut_completo") or datos.get("rut") or "—"
        cod     = datos.get("codigo_institucion", "No asignado")
        insc    = datos.get("num_inscripcion", "")
        print(f"           RUT: {rut_fmt} | Cod.inst: {cod} | Insc: {insc}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"\nGuardado: {path}")

    return records


if __name__ == "__main__":
    fecha_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(fecha_arg)
