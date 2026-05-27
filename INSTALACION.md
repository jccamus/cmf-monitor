# Instalacion - Monitoreo CMF (Docker + Postgres)

Esta es la guia de despliegue para la rama **`postgres-docker`**, que empaqueta
todo el sistema (aplicacion, base de datos y dashboard web) en contenedores
Docker. Una vez instalado, todo se administra con `docker compose`.

Otras variantes disponibles en este repositorio:

| Rama              | Almacenamiento  | Scheduler        | Notificaciones |
|-------------------|-----------------|------------------|----------------|
| `main`            | JSON en repo    | GitHub Actions   | (sin correo)   |
| `server`          | JSON en disco   | cron del sistema | SMTP propio    |
| `postgres-docker` | **Postgres**    | cron interno     | SMTP propio    |

---

## 1. Requisitos del servidor

- Sistema operativo Linux (probado en Debian/Ubuntu) o Windows con WSL2.
- **Docker Engine 24+** y **Docker Compose v2** (`docker compose ...`,
  no `docker-compose`).
  - Instalacion oficial: https://docs.docker.com/engine/install/
- Acceso saliente HTTPS a `www.cmfchile.cl` (puerto 443).
- Si vas a enviar correos: acceso saliente al servidor SMTP corporativo
  (tipicamente 587/TLS o 465/SSL).
- 1 GB RAM y 2 GB de disco libres son suficientes con holgura.

No se requiere instalar Python ni Postgres en el host: Docker provee ambos.

---

## 2. Que se sube al servidor

Solo necesitas el contenido de esta rama clonado en el servidor. Los
archivos relevantes son:

| Archivo / carpeta        | Para que sirve                                                | Subir? |
|--------------------------|---------------------------------------------------------------|--------|
| `Dockerfile`             | Construye la imagen de la app                                 | Si     |
| `docker-compose.yml`     | Define los 3 servicios (db, app, web)                         | Si     |
| `docker-entrypoint.sh`   | Espera la DB, migra JSONs, lanza cron                         | Si     |
| `run-cron.sh`            | Wrapper que el cron interno invoca a diario                   | Si     |
| `nginx.conf`             | Sirve `dashboard.html` en el puerto del host                  | Si     |
| `requirements.txt`       | Dependencias Python                                           | Si     |
| `schema.sql`             | DDL de las tablas (se aplica solo si no existen)              | Si     |
| `*.py`                   | Codigo del pipeline (incluye `healthcheck.py` para Docker)    | Si     |
| `templates/*.html` y `.txt` | Cuerpo de los correos                                      | Si     |
| `data/*.json`            | Historico para la migracion inicial                           | Si (1) |
| `.env.example`           | Plantilla del archivo `.env`                                  | Si     |
| `.env`                   | Credenciales reales                                           | **NO** (2) |
| `.git/`                  | Historia del repo (no influye en runtime)                     | Opcional |
| `INSTALACION.md`, `CLAUDE.md`, `Propuesta.txt` | Documentacion                           | Opcional |

(1) `data/*.json` queda en el repo para que `migrate.py` los cargue en la
DB la primera vez. Despues de la primera corrida exitosa puedes borrarlos
del repo si quieres (la fuente de verdad pasa a ser Postgres).

(2) `.env` contiene credenciales SMTP y la contrasena de la DB; debe
generarse manualmente en el servidor y nunca commitearse.

La forma recomendada de "subir" todo es clonar la rama directamente:

```bash
sudo mkdir -p /opt/cmf-monitor
sudo chown $USER:$USER /opt/cmf-monitor
git clone -b postgres-docker https://<tu-host>/<tu-org>/cmf-monitor.git /opt/cmf-monitor
cd /opt/cmf-monitor
```

---

## 3. Configurar el entorno

Crea el archivo `.env` a partir del ejemplo y completa los valores:

```bash
cp .env.example .env
nano .env       # o el editor que prefieras
```

Variables importantes:

| Variable                    | Para que sirve                                       |
|-----------------------------|------------------------------------------------------|
| `POSTGRES_PASSWORD`         | Contrasena de la DB local (cambia el default!)       |
| `WEB_PORT`                  | Puerto del host donde se publica el dashboard (8080) |
| `CMF_DASHBOARD_URL`         | URL publica del dashboard (va al final del correo)   |
| `CMF_SMTP_HOST`             | Servidor SMTP corporativo                            |
| `CMF_SMTP_USER` / `_PASS`   | Credenciales SMTP                                    |
| `CMF_MAIL_FROM`             | Remitente de los correos                             |
| `CMF_MAIL_TO_NUEVAS`        | Destinatario(s) del correo "nuevas sin codigo"       |
| `CMF_MAIL_TO_ASIGNADOS`     | Destinatario(s) del correo "codigos asignados"       |

Si `CMF_SMTP_HOST` o `CMF_MAIL_FROM` quedan vacios, el pipeline omite el
envio de correos silenciosamente (util para probar sin SMTP real).

---

## 4. Levantar el sistema

> ### ⚠ Antes de exponer el dashboard
>
> El servicio `web` (nginx) **no tiene autenticacion**: cualquiera con acceso
> al puerto `WEB_PORT` puede ver el dashboard, incluidos RUTs, emails y
> codigos de institucion. Esto es seguro mientras `WEB_PORT` solo este
> abierto en la red interna del servidor (loopback o LAN corporativa).
>
> **NO publiques el puerto hacia internet directamente.** Si necesitas acceso
> remoto, pon delante un reverse proxy (Caddy, nginx del host o Traefik) con
> **TLS y autenticacion basica/SSO**. Postgres tampoco se expone al host por
> defecto y debe seguir asi.

```bash
docker compose up -d --build
```

Esto:

1. Descarga `postgres:16-alpine` y `nginx:alpine`.
2. Construye la imagen de la app (Python 3.11 + cron + tini).
3. Arranca los 3 servicios:
   - `db`     - Postgres en un volumen persistente (`db_data`).
   - `app`    - en su primer arranque corre `migrate.py` para cargar los
                JSON historicos en la DB, hace una corrida inmediata del
                pipeline y luego inicia el cron interno (proxima ejecucion:
                **05:00 hora de Santiago**, todos los dias).
   - `web`    - nginx sirviendo `reports/dashboard.html` en
                `http://<servidor>:${WEB_PORT}/`.

Verificar que todo arranco bien:

```bash
docker compose ps         # los 3 servicios deben aparecer "running"/"healthy"
docker compose logs -f app
```

En los logs de `app` deberias ver:

```
[entrypoint] Esperando a Postgres en db:5432...
[entrypoint] Postgres listo.
[entrypoint] Ejecutando migracion inicial (si aplica)...
Migracion inicial de JSON -> Postgres
  Tabla resoluciones...
  NNN fila(s) cargadas/actualizadas.
  Tabla estado_codigos...
  N fila(s) cargadas/actualizadas.
Listo.
[entrypoint] Primera corrida del pipeline...
==================================================
PASO 1 - Scraper CMF (ultimos 90 dias)
...
```

Despues abrir el dashboard en el navegador: `http://<servidor>:8080/`

---

## 5. Operacion diaria

| Tarea                                      | Comando                                          |
|--------------------------------------------|--------------------------------------------------|
| Ver el estado de los servicios             | `docker compose ps`                              |
| Seguir los logs del pipeline               | `docker compose logs -f app`                     |
| Ver el log del cron interno                | `docker compose exec app tail -f /var/log/cmf-monitor.log` |
| Lanzar una corrida manual                  | `docker compose exec app python run.py`          |
| Lanzar una corrida para una fecha vieja    | `docker compose exec app python run.py 2026-05-15` |
| Forzar re-migracion de JSONs               | `docker compose exec app python migrate.py --force` |
| Abrir psql contra la DB                    | `docker compose exec db psql -U cmf -d cmf`      |
| Reiniciar solo la app                      | `docker compose restart app`                     |
| Detener todo                               | `docker compose down`                            |
| Detener todo Y borrar la DB                | `docker compose down -v` (CUIDADO: borra el volumen) |

---

## 6. Respaldos

El estado relevante vive en el volumen `db_data`. Para respaldarlo:

```bash
# Dump SQL (recomendado)
docker compose exec -T db pg_dump -U cmf -d cmf > backup_$(date +%F).sql

# Restaurar
cat backup_2026-05-27.sql | docker compose exec -T db psql -U cmf -d cmf
```

El dashboard (`reports/`) y los JSONs originales (`data/`) son
re-generables: el primero desde la DB, los segundos historicos.

---

## 7. Actualizaciones de codigo

```bash
cd /opt/cmf-monitor
git pull
docker compose build app
docker compose up -d
```

El esquema de la DB (`schema.sql`) usa `CREATE TABLE IF NOT EXISTS`, asi
que reconstruir la imagen no afecta los datos existentes. Si en un futuro
introduces cambios incompatibles, agrega un script de migracion incremental.

---

## 8. Troubleshooting

**El servicio `app` arranca pero el cron no dispara nada.**
Verifica la TZ del contenedor:
```bash
docker compose exec app date
```
Debe mostrar la hora local de Chile.

**El primer arranque dice "ya hay filas, omitiendo migracion".**
Es normal si la DB ya tiene datos (por ej. reinstalaste sin borrar el
volumen). Si quieres recargar todo desde los JSON, usa
`docker compose exec app python migrate.py --force`.

**No me llega correo aunque la corrida fue exitosa.**
1. Confirma que `CMF_SMTP_HOST` y `CMF_MAIL_FROM` esten en `.env`.
2. Mira el log: `docker compose logs app | grep -i smtp`. Si dice
   "SMTP no configurado", `.env` no se cargo (revisa que este en la raiz
   del proyecto, junto al `docker-compose.yml`).
3. Si dice "ERROR enviando correo: <X>", el SMTP rechazo la conexion.
   Prueba con `swaks` o `python -m smtplib` desde el contenedor para
   diagnosticar.
4. Si no hubo "novedades" (entidades nuevas sin codigo o recien
   asignadas), tampoco se envia correo.

**Quiero ver que entidades estan pendientes ahora.**
```bash
docker compose exec db psql -U cmf -d cmf -c \
   "SELECT entidad, rut, primera_deteccion FROM estado_codigos ORDER BY primera_deteccion;"
```

**El scraper fallo con error de red.**
CMF rechazo la conexion o cambio su HTML. El raw queda en
`/app/data/debug.html` dentro del contenedor:
```bash
docker compose exec app head -100 /app/data/debug.html
```

---

## 9. Puertos y red

| Puerto | Proceso       | Direccion | Quien lo necesita                          |
|--------|---------------|-----------|--------------------------------------------|
| 5432   | Postgres      | Interno   | solo `app` (no se expone al host por default) |
| 80     | nginx         | Interno   | mapeado a `${WEB_PORT}` (8080) del host    |
| 443    | (cmfchile.cl) | Saliente  | `app` necesita salir para scrapear         |
| 587    | (SMTP)        | Saliente  | `app` necesita salir para enviar correos   |

Si quieres exponer el dashboard hacia internet, lo recomendable es poner
un reverse proxy (Caddy / nginx del host / Traefik) delante con TLS y
autenticacion basica. No expongas Postgres al exterior.
