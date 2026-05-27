# Entrega — Monitoreo CMF (postgres-docker)

Este documento es el punto de partida para el equipo de TI que va a
desplegar el sistema. Para detalles completos ver `INSTALACION.md`.

---

## 1. Qué reciben

- **Repo Git** (rama `postgres-docker`): `https://github.com/jccamus/cmf-monitor`
  Si no hay acceso a GitHub, se entrega un `.zip` con el contenido de la rama.
- **Esta guia (`ENTREGA.md`)** — checklist resumido.
- **`INSTALACION.md`** dentro del repo — guia tecnica detallada.

El sistema scrapea diariamente el sitio de la CMF, persiste los resultados
en una base Postgres local, genera un dashboard HTML servido por nginx y
envia dos correos de notificacion via SMTP cuando hay novedades.

---

## 2. Pre-requisitos en el servidor

Antes de empezar, asegurar que el servidor tenga:

- [ ] Linux (Debian/Ubuntu probado) o Windows con WSL2
- [ ] **Docker Engine 24+** y **Docker Compose v2**
  (https://docs.docker.com/engine/install/)
- [ ] **Acceso saliente HTTPS** a `www.cmfchile.cl` (puerto 443)
- [ ] **Acceso saliente SMTP** al servidor de correo corporativo
  (tipicamente puerto 587 con STARTTLS o 465 con SSL)
- [ ] 1 GB RAM y 2 GB de disco libres

Postgres y Python **no** se instalan en el host: Docker provee ambos.

---

## 3. Datos que TI necesita preparar

Antes de la instalacion, conseguir/decidir lo siguiente:

| Dato | Quien lo provee | Para que |
|------|----------------|----------|
| Password de la base Postgres | TI (elige uno fuerte) | `POSTGRES_PASSWORD` |
| Host SMTP corporativo | TI / area de correo | `CMF_SMTP_HOST` |
| Puerto SMTP + modo TLS | TI / area de correo | `CMF_SMTP_PORT`, `CMF_SMTP_TLS` |
| Usuario y password SMTP | TI / area de correo | `CMF_SMTP_USER`, `CMF_SMTP_PASS` |
| Casilla remitente | Negocio | `CMF_MAIL_FROM` (ej. `cmf-monitor@empresa.cl`) |
| Casilla(s) destinatarias del correo "nuevas sin codigo" | Negocio | `CMF_MAIL_TO_NUEVAS` |
| Casilla(s) destinatarias del correo "codigos asignados" | Negocio | `CMF_MAIL_TO_ASIGNADOS` |
| Puerto del host para el dashboard | TI | `WEB_PORT` (default 8080) |
| URL publica del dashboard | TI | `CMF_DASHBOARD_URL` (link incluido en los correos) |

> Multiples destinatarios se separan con coma.
> Si `CMF_SMTP_HOST` o `CMF_MAIL_FROM` se dejan vacios, el sistema corre
> igual pero omite el envio de correos (util para probar primero).

---

## 4. Pasos de instalacion

```bash
# 1. Clonar la rama postgres-docker en el directorio elegido
sudo mkdir -p /opt/cmf-monitor
sudo chown $USER:$USER /opt/cmf-monitor
git clone -b postgres-docker https://github.com/jccamus/cmf-monitor.git /opt/cmf-monitor
cd /opt/cmf-monitor

# 2. Crear el archivo de configuracion a partir de la plantilla
cp .env.example .env
nano .env       # completar con los datos de la seccion 3

# 3. Levantar el stack
docker compose up -d --build

# 4. Ver logs del primer arranque (espera DB, migra datos historicos,
#    corre el pipeline por primera vez y arranca cron)
docker compose logs -f app
```

> ### ⚠ Antes de exponer el dashboard
>
> El servicio web (nginx) **no tiene autenticacion**. Es seguro mientras
> `WEB_PORT` quede en la red interna del servidor. **No publicar el puerto
> directamente a internet**: si se necesita acceso remoto, poner un reverse
> proxy (Caddy, nginx del host o Traefik) con TLS y autenticacion delante.
> Postgres tampoco debe exponerse al host.

---

## 5. Verificacion

Despues del `docker compose up -d --build`, validar:

- [ ] `docker compose ps` muestra los 3 servicios (`db`, `app`, `web`) como
      `running` y eventualmente `healthy` (puede tomar ~10 min en el primer
      arranque por el `start_period`).
- [ ] El log del primer arranque (`docker compose logs app`) muestra
      "Postgres listo", "Ejecutando migracion inicial", "Primera corrida del
      pipeline" y termina con "Iniciando cron".
- [ ] El dashboard responde en `http://<servidor>:${WEB_PORT}/`.
- [ ] Si se configuro SMTP y hay novedades reales: llegan uno o dos correos
      (segun corresponda).
- [ ] El proximo cron diario se gatilla a las **05:00 hora de Santiago**.

---

## 6. Operacion cotidiana

| Tarea | Comando |
|-------|---------|
| Ver estado de los servicios | `docker compose ps` |
| Logs del pipeline | `docker compose logs -f app` |
| Log historico del cron | `docker compose exec app tail -f /var/log/cmf-monitor.log` |
| Corrida manual (re-procesar hoy) | `docker compose exec app python run.py` |
| Corrida manual para una fecha pasada | `docker compose exec app python run.py 2026-05-20` |
| Backup de la DB | `docker compose exec -T db pg_dump -U cmf -d cmf > backup_$(date +%F).sql` |
| Restaurar backup | `cat backup_X.sql \| docker compose exec -T db psql -U cmf -d cmf` |
| Actualizar a nueva version del codigo | `git pull && docker compose up -d --build` |
| Detener todo | `docker compose down` |

---

## 7. Que NO se debe subir al servidor

- `.env` real con credenciales → **se crea manualmente en el servidor**,
  nunca se commitea ni se envia por correo.
- `reports/`, `logs/`, `__pycache__/` → se generan solos.
- `data/debug*.html` → diagnostico, se regenera.
- `Propuesta.txt` → documento personal, no es codigo.

`.env.example` (plantilla sin credenciales reales) si va en el repo.

---

## 8. Soporte y proximos pasos

- Si algo falla en el arranque: ver seccion **8. Troubleshooting** de
  `INSTALACION.md`.
- Si el scraper falla por cambios en el sitio CMF: las incidencias quedan
  registradas en el tab "Errores y temas a revisar" del dashboard.
- Cambios en plantillas de correo: editar `templates/mail_*.html` y
  `templates/mail_*.txt` y reiniciar con `docker compose restart app`
  (no requiere rebuild).
