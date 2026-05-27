"""
Genera HTMLs de preview sin necesidad de Postgres ni Docker.

Crea 3 archivos en reports/preview/ :
  - dashboard_preview.html
  - mail_nuevas_preview.html
  - mail_asignados_preview.html

Uso:
  python preview.py        # genera los 3
  python preview.py open   # genera y abre cada uno en el navegador

El dashboard usa los data/*.json reales que ya tienes en el repo.
Los correos usan datos de muestra mas un par de entidades reales tomadas
de data/_estado_codigos.json (si existe) para que veas como se ve con
informacion verosimil. NO se envia ningun correo: solo se renderiza el
HTML del cuerpo.
"""
import glob
import json
import os
import sys
import webbrowser
from datetime import datetime, date, timedelta
from string import Template

# Importamos los modulos pero NO invocamos sus run(); usamos los helpers
# de renderizado directamente para evitar tocar la DB.
import dashboard
import mailer

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
PREVIEW_DIR = os.path.join(BASE_DIR, "reports", "preview")


# ---------------------------------------------------------------------------
# Datos para el dashboard: leemos los JSON reales en data/
# ---------------------------------------------------------------------------

def cargar_records_desde_json() -> list[dict]:
    """Mismo criterio que tenia el viejo dashboard: para cada (fecha, numero)
    se conserva la version del archivo mas reciente (la mas enriquecida)."""
    seen: set[tuple[str, str]] = set()
    records: list[dict] = []
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "????-??-??.json")), reverse=True)
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                for r in json.load(f):
                    key = (r.get("fecha", ""), r.get("numero", ""))
                    if key not in seen:
                        seen.add(key)
                        records.append(r)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(records, key=lambda r: r.get("fecha", ""), reverse=True)


# ---------------------------------------------------------------------------
# Incidencias de muestra: una de cada tipo para que veas como queda la UI
# ---------------------------------------------------------------------------

def incidencias_muestra() -> list[dict]:
    """Una incidencia de cada tipo, con mensajes verosimiles."""
    ahora = datetime.now()
    return [
        {
            "id": 1, "tipo": "smtp_error", "gravedad": "error",
            "mensaje": "Correo 2 (codigos asignados): fallo el envio SMTP: "
                       "[Errno -2] Name or service not known",
            "contexto": {}, "created_at": ahora,
        },
        {
            "id": 2, "tipo": "destinatario_faltante", "gravedad": "error",
            "mensaje": "Correo 1 (nuevas sin codigo): hay 2 novedad(es) pero "
                       "el destinatario esta vacio.",
            "contexto": {}, "created_at": ahora,
        },
        {
            "id": 3, "tipo": "entidad_no_extraida", "gravedad": "error",
            "mensaje": "No se pudo extraer entidad de la resolucion 5089 (2026-05-14).",
            "contexto": {}, "created_at": ahora,
        },
        {
            "id": 4, "tipo": "email_entidad_faltante", "gravedad": "aviso",
            "mensaje": "PONDERA SPA (RUT 77.898.724-4) esta en la lista "
                       "'recien_asignados' pero no tiene email de contacto.",
            "contexto": {}, "created_at": ahora,
        },
        {
            "id": 5, "tipo": "email_entidad_faltante", "gravedad": "aviso",
            "mensaje": "COLBAST SPA (RUT 77.105.314-9) esta en la lista "
                       "'nuevas_sin_codigo' pero no tiene email de contacto.",
            "contexto": {}, "created_at": ahora,
        },
        {
            "id": 6, "tipo": "pendiente_fuera_ventana", "gravedad": "aviso",
            "mensaje": "EJEMPLO SPA (RUT 76.543.210-1) sigue pendiente pero "
                       "ya no aparece en la ventana de 90 dias del scraper.",
            "contexto": {}, "created_at": ahora,
        },
    ]


def resumen_semana_muestra() -> list[dict]:
    """Muestra del log semanal: misma fecha de hoy + algunos dias atras."""
    hoy = date.today()
    filas = []
    # Hoy: agregar todos los tipos de la muestra
    filas.append({"fecha": hoy, "tipo": "smtp_error", "gravedad": "error",
                  "cantidad": 1, "muestra": "Correo 2: SMTP refuso conexion."})
    filas.append({"fecha": hoy, "tipo": "destinatario_faltante", "gravedad": "error",
                  "cantidad": 1, "muestra": "Correo 1: destinatario vacio."})
    filas.append({"fecha": hoy, "tipo": "email_entidad_faltante", "gravedad": "aviso",
                  "cantidad": 2, "muestra": "PONDERA SPA sin email."})
    filas.append({"fecha": hoy, "tipo": "pendiente_fuera_ventana", "gravedad": "aviso",
                  "cantidad": 1, "muestra": "EJEMPLO SPA fuera de ventana."})
    # Algunos dias atras
    filas.append({"fecha": hoy - timedelta(days=2), "tipo": "email_entidad_faltante",
                  "gravedad": "aviso", "cantidad": 1, "muestra": "Otra SPA sin email."})
    filas.append({"fecha": hoy - timedelta(days=5), "tipo": "smtp_error",
                  "gravedad": "error", "cantidad": 1,
                  "muestra": "Correo 1: timeout en smtp.org.cl"})
    return filas


# ---------------------------------------------------------------------------
# Datos de muestra para los correos
# ---------------------------------------------------------------------------

def _cargar_pendientes_reales() -> list[dict]:
    """Toma las pendientes del _estado_codigos.json si existe; si no, devuelve
    una lista vacia (luego se sustituye por datos sinteticos)."""
    path = os.path.join(DATA_DIR, "_estado_codigos.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            estado = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    pendientes = []
    for datos in estado.get("sin_codigo", {}).values():
        pendientes.append({
            "fecha_resolucion":   datos.get("fecha_resolucion", ""),
            "entidad":            datos.get("entidad", ""),
            "rut":                datos.get("rut_completo") or datos.get("rut", ""),
            "tipo_servicio":      datos.get("tipo_servicio", ""),
            "codigo_institucion": datos.get("codigo_institucion", "No asignado"),
            "email":              datos.get("email", ""),
            "primera_deteccion":  datos.get("primera_deteccion", ""),
        })
    return pendientes


def filas_nuevas_muestra() -> list[dict]:
    """Lista 'nuevas sin codigo' para el preview. Incluye una entidad SIN
    email para ver como se renderiza el guion."""
    reales = _cargar_pendientes_reales()
    if reales:
        # Tomamos 2 reales y forzamos la primera sin email para variedad
        muestra = reales[:2]
        if len(muestra) >= 1:
            muestra[0] = {**muestra[0], "email": ""}
        return muestra
    return [
        {
            "fecha_resolucion":   "2026-05-20",
            "entidad":            "EJEMPLO ASESORES SPA",
            "rut":                "77.123.456-7",
            "tipo_servicio":      "ASESORIA DE INVERSION",
            "codigo_institucion": "No asignado",
            "email":              "",  # sin email -> aparece como '-'
            "primera_deteccion":  "2026-05-20",
        },
        {
            "fecha_resolucion":   "2026-05-22",
            "entidad":            "MUESTRA CAPITAL SPA",
            "rut":                "76.987.654-3",
            "tipo_servicio":      "GESTION DE CARTERAS",
            "codigo_institucion": "No asignado",
            "email":              "contacto@muestra-capital.cl",
            "primera_deteccion":  "2026-05-22",
        },
    ]


def filas_asignados_muestra() -> list[dict]:
    """Lista 'codigos recien asignados' con 2 entradas, una con y una sin email."""
    return [
        {
            "fecha_resolucion":   "2026-04-10",
            "entidad":            "EJEMPLO LEASING SPA",
            "rut":                "77.111.222-3",
            "tipo_servicio":      "ARRENDAMIENTO FINANCIERO",
            "codigo_institucion": "0432",
            "email":              "operaciones@ejemplo-leasing.cl",
            "primera_deteccion":  "2026-04-15",
        },
        {
            "fecha_resolucion":   "2026-04-18",
            "entidad":            "SEGUNDA MUESTRA SPA",
            "rut":                "76.555.666-K",
            "tipo_servicio":      "DISTRIBUCION DE SEGUROS",
            "codigo_institucion": "0433",
            "email":              "",  # sin email -> '-' y dispararia incidencia
            "primera_deteccion":  "2026-04-19",
        },
    ]


# ---------------------------------------------------------------------------
# Generadores de cada preview
# ---------------------------------------------------------------------------

def generar_dashboard() -> str:
    records = cargar_records_desde_json()
    if not records:
        print("AVISO: no hay data/*.json para alimentar el dashboard preview.")
        records = []
    html = dashboard.generar_html(
        records,
        incidencias_hoy   = incidencias_muestra(),
        resumen_semana    = resumen_semana_muestra(),
    )
    path = os.path.join(PREVIEW_DIR, "dashboard_preview.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def _wrap_email_html(asunto: str, html_body: str) -> str:
    """Envuelve el cuerpo del correo en una pagina con cabecera mostrando el
    asunto y los destinatarios, para que el preview se sienta como verlo en
    el cliente de correo."""
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Preview - {asunto}</title>
<style>
  body {{ background:#e2e8f0; margin:0; padding:24px;
         font-family: system-ui, -apple-system, sans-serif; }}
  .wrap {{ max-width: 820px; margin: 0 auto;
           background: white; border-radius: 6px; overflow: hidden;
           box-shadow: 0 2px 10px rgba(0,0,0,.1); }}
  .hdr {{ background: #f7fafc; padding: 14px 22px;
          border-bottom: 1px solid #e2e8f0; font-size: 13px; color: #4a5568; }}
  .hdr strong {{ color: #1a365d; }}
  .body {{ padding: 0 4px; }}
  .tag {{ display: inline-block; background: #fef3c7; color: #92400e;
          padding: 2px 8px; border-radius: 10px; font-size: 11px;
          font-weight: 700; margin-left: 8px; }}
</style></head><body>
<div class="wrap">
  <div class="hdr">
    <div><strong>Asunto:</strong> {asunto} <span class="tag">PREVIEW</span></div>
    <div><strong>De:</strong> CMF Monitor &lt;cmf-monitor@ejemplo.cl&gt;</div>
    <div><strong>Para:</strong> tareas@ejemplo.cl</div>
  </div>
  <div class="body">{html_body}</div>
</div>
</body></html>"""


def _render_mail(template_basename: str, columnas, filas, asunto: str) -> str:
    """Renderiza el HTML del correo (con tabla, contactos, etc.) y lo envuelve
    en el visor de preview."""
    tpl_path = os.path.join(TEMPLATES_DIR, template_basename + ".html")
    with open(tpl_path, encoding="utf-8") as f:
        plantilla = f.read()

    contexto = {
        "fecha":         datetime.today().strftime("%d/%m/%Y"),
        "n":             str(len(filas)),
        "tabla":         mailer._tabla_html(filas, columnas),
        "contactos":     mailer._contactos_html(filas),
        "dashboard_url": "http://localhost:8080/",
    }
    cuerpo = Template(plantilla).safe_substitute(contexto)
    return _wrap_email_html(asunto, cuerpo)


def generar_mail_nuevas() -> str:
    filas = filas_nuevas_muestra()
    html = _render_mail(
        "mail_nuevas",
        mailer.COLUMNAS_NUEVAS,
        filas,
        asunto=f"[CMF Monitor] {len(filas)} nueva(s) entidad(es) sin codigo de institucion — preview",
    )
    path = os.path.join(PREVIEW_DIR, "mail_nuevas_preview.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def generar_mail_asignados() -> str:
    filas = filas_asignados_muestra()
    html = _render_mail(
        "mail_asignados",
        mailer.COLUMNAS_ASIGNADOS,
        filas,
        asunto=f"[CMF Monitor] {len(filas)} codigo(s) de institucion recien asignado(s) — preview",
    )
    path = os.path.join(PREVIEW_DIR, "mail_asignados_preview.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def main(abrir: bool) -> None:
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    paths = [
        generar_dashboard(),
        generar_mail_nuevas(),
        generar_mail_asignados(),
    ]

    print("Previews generados:")
    for p in paths:
        print(f"  {p}")

    if abrir:
        for p in paths:
            webbrowser.open(f"file:///{p.replace(os.sep, '/')}")


if __name__ == "__main__":
    abrir = len(sys.argv) > 1 and sys.argv[1] == "open"
    main(abrir=abrir)
