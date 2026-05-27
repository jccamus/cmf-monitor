"""
Enriquece registros AUTORIZA LA PRESTACION en dos pasos por entidad:
  1. Busqueda CMF -> RUT, Tipo Entidad, Vigencia, URL de detalle
  2. Pagina de detalle -> todos los campos del registro oficial

Solo procesa registros con autoriza_prestacion=true que aun no tienen
num_inscripcion (incremental: lo que ya esta enriquecido no se re-pega).
"""

import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import db

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

# Mapa etiqueta (normalizada sin tildes, mayusculas) -> columna en resoluciones
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

# Columnas que actualizamos al final de buscar_entidad()
COLS_BUSQUEDA = ["rut", "nombre_cmf", "tipo_entidad_cmf", "vigencia"]
COLS_DETALLE  = list(CAMPOS_DETALLE.values())
COLS_TODAS    = COLS_BUSQUEDA + COLS_DETALLE


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _col(headers: list[str], *keywords: str) -> int | None:
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
# PASO 1 - Busqueda
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
    if "&" in nombre or "/" in nombre:
        limpio = nombre.replace("&", " ").replace("/", " ")
        limpio = " ".join(limpio.split())
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
# PASO 2 - Detalle
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


def buscar_entidad(nombre: str, sesion: requests.Session) -> dict:
    busqueda = _buscar(nombre, sesion)
    detail_url = busqueda.pop("detail_url", "")
    time.sleep(DELAY_SEG)
    detalle = _fetch_detail(detail_url, sesion)
    return {**busqueda, **detalle}


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

# UPDATE generado dinamicamente con todas las columnas de enriquecimiento.
_SET_COLS = ", ".join(f"{c} = %s" for c in COLS_TODAS)
_UPDATE_SQL = (
    f"UPDATE resoluciones SET {_SET_COLS}, updated_at = now() "
    "WHERE fecha = %s AND numero = %s"
)


def run(fecha: str | None = None) -> int:
    # 'fecha' se acepta por compatibilidad pero el enricher procesa TODOS los
    # pendientes del universo (no solo los de un dia): asi recoge entidades
    # que aparecieron en corridas anteriores pero quedaron sin enriquecer.
    del fecha

    with db.conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fecha, numero, entidad FROM resoluciones "
                "WHERE autoriza_prestacion = TRUE "
                "  AND entidad <> '' "
                "  AND COALESCE(num_inscripcion, '') = '' "
                "ORDER BY fecha DESC, numero DESC"
            )
            pendientes = cur.fetchall()

        if not pendientes:
            print("Todos los registros ya tienen datos de detalle.")
            return 0

        print(f"Enriqueciendo {len(pendientes)} entidades (busqueda + detalle)...")
        sesion = _crear_sesion()
        time.sleep(1)

        cache: dict[str, dict] = {}
        actualizadas = 0
        for i, (fecha_row, numero, entidad) in enumerate(pendientes, 1):
            print(f"  [{i}/{len(pendientes)}] {entidad}")

            if entidad not in cache:
                cache[entidad] = buscar_entidad(entidad, sesion)
                time.sleep(DELAY_SEG)

            datos = cache[entidad]
            valores = [datos.get(c, "") for c in COLS_TODAS]
            with conn.cursor() as cur:
                cur.execute(_UPDATE_SQL, (*valores, fecha_row, numero))
            # Commit por entidad: si el proceso se cae a mitad de la corrida,
            # lo enriquecido hasta ese punto no se pierde y la proxima corrida
            # solo retoma los pendientes restantes.
            conn.commit()
            actualizadas += 1

            rut_fmt = datos.get("rut_completo") or datos.get("rut") or "—"
            cod     = datos.get("codigo_institucion", "No asignado")
            insc    = datos.get("num_inscripcion", "")
            print(f"           RUT: {rut_fmt} | Cod.inst: {cod} | Insc: {insc}")

    print(f"\n{actualizadas} entidad(es) enriquecida(s).")
    return actualizadas


if __name__ == "__main__":
    fecha_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(fecha_arg)
