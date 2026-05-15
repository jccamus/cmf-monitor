"""
Detecta transiciones del campo 'codigo_institucion' entre corridas:

  - nuevas_sin_codigo: entidades autorizadas que aparecen ahora sin código y
    que NO estaban en la lista de pendientes de la corrida anterior. Es decir,
    entraron hoy a la lista de seguimiento.

  - recien_asignados: entidades que estaban en la lista de pendientes y ahora
    SÍ tienen un código de institución asignado. Es decir, salieron hoy de la
    lista porque la CMF ya las codificó.

El estado entre corridas vive en data/_estado_codigos.json (se commitea con
el resto de data/ para que sobreviva entre ejecuciones del cron).

Salidas para mailer.py (solo se escriben si la lista no está vacía):
  reports/tareas_nuevas_sin_codigo.json
  reports/tareas_recien_asignados.json
"""
import json
import os
import sys
from datetime import datetime

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
ESTADO_PATH = os.path.join(DATA_DIR, "_estado_codigos.json")


def _sin_codigo(r: dict) -> bool:
    return r.get("codigo_institucion", "") in ("", "No asignado")


def _resumen(r: dict, primera_deteccion: str) -> dict:
    """Subset de campos relevantes para los reportes y la comparación."""
    return {
        "entidad":            r.get("entidad", ""),
        "rut":                r.get("rut", ""),
        "rut_completo":       r.get("rut_completo", ""),
        "fecha_resolucion":   r.get("fecha", ""),
        "tipo_servicio":      r.get("tipo_servicio", ""),
        "tipo_empresa":       r.get("tipo_empresa", ""),
        "codigo_institucion": r.get("codigo_institucion", ""),
        "primera_deteccion":  primera_deteccion,
    }


def _cargar_estado() -> dict:
    if not os.path.exists(ESTADO_PATH):
        return {"sin_codigo": {}}
    try:
        with open(ESTADO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"sin_codigo": {}}


def _guardar_estado(estado: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def _escribir_o_borrar(path: str, lista: list[dict]) -> None:
    """Si la lista tiene elementos, escribe el JSON. Si está vacía, borra el
    archivo (señal para mailer.py de que no hay nada que enviar)."""
    if lista:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(lista, f, ensure_ascii=False, indent=2)
    elif os.path.exists(path):
        os.remove(path)


def run(fecha: str | None = None) -> dict:
    """Procesa el JSON del día y calcula las transiciones de código.
    Retorna {'nuevas_sin_codigo': [...], 'recien_asignados': [...]} para que
    mailer.py los consuma directamente."""
    if fecha is None:
        fecha = datetime.today().strftime("%Y-%m-%d")

    path = os.path.join(DATA_DIR, f"{fecha}.json")
    if not os.path.exists(path):
        print(f"No existe {path}. Ejecuta scraper.py primero.")
        return {"nuevas_sin_codigo": [], "recien_asignados": []}

    with open(path, encoding="utf-8") as f:
        records: list[dict] = json.load(f)

    # Universo: entidades autorizadas, con RUT (clave estable) y vigentes.
    autorizadas = [
        r for r in records
        if r.get("autoriza_prestacion")
        and r.get("rut")
        and r.get("vigencia", "").strip().lower() != "no vigente"
    ]

    estado = _cargar_estado()
    sin_codigo_previo: dict = estado.get("sin_codigo", {})

    nuevas: list[dict] = []
    asignados: list[dict] = []
    sin_codigo_actual: dict = {}

    for r in autorizadas:
        rut = r["rut"]
        if _sin_codigo(r):
            previa = sin_codigo_previo.get(rut)
            if previa:
                # Ya estaba en la lista; conserva su fecha de primera detección.
                resumen = _resumen(r, previa.get("primera_deteccion", fecha))
            else:
                # Caso NUEVO en esta corrida.
                resumen = _resumen(r, fecha)
                nuevas.append(resumen)
            sin_codigo_actual[rut] = resumen
        else:
            # Tiene código; si estaba pendiente, es un recién asignado.
            if rut in sin_codigo_previo:
                primera = sin_codigo_previo[rut].get("primera_deteccion", "")
                asignados.append(_resumen(r, primera))

    # Entidades que estaban pendientes en la corrida anterior pero no aparecen
    # en el JSON de hoy: salieron de la ventana de 90 dias del scraper. Las
    # mantenemos en el estado para no perderles el rastro; su codigo no se
    # detectara automaticamente sin un mecanismo de re-consulta directa a CMF.
    # (TODO: agregar un comando manual o un re-check periodico via enricher.)
    ruts_hoy = {r["rut"] for r in autorizadas}
    fuera_de_ventana = 0
    for rut, previa in sin_codigo_previo.items():
        if rut not in ruts_hoy and rut not in sin_codigo_actual:
            sin_codigo_actual[rut] = previa
            fuera_de_ventana += 1

    estado["sin_codigo"]    = sin_codigo_actual
    estado["ultima_corrida"] = fecha
    _guardar_estado(estado)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    _escribir_o_borrar(os.path.join(REPORTS_DIR, "tareas_nuevas_sin_codigo.json"), nuevas)
    _escribir_o_borrar(os.path.join(REPORTS_DIR, "tareas_recien_asignados.json"), asignados)

    print(f"  {len(nuevas)} nueva(s) entidad(es) sin código (entran a la lista)")
    print(f"  {len(asignados)} entidad(es) con código recién asignado (salen de la lista)")
    print(f"  {len(sin_codigo_actual)} entidad(es) pendientes en total"
          f" (de las cuales {fuera_de_ventana} están fuera de la ventana de 90 días)")

    return {"nuevas_sin_codigo": nuevas, "recien_asignados": asignados}


if __name__ == "__main__":
    fecha_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(fecha_arg)
