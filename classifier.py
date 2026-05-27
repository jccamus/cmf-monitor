"""
Asigna una categoria a cada resolucion del dia segun palabras clave en el
texto. Actualiza la columna 'categoria' en la tabla resoluciones.
"""

import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime

import db

# Orden importa: la primera coincidencia gana.
# Las categorias mas especificas deben ir antes que las generales.
REGLAS: list[tuple[str, list[str]]] = [
    ("nueva_actividad",    ["AUTORIZA LA PRESTACIÓN", "AUTORIZA EL INICIO", "AUTORIZA INICIO",
                            "AUTORIZA LA OPERACIÓN", "AUTORIZA OPERACIÓN"]),
    ("inscripción",        ["INSCRIBE EN EL REGISTRO", "INSCRIPCIÓN EN EL REGISTRO",
                            "INCORPORA AL REGISTRO", "AGREGA AL REGISTRO"]),
    ("cancelación",        ["CANCELA LA INSCRIPCIÓN", "CANCELA INSCRIPCIÓN", "REVOCA",
                            "DA DE BAJA", "ELIMINA DEL REGISTRO", "CANCELA EL REGISTRO"]),
    ("cambio_directivo",   ["DIRECTOR", "GERENTE GENERAL", "GERENTE", "APODERADO",
                            "REPRESENTANTE LEGAL", "ADMINISTRADOR"]),
    ("fusión_adquisición", ["FUSIÓN", "FUSIÓN POR", "ABSORCIÓN", "ADQUISICIÓN",
                            "ESCISIÓN", "DIVISIÓN"]),
    ("compraventa",        ["COMPRAVENTA", "TRANSFERENCIA DE ACCIONES", "ENAJENACIÓN",
                            "ADQUIERE", "COMPRA DE", "VENTA DE"]),
    ("modificación",       ["MODIFICA", "ACTUALIZA", "REFORMA", "RECTIFICA",
                            "CAMBIO DE RAZÓN SOCIAL", "CAMBIO DE NOMBRE"]),
    ("sanción",            ["MULTA", "SANCIÓN", "AMONESTA", "REPRENDE",
                            "INFRACCIÓN", "INCUMPLIMIENTO"]),
    ("suspensión",         ["SUSPENDE", "PRORROGA SUSPENSIÓN", "SUSPENSIÓN DE"]),
]


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


# Limite de palabra (\b) al inicio para evitar "FUSION" matchee "DIFUSION".
_REGLAS_NORM: list[tuple[str, list[re.Pattern[str]]]] = [
    (categoria, [re.compile(r"\b" + re.escape(_sin_tildes(kw.upper())))
                 for kw in keywords])
    for categoria, keywords in REGLAS
]


def clasificar(texto: str) -> str:
    t = _sin_tildes(texto.upper())
    for categoria, patrones in _REGLAS_NORM:
        for patron in patrones:
            if patron.search(t):
                return categoria
    return "otro"


def run(fecha: str | None = None) -> dict[str, int]:
    # 'fecha' se mantiene en la firma por compatibilidad con el orquestador,
    # pero la clasificacion es global: re-clasifica todas las resoluciones de
    # la DB (es barato y mantiene la idempotencia del pipeline).
    del fecha
    fecha_log = datetime.today().strftime("%Y-%m-%d")

    cats: Counter = Counter()
    with db.conectar() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT fecha, numero, resolucion FROM resoluciones")
            filas = cur.fetchall()
            updates = []
            for f, n, resolucion in filas:
                cat = clasificar(resolucion or "")
                cats[cat] += 1
                updates.append((cat, f, n))
            if updates:
                cur.executemany(
                    "UPDATE resoluciones SET categoria = %s, updated_at = now() "
                    "WHERE fecha = %s AND numero = %s "
                    "  AND categoria IS DISTINCT FROM %s",
                    [(cat, f, n, cat) for cat, f, n in updates],
                )

    print(f"Clasificacion {fecha_log} ({sum(cats.values())} resoluciones):")
    for cat, n in cats.most_common():
        label = cat.replace("_", " ").title()
        print(f"  {label:<25} {n}")

    return dict(cats)


if __name__ == "__main__":
    fecha_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(fecha_arg)
