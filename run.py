"""
Punto de entrada unico.
Uso:
  python run.py              -> procesa la fecha de hoy
  python run.py 2026-05-03   -> procesa una fecha especifica
"""

import sys
import scraper
import classifier
import enricher
import tareas
import mailer
import dashboard


def main():
    fecha = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 50)
    print("PASO 1 - Scraper CMF (ultimos 90 dias)")
    print("=" * 50)
    scraper.run(fecha)

    print()
    print("=" * 50)
    print("PASO 1.5 - Reparacion de entidades historicas")
    print("=" * 50)
    scraper.repair_entidades()

    print()
    print("=" * 50)
    print("PASO 2 - Clasificador")
    print("=" * 50)
    classifier.run(fecha)

    print()
    print("=" * 50)
    print("PASO 3 - Enriquecimiento (RUT, Tipo, Vigencia)")
    print("=" * 50)
    enricher.run(fecha)

    print()
    print("=" * 50)
    print("PASO 4 - Tareas (transiciones de codigo de institucion)")
    print("=" * 50)
    novedades = tareas.run(fecha)

    print()
    print("=" * 50)
    print("PASO 5 - Notificaciones por correo")
    print("=" * 50)
    mailer.notificar(novedades)

    print()
    print("=" * 50)
    print("PASO 6 - Dashboard")
    print("=" * 50)
    path = dashboard.run()

    print()
    print("Listo. Abre el dashboard en tu navegador:")
    if path:
        print(f"  {path}")


if __name__ == "__main__":
    main()
