"""
Registro de incidencias detectadas en cada corrida del pipeline.

Cada PASO llama issues.registrar(...) cuando detecta algo que el equipo
de operacion deberia revisar (datos faltantes, fallas de envio, regex
que no parseo una resolucion, etc.). El dashboard lee desde aqui para
mostrar la seccion "Errores y temas a revisar".

Tipos canonicos en uso hoy (mantener consistentes para que el dashboard
los agrupe bien):

  - entidad_no_extraida      scraper no pudo extraer 'entidad' del texto
  - email_entidad_faltante   entidad en listas de novedades sin email
  - pendiente_fuera_ventana  entidad pendiente que ya no aparece en CMF
  - smtp_no_configurado      hay novedades pero falta SMTP
  - destinatario_faltante    hay novedades pero falta CMF_MAIL_TO_*
  - smtp_error               excepcion al enviar (timeout, auth, etc.)
"""
import json
from typing import Any

import db

GRAVEDADES = {"aviso", "error"}

# Etiquetas legibles para el dashboard (titulo + descripcion del grupo).
ETIQUETAS: dict[str, tuple[str, str]] = {
    "entidad_no_extraida": (
        "Entidad no extraida del texto de la resolucion",
        "El regex no logro identificar la entidad. Revisar la materia original "
        "y, si la CMF cambio el formato, extender _TIPOS_SERVICIO en scraper.py.",
    ),
    "email_entidad_faltante": (
        "Entidad sin email de contacto",
        "Aparece en una lista de novedades (nuevas sin codigo o codigos asignados) "
        "pero la ficha CMF no trae email. Completar manualmente desde CMF si es posible.",
    ),
    "pendiente_fuera_ventana": (
        "Pendiente fuera de la ventana de 90 dias",
        "Entidad que estaba en seguimiento pero ya no aparece en el listado CMF de los "
        "ultimos 90 dias. Revisar manualmente si recibio codigo o si la resolucion fue retirada.",
    ),
    "smtp_no_configurado": (
        "SMTP no configurado",
        "Hubo novedades para notificar pero faltan CMF_SMTP_HOST / CMF_MAIL_FROM en .env. "
        "Completar la configuracion y volver a correr.",
    ),
    "destinatario_faltante": (
        "Falta destinatario de correo",
        "Hay novedades pero el destinatario (CMF_MAIL_TO_NUEVAS / CMF_MAIL_TO_ASIGNADOS) "
        "esta vacio en .env.",
    ),
    "smtp_error": (
        "Error enviando correo via SMTP",
        "Excepcion al intentar entregar el correo. Revisar credenciales, red y politicas "
        "del servidor saliente.",
    ),
    "scraper_error_red": (
        "Error de red al scrapear CMF",
        "El listado de CMF no se pudo descargar. El pipeline continua con los datos "
        "previos en la DB; el dashboard de hoy refleja la ultima corrida exitosa.",
    ),
}


def _label(tipo: str) -> tuple[str, str]:
    return ETIQUETAS.get(tipo, (tipo.replace("_", " ").title(), ""))


def limpiar_hoy() -> None:
    """Borra las incidencias de hoy. Llamar al inicio del pipeline para
    que la seccion 'hoy' del dashboard refleje el ultimo estado y no
    acumule duplicados al re-correr."""
    with db.conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM incidencias WHERE fecha = CURRENT_DATE")


def registrar(
    tipo: str,
    gravedad: str,
    mensaje: str,
    contexto: dict[str, Any] | None = None,
) -> None:
    if gravedad not in GRAVEDADES:
        gravedad = "aviso"
    payload = json.dumps(contexto or {}, ensure_ascii=False)
    with db.conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO incidencias (tipo, gravedad, mensaje, contexto) "
                "VALUES (%s, %s, %s, %s::jsonb)",
                (tipo, gravedad, mensaje, payload),
            )


def cargar_hoy() -> list[dict]:
    """Incidencias registradas en la corrida de hoy."""
    with db.conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tipo, gravedad, mensaje, contexto, created_at "
                "FROM incidencias WHERE fecha = CURRENT_DATE "
                "ORDER BY gravedad DESC, tipo, id"
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def cargar_ultimos_dias(n: int = 7) -> list[dict]:
    """Resumen agrupado por fecha + tipo + gravedad de los ultimos N dias
    (incluye HOY)."""
    with db.conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fecha, tipo, gravedad,
                       COUNT(*)            AS cantidad,
                       MIN(mensaje)        AS muestra
                FROM incidencias
                WHERE fecha >= CURRENT_DATE - (%s::int - 1) * INTERVAL '1 day'
                GROUP BY fecha, tipo, gravedad
                ORDER BY fecha DESC, gravedad DESC, tipo
                """,
                (n,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
