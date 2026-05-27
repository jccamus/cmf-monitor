"""
Healthcheck del contenedor 'app'.

Exit 0 (sano) si:
  - meta.ultima_corrida no existe aun (primer arranque, todavia no corre el cron)
  - la ultima corrida fue hoy o ayer (delta <= 1 dia)

Exit 1 (no sano) si:
  - la ultima corrida fue hace mas de 1 dia (cron no esta despachando)
  - la DB no es accesible

Usado por docker-compose como:
  healthcheck:
    test: ["CMD", "python", "/app/healthcheck.py"]
"""
import sys
from datetime import date, datetime

import db


def main() -> int:
    try:
        with db.conectar() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT valor FROM meta WHERE clave = 'ultima_corrida'")
                row = cur.fetchone()
    except Exception as exc:
        print(f"healthcheck: DB inaccesible: {exc}", file=sys.stderr)
        return 1

    if not row:
        # Primer arranque del contenedor; aun no ha corrido el pipeline.
        # Consideramos sano (start_period del compose absorbe esto).
        return 0

    try:
        ultima = datetime.strptime(row[0], "%Y-%m-%d").date()
    except (ValueError, TypeError) as exc:
        print(f"healthcheck: meta.ultima_corrida invalida ({row[0]!r}): {exc}",
              file=sys.stderr)
        return 1

    delta = (date.today() - ultima).days
    if delta <= 1:
        return 0
    print(f"healthcheck: ultima corrida fue hace {delta} dias ({ultima}).",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
