"""
Lee el JSON del día y asigna una categoría a cada resolución
basándose en palabras clave en el texto de la resolución.
Actualiza el mismo archivo JSON con el campo 'categoria'.
"""

import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Orden importa: la primera coincidencia gana.
# Las categorías más específicas deben ir antes que las generales.
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
    """Quita tildes/diacríticos para que el match no dependa de la acentuación."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


# REGLAS compiladas: cada keyword se normaliza (mayúsculas, sin tildes) y se
# convierte en un patrón con LÍMITE DE PALABRA al inicio (\b) para evitar que
# "FUSIÓN" matchee a "DIFUSIÓN", o "MULTA" a "MULTIPLICA". El límite a la
# derecha se omite a propósito: queremos que "DIRECTOR" siga matcheando
# "DIRECTORES" o "DIRECTORA", y "MULTA" a "MULTADO".
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


def clasificar_archivo(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        records: list[dict] = json.load(f)

    for r in records:
        r["categoria"] = clasificar(r.get("resolucion", ""))

    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return records


def run(fecha: str | None = None) -> list[dict]:
    if fecha is None:
        fecha = datetime.today().strftime("%Y-%m-%d")

    path = os.path.join(DATA_DIR, f"{fecha}.json")
    if not os.path.exists(path):
        print(f"No existe {path}. Ejecuta scraper.py primero.")
        sys.exit(1)

    records = clasificar_archivo(path)

    cats = Counter(r["categoria"] for r in records)
    print(f"Clasificación {fecha} ({len(records)} resoluciones):")
    for cat, n in cats.most_common():
        label = cat.replace("_", " ").title()
        print(f"  {label:<25} {n}")

    return records


if __name__ == "__main__":
    fecha_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(fecha_arg)
