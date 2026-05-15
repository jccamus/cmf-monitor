"""
Configuración centralizada. Lee variables de entorno y entrega valores
sensatos por defecto cuando faltan. El resto del código solo lee de aquí
y no toca os.environ directamente.

Variables soportadas (todas opcionales — si faltan, mailer.py omite el envío):

  CMF_SMTP_HOST              servidor SMTP (ej. smtp.miorganizacion.cl)
  CMF_SMTP_PORT              puerto (25/465/587). Default 587
  CMF_SMTP_USER              usuario para autenticarse
  CMF_SMTP_PASS              password
  CMF_SMTP_TLS               starttls | ssl | none. Default starttls
  CMF_MAIL_FROM              remitente, ej. 'CMF Monitor <cmf@org.cl>'
  CMF_MAIL_TO_NUEVAS         destinatario(s) del correo de nuevas sin código
  CMF_MAIL_TO_ASIGNADOS      destinatario(s) del correo de códigos asignados
  CMF_MAIL_SUBJECT_NUEVAS    asunto del correo 1 (admite $n y $fecha)
  CMF_MAIL_SUBJECT_ASIGNADOS asunto del correo 2 (admite $n y $fecha)
  CMF_DASHBOARD_URL          URL del dashboard, se inserta en el footer

Múltiples destinatarios: separa con coma. Ej:
  CMF_MAIL_TO_NUEVAS="ana@org.cl, pedro@org.cl"
"""
import os

# --- SMTP ---
SMTP_HOST = os.environ.get("CMF_SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("CMF_SMTP_PORT", "587") or 587)
SMTP_USER = os.environ.get("CMF_SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("CMF_SMTP_PASS", "")
SMTP_TLS  = os.environ.get("CMF_SMTP_TLS", "starttls").strip().lower()

# --- Direcciones ---
MAIL_FROM         = os.environ.get("CMF_MAIL_FROM", "").strip()
MAIL_TO_NUEVAS    = os.environ.get("CMF_MAIL_TO_NUEVAS", "").strip()
MAIL_TO_ASIGNADOS = os.environ.get("CMF_MAIL_TO_ASIGNADOS", "").strip()

# --- Asuntos (usan $n y $fecha, sintaxis string.Template) ---
SUBJECT_NUEVAS = os.environ.get(
    "CMF_MAIL_SUBJECT_NUEVAS",
    "[CMF Monitor] $n nueva(s) entidad(es) sin código de institución — $fecha",
)
SUBJECT_ASIGNADOS = os.environ.get(
    "CMF_MAIL_SUBJECT_ASIGNADOS",
    "[CMF Monitor] $n código(s) de institución recién asignado(s) — $fecha",
)

# --- Dashboard ---
DASHBOARD_URL = os.environ.get("CMF_DASHBOARD_URL", "http://localhost:8080/").strip()


def smtp_configurado() -> bool:
    """True si hay configuración mínima para intentar enviar correos."""
    return bool(SMTP_HOST and MAIL_FROM)
