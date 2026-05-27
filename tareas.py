"""
Detecta transiciones del campo 'codigo_institucion' entre corridas usando
la tabla estado_codigos (reemplaza el viejo data/_estado_codigos.json).

  - nuevas_sin_codigo: entidades autorizadas que aparecen ahora sin codigo
    y que NO estaban en la lista de pendientes de la corrida anterior. Es
    decir, entran hoy a la lista de seguimiento.
  - recien_asignados: entidades que estaban en la lista de pendientes y
    ahora SI tienen un codigo de institucion asignado. Es decir, salen hoy
    de la lista porque la CMF ya las codifico.

Salidas para mailer.py (solo si la lista no esta vacia):
  reports/tareas_nuevas_sin_codigo.json
  reports/tareas_recien_asignados.json
"""
import json
import os
import sys
from datetime import datetime, date

import db
import issues

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

_VACIOS_EMAIL = {"", "-", "---"}


def _sin_codigo(codigo: str) -> bool:
    return (codigo or "") in ("", "No asignado")


def _resumen_db(row: dict, primera_deteccion: str) -> dict:
    """Subset de campos para reportes/comparacion (mismo shape que la
    version en server, asi mailer.py funciona igual)."""
    fecha_res = row.get("fecha")
    if isinstance(fecha_res, date):
        fecha_res = fecha_res.strftime("%Y-%m-%d")
    return {
        "entidad":            row.get("entidad", "") or "",
        "rut":                row.get("rut", "") or "",
        "rut_completo":       row.get("rut_completo", "") or "",
        "fecha_resolucion":   fecha_res or "",
        "tipo_servicio":      row.get("tipo_servicio", "") or "",
        "tipo_empresa":       row.get("tipo_empresa", "") or "",
        "codigo_institucion": row.get("codigo_institucion", "") or "",
        "email":              row.get("email", "") or "",
        "primera_deteccion":  primera_deteccion,
    }


def _escribir_o_borrar(path: str, lista: list[dict]) -> None:
    if lista:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(lista, f, ensure_ascii=False, indent=2)
    elif os.path.exists(path):
        os.remove(path)


def run(fecha: str | None = None) -> dict:
    if fecha is None:
        fecha = datetime.today().strftime("%Y-%m-%d")

    nuevas: list[dict] = []
    asignados: list[dict] = []

    with db.conectar() as conn:
        with conn.cursor() as cur:
            # Universo: autorizadas con RUT y vigentes
            cur.execute(
                "SELECT fecha, entidad, rut, rut_completo, tipo_servicio, "
                "       tipo_empresa, codigo_institucion, email "
                "FROM resoluciones "
                "WHERE autoriza_prestacion = TRUE "
                "  AND rut <> '' "
                "  AND LOWER(TRIM(vigencia)) <> 'no vigente'"
            )
            cols = [d.name for d in cur.description]
            autorizadas = [dict(zip(cols, row)) for row in cur.fetchall()]

            # Estado previo
            cur.execute("SELECT rut, primera_deteccion FROM estado_codigos")
            sin_codigo_previo: dict[str, date] = {
                rut: pd for rut, pd in cur.fetchall()
            }

        sin_codigo_actual: dict[str, dict] = {}
        ruts_hoy: set[str] = set()

        for r in autorizadas:
            rut = r["rut"]
            ruts_hoy.add(rut)
            if _sin_codigo(r.get("codigo_institucion", "")):
                primera = sin_codigo_previo.get(rut)
                if primera:
                    resumen = _resumen_db(r, primera.strftime("%Y-%m-%d"))
                else:
                    resumen = _resumen_db(r, fecha)
                    nuevas.append(resumen)
                sin_codigo_actual[rut] = resumen
            else:
                if rut in sin_codigo_previo:
                    asignados.append(
                        _resumen_db(r, sin_codigo_previo[rut].strftime("%Y-%m-%d"))
                    )

        # Entidades que estaban pendientes pero hoy no aparecen en autorizadas
        # (salieron de la ventana de 90 dias del scraper). Las preservamos en
        # estado_codigos para no perderles el rastro y se registran como
        # incidencia para que el equipo las revise a mano.
        fuera_de_ventana = 0
        with conn.cursor() as cur:
            cur.execute("SELECT rut, entidad, rut_completo FROM estado_codigos")
            estado_previo = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
        previos_ruts = set(estado_previo.keys())
        for rut in previos_ruts:
            if rut not in ruts_hoy:
                fuera_de_ventana += 1
                ent, rc = estado_previo[rut]
                issues.registrar(
                    "pendiente_fuera_ventana", "aviso",
                    f"{ent or '(sin nombre)'} (RUT {rc or rut}) sigue pendiente pero "
                    f"ya no aparece en la ventana de 90 dias del scraper.",
                    {"rut": rut, "entidad": ent, "rut_completo": rc},
                )

        # Sincronizar estado_codigos:
        #   - upsert las que estan sin codigo hoy (sin_codigo_actual)
        #   - delete las que recien recibieron codigo (asignados)
        with conn.cursor() as cur:
            for resumen in sin_codigo_actual.values():
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
                       updated_at         = now()
                    """,
                    (
                        resumen["rut"], resumen["entidad"], resumen["rut_completo"],
                        resumen["fecha_resolucion"] or None,
                        resumen["tipo_servicio"], resumen["tipo_empresa"],
                        resumen["codigo_institucion"], resumen["email"],
                        resumen["primera_deteccion"],
                    ),
                )
            for r in asignados:
                cur.execute("DELETE FROM estado_codigos WHERE rut = %s", (r["rut"],))

            cur.execute(
                "INSERT INTO meta (clave, valor) VALUES ('ultima_corrida', %s) "
                "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
                (fecha,),
            )

    # Cuantas pendientes hay AHORA (incluye las fuera de ventana, que NO
    # estaban en sin_codigo_actual pero siguen en la tabla)
    total_pendientes = len(sin_codigo_actual) + fuera_de_ventana

    # Incidencia por cada entidad de las listas que no tenga email de contacto.
    # Aplica a AMBAS listas: en "nuevas" sirve como recordatorio de que falta
    # un dato; en "asignados" es donde realmente se usaria para contactar.
    for resumen, lista_nombre in (
        [(r, "nuevas_sin_codigo") for r in nuevas]
      + [(r, "recien_asignados") for r in asignados]
    ):
        email = (resumen.get("email") or "").strip()
        if email in _VACIOS_EMAIL:
            ident = resumen.get("rut_completo") or resumen.get("rut") or "sin RUT"
            issues.registrar(
                "email_entidad_faltante", "aviso",
                f"{resumen.get('entidad') or '(sin nombre)'} (RUT {ident}) "
                f"esta en la lista '{lista_nombre}' pero no tiene email de contacto.",
                {
                    "rut": resumen.get("rut", ""),
                    "entidad": resumen.get("entidad", ""),
                    "lista": lista_nombre,
                },
            )

    os.makedirs(REPORTS_DIR, exist_ok=True)
    _escribir_o_borrar(os.path.join(REPORTS_DIR, "tareas_nuevas_sin_codigo.json"), nuevas)
    _escribir_o_borrar(os.path.join(REPORTS_DIR, "tareas_recien_asignados.json"), asignados)

    print(f"  {len(nuevas)} nueva(s) entidad(es) sin codigo (entran a la lista)")
    print(f"  {len(asignados)} entidad(es) con codigo recien asignado (salen de la lista)")
    print(f"  {total_pendientes} entidad(es) pendientes en total"
          f" (de las cuales {fuera_de_ventana} estan fuera de la ventana de 90 dias)")

    return {"nuevas_sin_codigo": nuevas, "recien_asignados": asignados}


if __name__ == "__main__":
    fecha_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(fecha_arg)
