#!/usr/bin/env bash
# Wrapper que ejecuta el pipeline desde cron.
# El entrypoint escribe el entorno actual a /etc/cmf-monitor.env como pares
# KEY='valor', con las comillas escapadas. Aqui lo cargamos antes de python.
set -e

if [ -f /etc/cmf-monitor.env ]; then
    set -a
    # shellcheck disable=SC1091
    . /etc/cmf-monitor.env
    set +a
fi

cd /app
echo "----- $(date '+%F %T %Z') | corrida cron -----"
exec /usr/local/bin/python run.py
