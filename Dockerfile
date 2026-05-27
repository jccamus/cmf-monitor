FROM python:3.11-slim

# Zona horaria: el cron interno usa la hora del contenedor, asi que
# necesitamos que sea America/Santiago para que "05:00" signifique 05:00 CL.
# (Puede sobrescribirse desde docker-compose si se despliega en otra TZ.)
ENV TZ=America/Santiago

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        cron \
        tini \
        tzdata \
        ca-certificates \
 && ln -sf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

# Usuario no privilegiado para correr la app. El daemon de cron sigue
# siendo root (es lo estandar y es lo que necesita para leer /etc/cron.d),
# pero los procesos de Python que disparan los cron jobs corren como 'cmf'.
# El entrypoint tambien usa 'runuser -u cmf' para la migracion y la
# primera corrida.
RUN groupadd --system --gid 1000 cmf \
 && useradd  --system --uid 1000 --gid cmf \
             --home-dir /app --shell /bin/bash cmf

WORKDIR /app

# Dependencias primero para aprovechar la cache de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codigo
COPY . .

# Crontab: corre todos los dias a las 05:00 hora local (TZ=America/Santiago).
# El segundo campo (despues del horario) es el USUARIO con que cron ejecuta
# el comando: aqui usamos 'cmf' (no root). El daemon cron sigue corriendo
# como root pero el python se ejecuta sin privilegios.
RUN printf '%s\n' \
    '0 5 * * * cmf /usr/local/bin/run-cron.sh >> /var/log/cmf-monitor.log 2>&1' \
    '' \
    > /etc/cron.d/cmf-monitor \
 && chmod 0644 /etc/cron.d/cmf-monitor \
 && touch /var/log/cmf-monitor.log \
 && chown cmf:cmf /var/log/cmf-monitor.log /app -R

COPY run-cron.sh        /usr/local/bin/run-cron.sh
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/run-cron.sh \
             /usr/local/bin/docker-entrypoint.sh

# NOTA: el entrypoint arranca como root (lo necesita para escribir
# /etc/cmf-monitor.env y para hacer 'exec cron -f'). El propio script
# luego usa 'runuser -u cmf' para la migracion y la primera corrida del
# pipeline, asi solo el demonio cron sigue como root.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
