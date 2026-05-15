"""
Envía los dos correos de tareas vía SMTP usando solo la biblioteca estándar
de Python (smtplib + email.message). Cada correo se manda de forma
independiente: si uno falla, el otro de todas formas se intenta.

Si no hay configuración SMTP en las variables de entorno (ver config.py),
no hace nada y avisa por stdout. Esto permite que el mismo pipeline corra
en entornos sin correo (ej. GitHub Actions) sin romperse.

Las plantillas viven en templates/*.html y templates/*.txt y se pueden
editar sin tocar el código. Usan la sintaxis de string.Template ($var)
para que no entren en conflicto con CSS u otras llaves.

Placeholders disponibles en las plantillas:
  $fecha           fecha de la corrida (DD/MM/YYYY)
  $n              cantidad de entidades en la lista
  $tabla          tabla HTML (o texto) con los datos
  $dashboard_url  URL del dashboard
"""
import html
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from string import Template

import config

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Columnas para cada tipo de correo (clave en el JSON, etiqueta visible).
COLUMNAS_NUEVAS = [
    ("fecha_resolucion", "Fecha resolución"),
    ("entidad",          "Nombre"),
    ("rut",              "RUT"),
    ("tipo_servicio",    "Tipo de servicio"),
    ("email",            "Email de contacto"),
]
COLUMNAS_ASIGNADOS = [
    ("primera_deteccion",  "Detectado el"),
    ("entidad",            "Nombre"),
    ("rut",                "RUT"),
    ("codigo_institucion", "Código asignado"),
    ("fecha_resolucion",   "Fecha resolución"),
    ("email",              "Email de contacto"),
]

_FECHAS = {"fecha_resolucion", "primera_deteccion"}
_VACIOS_EMAIL = {"", "-", "---"}


# ---------------------------------------------------------------------------
# Render de tabla
# ---------------------------------------------------------------------------

def _fmt_fecha(s: str) -> str:
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return s or "-"


def _valor(r: dict, key: str) -> str:
    v = r.get(key, "") or "-"
    return _fmt_fecha(v) if key in _FECHAS else str(v)


def _celda_html(r: dict, key: str, td_style: str) -> str:
    """Renderiza una celda. Convierte el campo 'email' en un mailto: clickable."""
    val = _valor(r, key)
    if key == "email" and val not in _VACIOS_EMAIL:
        esc = html.escape(val)
        return f'<td style="{td_style}"><a href="mailto:{esc}">{esc}</a></td>'
    return f'<td style="{td_style}">{html.escape(val)}</td>'


def _tabla_html(filas: list[dict], columnas: list[tuple[str, str]]) -> str:
    th_style = ("text-align:left;background:#1a365d;color:white;"
                "padding:8px 10px;border:1px solid #1a365d;font-size:13px;")
    td_style = "padding:6px 10px;border:1px solid #e2e8f0;font-size:13px;"
    table_style = ("border-collapse:collapse;width:100%;"
                   "font-family:system-ui,-apple-system,sans-serif;"
                   "margin:16px 0;")

    head = "".join(f'<th style="{th_style}">{html.escape(lbl)}</th>' for _, lbl in columnas)
    rows = []
    for r in filas:
        cells = "".join(_celda_html(r, k, td_style) for k, _ in columnas)
        rows.append(f"<tr>{cells}</tr>")
    return (f'<table style="{table_style}">'
            f'<thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody>'
            f'</table>')


def _contactos_html(filas: list[dict]) -> str:
    """Bloque HTML 'Contactos disponibles' para inyectar en el cuerpo del
    correo. Se omite si ninguna entidad tiene email."""
    items = []
    for r in filas:
        email = (r.get("email") or "").strip()
        if email in _VACIOS_EMAIL:
            continue
        esc_e = html.escape(email)
        esc_n = html.escape(r.get("entidad", "(sin nombre)"))
        items.append(f'  <li><a href="mailto:{esc_e}">{esc_e}</a> — {esc_n}</li>')
    if not items:
        return ""
    return (
        '<p style="margin:16px 0 8px"><strong>Contactos disponibles:</strong></p>\n'
        '<ul style="margin:0 0 16px;padding-left:20px;font-size:14px">\n'
        + "\n".join(items)
        + "\n</ul>"
    )


def _contactos_texto(filas: list[dict]) -> str:
    """Equivalente en texto plano del bloque de contactos."""
    items = []
    for r in filas:
        email = (r.get("email") or "").strip()
        if email in _VACIOS_EMAIL:
            continue
        items.append(f"  - {email} ({r.get('entidad', '(sin nombre)')})")
    if not items:
        return ""
    return "Contactos disponibles:\n" + "\n".join(items)


def _tabla_texto(filas: list[dict], columnas: list[tuple[str, str]]) -> str:
    """Tabla ASCII simple para el fallback de texto plano."""
    headers = [lbl for _, lbl in columnas]
    body = [[_valor(r, k) for k, _ in columnas] for r in filas]
    widths = [
        max(len(headers[i]), max((len(row[i]) for row in body), default=0))
        for i in range(len(headers))
    ]
    sep = "  "
    out = [sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    out.append(sep.join("-" * w for w in widths))
    for row in body:
        out.append(sep.join(v.ljust(widths[i]) for i, v in enumerate(row)))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Render de plantilla
# ---------------------------------------------------------------------------

def _renderizar(template_path: str, contexto: dict) -> str:
    if not os.path.exists(template_path):
        return ""
    with open(template_path, encoding="utf-8") as f:
        return Template(f.read()).safe_substitute(contexto)


# ---------------------------------------------------------------------------
# Envío SMTP
# ---------------------------------------------------------------------------

def _abrir_smtp() -> smtplib.SMTP:
    if config.SMTP_TLS == "ssl":
        ctx = ssl.create_default_context()
        return smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT,
                                context=ctx, timeout=30)
    smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
    if config.SMTP_TLS == "starttls":
        smtp.starttls(context=ssl.create_default_context())
    return smtp


def _enviar(asunto: str, destinatarios: str, html_body: str, texto_body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"]    = config.MAIL_FROM
    msg["To"]      = destinatarios
    msg.set_content(texto_body or "Este correo requiere un cliente que soporte HTML.")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    smtp = _abrir_smtp()
    try:
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASS)
        smtp.send_message(msg)
    finally:
        smtp.quit()


def _correo(
    filas: list[dict],
    asunto_tpl: str,
    destinatarios: str,
    html_template: str,
    txt_template: str,
    columnas: list[tuple[str, str]],
    etiqueta: str,
) -> None:
    if not filas:
        print(f"  {etiqueta}: sin novedades, no se envía correo.")
        return
    if not destinatarios:
        print(f"  {etiqueta}: hay {len(filas)} novedad(es) pero falta destinatario "
              f"(CMF_MAIL_TO_*); omitiendo.")
        return

    fecha = datetime.today().strftime("%d/%m/%Y")
    contexto_html = {
        "fecha":         fecha,
        "n":             str(len(filas)),
        "tabla":         _tabla_html(filas, columnas),
        "contactos":     _contactos_html(filas),
        "dashboard_url": config.DASHBOARD_URL,
    }
    contexto_txt = {
        **contexto_html,
        "tabla":     _tabla_texto(filas, columnas),
        "contactos": _contactos_texto(filas),
    }

    asunto    = Template(asunto_tpl).safe_substitute(n=str(len(filas)), fecha=fecha)
    html_body = _renderizar(html_template, contexto_html)
    txt_body  = _renderizar(txt_template, contexto_txt)

    if not html_body and not txt_body:
        print(f"  {etiqueta}: no existe plantilla {html_template}; omitiendo.")
        return

    print(f"  {etiqueta}: enviando '{asunto}' a {destinatarios}")
    try:
        _enviar(asunto, destinatarios, html_body, txt_body)
        print(f"  {etiqueta}: OK")
    except Exception as exc:
        # No relanzar: el otro correo debe poder intentarse igual.
        print(f"  {etiqueta}: ERROR enviando correo: {exc}")


def notificar(novedades: dict) -> None:
    """Envía los dos correos de forma independiente.
    novedades: dict con 'nuevas_sin_codigo' y 'recien_asignados'."""
    if not config.smtp_configurado():
        print("SMTP no configurado (faltan CMF_SMTP_HOST / CMF_MAIL_FROM); "
              "se omiten los envíos de correo.")
        return

    _correo(
        filas         = novedades.get("nuevas_sin_codigo", []),
        asunto_tpl    = config.SUBJECT_NUEVAS,
        destinatarios = config.MAIL_TO_NUEVAS,
        html_template = os.path.join(TEMPLATES_DIR, "mail_nuevas.html"),
        txt_template  = os.path.join(TEMPLATES_DIR, "mail_nuevas.txt"),
        columnas      = COLUMNAS_NUEVAS,
        etiqueta      = "Correo 1 (nuevas sin código)",
    )

    _correo(
        filas         = novedades.get("recien_asignados", []),
        asunto_tpl    = config.SUBJECT_ASIGNADOS,
        destinatarios = config.MAIL_TO_ASIGNADOS,
        html_template = os.path.join(TEMPLATES_DIR, "mail_asignados.html"),
        txt_template  = os.path.join(TEMPLATES_DIR, "mail_asignados.txt"),
        columnas      = COLUMNAS_ASIGNADOS,
        etiqueta      = "Correo 2 (códigos asignados)",
    )
