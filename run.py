"""
Punto de entrada unico.
Uso:
  python run.py              -> procesa la fecha de hoy
  python run.py 2026-05-03   -> procesa una fecha especifica
"""

import sys
from datetime import datetime

import db
import issues
import scraper
import classifier
import enricher
import tareas
import mailer
import dashboard


def _detectar_entidades_no_extraidas() -> None:
    """Despues del repair, las filas con autoriza_prestacion=true que sigan
    con entidad='' son casos que el regex no pudo manejar. Las registramos
    como incidencia para que el equipo extienda _TIPOS_SERVICIO o corrija
    el dato a mano."""
    with db.conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fecha, numero, resolucion FROM resoluciones "
                "WHERE autoriza_prestacion = TRUE AND entidad = '' "
                "ORDER BY fecha DESC, numero DESC"
            )
            filas = cur.fetchall()

    for fecha, numero, resolucion in filas:
        issues.registrar(
            "entidad_no_extraida", "error",
            f"No se pudo extraer entidad de la resolucion {numero} "
            f"({fecha.isoformat() if hasattr(fecha, 'isoformat') else fecha}).",
            {
                "fecha":      fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha),
                "numero":     numero,
                "resolucion": (resolucion or "")[:300],
            },
        )

    if filas:
        print(f"  {len(filas)} resolucion(es) sin entidad extraida — registradas como incidencia.")


def main():
    fecha = sys.argv[1] if len(sys.argv) > 1 else datetime.today().strftime("%Y-%m-%d")
    print(f"Fecha de la corrida: {fecha}")

    # Limpiar incidencias de hoy: cada corrida empieza con la pizarra limpia
    # y vuelve a registrar lo que detecte. El historico de dias anteriores
    # se preserva para el log semanal.
    issues.limpiar_hoy()

    print("=" * 50)
    print("PASO 1 - Scraper CMF (ultimos 90 dias)")
    print("=" * 50)
    scraper_ok = True
    try:
        scraper.run(fecha)
    except Exception as exc:
        # El scraper ya registro una incidencia. Seguimos con el resto del
        # pipeline contra los datos previos en la DB: el dashboard se regenera
        # mostrando la alerta, y tareas/mailer evaluan transiciones reales
        # (puede que aun haya algo que notificar de corridas anteriores).
        scraper_ok = False
        print(f"PASO 1 fallo: {exc}")
        print("Continuando con los datos previos en la base de datos.")

    print()
    print("=" * 50)
    print("PASO 1.5 - Reparacion de entidades historicas")
    print("=" * 50)
    if scraper_ok:
        scraper.repair_entidades()
        _detectar_entidades_no_extraidas()
    else:
        print("Omitido porque PASO 1 fallo.")

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
