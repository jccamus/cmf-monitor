#!/usr/bin/env bash
set -euo pipefail

# Este script arranca como root (lo necesita para preparar /etc/cmf-monitor.env
# y para que mas abajo cron pueda binderse a su socket). Pero los procesos de
# Python se invocan via 'runuser -u cmf' para que no corran con privilegios.

run_as_cmf() {
    runuser -u cmf -- "$@"
}

# Espera a que la DB acepte conexiones (max ~60s).
echo "[entrypoint] Esperando a Postgres en ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
for _ in $(seq 1 60); do
    if run_as_cmf python - <<'PY' >/dev/null 2>&1
import os, psycopg
host = os.environ.get('POSTGRES_HOST', 'db')
port = os.environ.get('POSTGRES_PORT', '5432')
db   = os.environ.get('POSTGRES_DB',   'cmf')
user = os.environ.get('POSTGRES_USER', 'cmf')
pwd  = os.environ.get('POSTGRES_PASSWORD', 'cmf')
psycopg.connect(f"host={host} port={port} dbname={db} user={user} password={pwd}", connect_timeout=2).close()
PY
    then
        echo "[entrypoint] Postgres listo."
        break
    fi
    sleep 1
done

# Pasa el entorno al cron escribiendolo a /etc/cmf-monitor.env con quoting
# seguro (los passwords pueden traer caracteres especiales).
# El archivo queda owned por cmf y modo 600: solo el usuario 'cmf' lo puede
# leer, ni siquiera otros procesos no privilegiados del contenedor.
python - <<'PY' > /etc/cmf-monitor.env
import os, shlex
prefijos = ("DATABASE_URL", "POSTGRES_", "CMF_", "TZ")
for k, v in sorted(os.environ.items()):
    if k.startswith(prefijos):
        print(f"{k}={shlex.quote(v)}")
PY
chown cmf:cmf /etc/cmf-monitor.env
chmod 600     /etc/cmf-monitor.env

# Migracion inicial (idempotente: solo carga si las tablas estan vacias)
echo "[entrypoint] Ejecutando migracion inicial (si aplica)..."
run_as_cmf python /app/migrate.py || true

# Primera corrida inmediata (para tener dashboard sin esperar al cron de las 05:00).
echo "[entrypoint] Primera corrida del pipeline..."
run_as_cmf python /app/run.py >> /var/log/cmf-monitor.log 2>&1 || true

# Arranca cron en foreground; tini se encarga de senales.
# El daemon cron sigue como root (es lo que requiere para leer /etc/cron.d),
# pero el job del crontab esta configurado para correrse como 'cmf'.
echo "[entrypoint] Iniciando cron (proxima ejecucion automatica: 05:00 ${TZ:-UTC})."
exec cron -f
