# Monitoreo CMF — Documentación Técnica de Instalación

**Sistema:** Monitoreo CMF - Resoluciones de Autorización de Entidades  
**Propósito:** Descarga diaria de resoluciones de la Comisión para el Mercado Financiero, clasificación automática por categoría, enriquecimiento con datos del registro oficial y generación de un panel de control HTML con información de nuevas entidades autorizadas.  
**Audiencia:** Equipo de Tecnologías de la Información  
**Última actualización:** Mayo 2026

---

## 1. Qué hace este sistema

Cada día, el sistema ejecuta los siguientes pasos en secuencia:

| Paso | Script | Qué hace | Tiempo aprox. |
|------|--------|----------|---------------|
| 1 | `scraper.py` | Descarga las resoluciones CMF de los últimos 90 días y extrae entidad y tipo de servicio | 15–30 seg |
| 1.5 | `scraper.py` | Repara entidades que quedaron vacías en archivos históricos (idempotente, no re-procesa si ya está correcto) | < 5 seg |
| 2 | `classifier.py` | Clasifica cada resolución por categoría | < 5 seg |
| 3 | `enricher.py` | Consulta el registro CMF por cada entidad nueva: obtiene RUT, código de institución, domicilio, contacto, etc. | 3–8 min (*) |
| 4 | `tareas.py` | Detecta transiciones de código (entidades que entran o salen de la lista "sin código") y escribe `reports/tareas_*.json` | < 1 seg |
| 5 | `mailer.py` | Envía dos correos vía SMTP: uno con las nuevas entidades sin código, otro con los códigos recién asignados. Solo envía si hay novedades. Ver §14 | 2–10 seg |
| 6 | `dashboard.py` | Genera `reports/dashboard.html` con panel de control interactivo | < 5 seg |

(*) El enriquecimiento respeta pausas de 2 segundos entre solicitudes para no sobrecargar el servidor CMF. Solo procesa entidades nuevas (no re-procesa las ya registradas).

**Salidas del sistema:**
- `data/YYYY-MM-DD.json` — datos del día en formato JSON
- `reports/dashboard.html` — panel de control autocontenido (no requiere servidor web para visualizarse)

---

## 2. Qué muestra el dashboard

El archivo `reports/dashboard.html` es un panel de control interactivo con las siguientes secciones:

### Tarjetas de resumen (parte superior)
| Tarjeta | Descripción |
|---------|-------------|
| Resoluciones en los últimos 90 días (desde DD/MM/AAAA) | Total de resoluciones CMF emitidas en los 90 días anteriores a la fecha de generación |
| Entidades autorizadas en los últimos 90 días (desde DD/MM/AAAA) | Total de resoluciones "AUTORIZA LA PRESTACIÓN" vigentes en los últimos 90 días |
| Sin código de institución en los últimos 90 días (desde DD/MM/AAAA) | Entidades autorizadas en los últimos 90 días que aún no tienen código de institución CMF asignado |

La fecha entre paréntesis se calcula automáticamente en cada generación del dashboard.

### Gráfico de barras
Muestra cuántas entidades se han autorizado en los **últimos 90 días** según el **Tipo de Servicio** (Asesoría de Inversión, Gestión de Carteras, Corredor de Valores, etc.), ordenadas de mayor a menor. El título indica la fecha de inicio del período entre paréntesis.

### Tabla: Nuevas Entidades Autorizadas
Lista todas las entidades con resolución "AUTORIZA LA PRESTACIÓN" vigentes desde enero 2024, agrupadas por mes. Incluye:
- Fecha de la resolución (formato DD/MM/AAAA)
- Nombre de la entidad
- RUT y código de institución CMF
- Tipo de servicio autorizado
- Tipo de registro CMF
- Estado de vigencia
- Botón "Ver" que abre una ventana emergente con la ficha completa de la entidad (17 campos del registro oficial)

**Búsqueda:** campo de texto con dos botones:
- **Buscar** — filtra la tabla por entidad, RUT o tipo de servicio (también se activa pulsando Enter). Las cabeceras de mes sin resultados se ocultan automáticamente.
- **Limpiar** — borra el texto ingresado y restaura la lista completa con todos los registros disponibles.

No se muestran entidades con estado "No Vigente".

### Resumen por categoría y tipo de empresa
Dos tablas de resumen que totalizan las entidades autorizadas en los **últimos 90 días** por categoría de resolución y por tipo de empresa. El título indica la fecha de inicio del período entre paréntesis.

---

## 3. Requisitos del servidor

### 3.1 Hardware mínimo

| Recurso | Mínimo | Recomendado |
|---------|--------|-------------|
| CPU | 1 núcleo | 2 núcleos |
| RAM | 512 MB | 1 GB |
| Disco | 2 GB libres | 10 GB (para datos históricos) |
| Red | Acceso HTTPS saliente a `www.cmfchile.cl` | — |

El sistema **no requiere** base de datos, servidor web ni puertos entrantes abiertos.

### 3.2 Software

| Componente | Versión mínima | Notas |
|------------|---------------|-------|
| Python | **3.10** | El código usa sintaxis de tipos `str \| None` disponible desde 3.10 |
| pip | Incluido con Python | Para instalar dependencias |
| Sistema Operativo | Windows Server 2016+ / Ubuntu 20.04+ / RHEL 8+ | Cualquier SO con Python 3.10+ |

### 3.3 Acceso de red requerido

El servidor debe poder hacer las siguientes conexiones **salientes** (no se requieren puertos entrantes ni VPN especial):

| Destino | Puerto | Propósito |
|---------|--------|-----------|
| `www.cmfchile.cl` (HTTPS) | 443 | Scraping de resoluciones y registro CMF |
| Servidor SMTP de la organización | 587 (STARTTLS) o 465 (SSL) o 25 | Envío de notificaciones por correo (ver §14) |

Si el dashboard se va a servir desde el mismo equipo, también hay que abrir el puerto **entrante** que se use para HTTP (típicamente 8080) hacia la red interna.

---

## 4. Instalación paso a paso

### 4.0 Qué archivos van al servidor

La forma recomendada es **clonar la rama `server` del repositorio**, que trae exactamente lo necesario. Si copias archivos a mano, esta es la lista:

| Archivo / carpeta | ¿Subir al servidor? | Por qué |
|-------------------|---------------------|---------|
| `run.py`, `scraper.py`, `classifier.py`, `enricher.py`, `tareas.py`, `mailer.py`, `config.py`, `dashboard.py` | **Sí** | Son el código del pipeline. |
| `templates/` (4 archivos: `mail_nuevas.html`, `mail_nuevas.txt`, `mail_asignados.html`, `mail_asignados.txt`) | **Sí** | Contienen el cuerpo editable de los dos correos. |
| `requirements.txt` | **Sí** | Lista de dependencias Python. |
| `INSTALACION.md`, `CLAUDE.md` | Opcional | Documentación. Útil de referencia, no obligatoria para que funcione. |
| `data/_estado_codigos.json` | **Sí, si quieres arrancar sin un correo gigante** | Es la memoria entre corridas. Sin este archivo, el primer cron mandará un correo con todas las entidades pendientes como "nuevas". Subiendo el del repo, arrancas con las pendientes ya conocidas. |
| `data/YYYY-MM-DD.json` (varios) | Recomendable | Histórico de scraping. Sirve para que el dashboard arranque con datos desde el día 1 y para que la persistencia incremental del scraper aproveche el enriquecimiento previo. |
| `data/debug*.html` | **No** | Dumps HTML de diagnóstico. Pesados (~5 MB) y se regeneran solos. |
| `reports/*` | **No** | Se regeneran en cada corrida (`dashboard.html`, `tareas_*.json`, `preview_*.html`). |
| `__pycache__/`, `*.pyc` | **No** | Caché de Python. Se regeneran. |
| `.github/`, `.git/`, `.claude/`, `.gitignore` | **No subir manualmente** | Metadata del repo y del workflow de GitHub. No aplica en deploy auto-hospedado. |
| `Propuesta.txt` | **No** | Documento personal del proyecto, no es código. |

**Recomendación rápida**: clona el repo y dejá que git resuelva qué viene y qué no.

---

### 4.1 En Windows Server

**a) Verificar Python 3.10+:**
```powershell
python --version
# Debe mostrar Python 3.10.x o superior
```

Si no está instalado, descargarlo desde https://www.python.org/downloads/  
Marcar "Add Python to PATH" durante la instalación.

**b) Obtener el código (opción recomendada: `git clone`):**
```powershell
# Si Git está instalado:
git clone -b server https://github.com/jccamus/cmf-monitor.git C:\cmf-monitor
```

O alternativamente, descargar el ZIP de la rama `server` desde GitHub y descomprimir en `C:\cmf-monitor\`. La estructura final debe verse como §7.

**c) Instalar dependencias Python:**
```powershell
cd C:\cmf-monitor
python -m pip install -r requirements.txt
```

**d) Configurar las variables de entorno SMTP** (ver §14.3). Sin esto, los correos no se envían — el resto del pipeline sí funciona.

**e) Verificar que funciona:**
```powershell
python run.py
```

La primera ejecución toma entre 5 y 10 minutos. Al finalizar debe existir:
- `C:\cmf-monitor\data\YYYY-MM-DD.json`
- `C:\cmf-monitor\reports\dashboard.html`
- Si hay novedades, se enviaron correos a los destinatarios configurados.

---

### 4.2 En Linux / Ubuntu Server

**a) Verificar Python 3.10+:**
```bash
python3 --version
```

Si no está instalado:
```bash
sudo apt update && sudo apt install python3 python3-pip git -y
```

**b) Crear carpeta del proyecto y obtener el código:**
```bash
sudo mkdir -p /opt/cmf-monitor
sudo chown $USER:$USER /opt/cmf-monitor
git clone -b server https://github.com/jccamus/cmf-monitor.git /opt/cmf-monitor
```

Si no es posible usar git (red restringida), copiar los archivos listados en §4.0 vía SCP/SFTP a `/opt/cmf-monitor/`, manteniendo la subcarpeta `templates/`.

**c) Instalar dependencias:**
```bash
cd /opt/cmf-monitor
pip3 install -r requirements.txt
```

**d) Configurar las variables de entorno SMTP** (ver §14.2). Sin esto, los correos no se envían.

**e) Verificar:**
```bash
python3 run.py
```

---

## 5. Ejecución diaria automática a las 5:00 AM (Santiago de Chile)

### Consideración de zona horaria

Santiago de Chile opera en la zona horaria **America/Santiago**:
- **Horario de invierno (abril–octubre):** UTC−4
- **Horario de verano (octubre–abril):** UTC−3

La forma más robusta es configurar la zona horaria del sistema al valor correcto y programar la tarea en hora local. Así el cambio de horario de verano se maneja automáticamente.

---

### 5.1 Windows Server — Programador de tareas

**Paso 1: Configurar la zona horaria del servidor a Santiago**

En el Panel de Control → Fecha y hora → Zona horaria, seleccionar:
`(UTC-04:00) Santiago`

O desde PowerShell (requiere privilegios de administrador):
```powershell
Set-TimeZone -Id "Pacific SA Standard Time"
```

**Paso 2: Crear la tarea programada**

> **Prerrequisito**: las variables SMTP de §14.3 ya deben estar definidas como **Variables de Sistema** (no de usuario), porque la tarea corre como `SYSTEM`.

Ejecutar en PowerShell con permisos de administrador:

```powershell
schtasks /create `
  /tn "CMF Monitor Diario" `
  /tr "python C:\cmf-monitor\run.py" `
  /sc DAILY `
  /st 05:00 `
  /ru SYSTEM `
  /f
```

Esto programa la ejecución **todos los días a las 05:00** en hora local del servidor (Santiago). `SYSTEM` hereda automáticamente las variables de sistema definidas en §14.3.

**Para verificar que la tarea quedó registrada:**
```powershell
schtasks /query /tn "CMF Monitor Diario"
```

**Para ejecutarla manualmente (prueba):**
```powershell
schtasks /run /tn "CMF Monitor Diario"
```

**Para modificar el horario** (ejemplo: cambiar a 06:00):
```powershell
schtasks /change /tn "CMF Monitor Diario" /st 06:00
```

**Para eliminar la tarea:**
```powershell
schtasks /delete /tn "CMF Monitor Diario" /f
```

**Para ver el log de ejecución** (requiere configurar redirección de salida):

Crear el archivo `C:\cmf-monitor\run_log.bat`:
```bat
@echo off
python C:\cmf-monitor\run.py >> C:\cmf-monitor\logs\cmf-monitor.log 2>&1
```

Crear la carpeta de logs:
```powershell
New-Item -ItemType Directory -Force -Path "C:\cmf-monitor\logs"
```

Luego modificar la tarea para usar el .bat:
```powershell
schtasks /change /tn "CMF Monitor Diario" /tr "C:\cmf-monitor\run_log.bat"
```

---

### 5.2 Linux — Cron con zona horaria de Santiago

**Paso 1: Configurar la zona horaria del servidor**

```bash
sudo timedatectl set-timezone America/Santiago
```

Verificar:
```bash
timedatectl
# Debe mostrar: Time zone: America/Santiago
```

**Paso 2: Crear carpeta de logs**

```bash
sudo mkdir -p /var/log/cmf-monitor
sudo chown $USER:$USER /var/log/cmf-monitor
```

**Paso 3: Crear el wrapper que carga las variables SMTP**

El cron NO hereda las variables del shell del usuario. Para que `mailer.py` vea las credenciales SMTP, el cron debe invocar un script que cargue `/etc/cmf-monitor.env` antes de llamar a Python. Ver §14.2 para crear el archivo de entorno; luego crear el wrapper:

```bash
sudo tee /opt/cmf-monitor/run.sh > /dev/null <<'EOF'
#!/usr/bin/env bash
set -e
set -a
. /etc/cmf-monitor.env
set +a
cd /opt/cmf-monitor
exec /usr/bin/python3 run.py >> /var/log/cmf-monitor/cmf-monitor.log 2>&1
EOF
sudo chmod +x /opt/cmf-monitor/run.sh
```

**Paso 4: Agregar la tarea al crontab**

```bash
crontab -e
```

Agregar la siguiente línea (apunta al wrapper, NO al python directo):

```cron
0 5 * * * /opt/cmf-monitor/run.sh
```

| Campo | Valor | Significado |
|-------|-------|-------------|
| `0 5` | 05:00 | Hora de ejecución en hora local del servidor |
| `* *` | Cualquier mes, cualquier día del mes | — |
| `*` | Todos los días de la semana | Incluye sábados y domingos por si CMF publica resoluciones |

Como el servidor ya tiene la zona horaria configurada en America/Santiago, el cambio de horario de verano se aplica automáticamente: la tarea siempre corre a las 5:00 AM Santiago.

**Para ver el log en tiempo real:**
```bash
tail -f /var/log/cmf-monitor/cmf-monitor.log
```

**Para ver las últimas 100 líneas:**
```bash
tail -100 /var/log/cmf-monitor/cmf-monitor.log
```

**Para probar la ejecución manual** (con las variables de entorno cargadas, igual que como corre el cron):
```bash
/opt/cmf-monitor/run.sh
```

Para probar sin enviar correos (omite envío si las variables SMTP no están seteadas en la sesión):
```bash
cd /opt/cmf-monitor && python3 run.py
```

---

## 6. Publicación del dashboard

El archivo `reports/dashboard.html` es autocontenido: no requiere internet ni servidor web para abrirse localmente. Hay tres opciones de distribución:

### Opción A — Carpeta compartida de red (más simple)

Publicar `reports/dashboard.html` en una carpeta de red compartida (por ejemplo `\\servidor\cmf-monitor\`). Los usuarios abren el archivo directamente con su navegador.

**Ventaja:** Sin configuración de servidor web.  
**Limitación:** El usuario debe estar conectado a la red interna.

### Opción B — Servidor HTTP simple con Python

En el servidor, ejecutar:

```bash
# Linux (en background, permanente)
nohup python3 -m http.server 8080 --directory /opt/cmf-monitor/reports &

# Windows
cd C:\cmf-monitor\reports
python -m http.server 8080
```

Los usuarios acceden a `http://IP-DEL-SERVIDOR:8080/dashboard.html` desde su navegador. Abrir el puerto 8080 en el firewall del servidor.

**Para iniciar automáticamente en Linux** (como servicio systemd):

Crear el archivo `/etc/systemd/system/cmf-dashboard.service`:
```ini
[Unit]
Description=CMF Dashboard HTTP Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 -m http.server 8080 --directory /opt/cmf-monitor/reports
WorkingDirectory=/opt/cmf-monitor/reports
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
```

Activar el servicio:
```bash
sudo systemctl enable cmf-dashboard
sudo systemctl start cmf-dashboard
```

### Opción C — IIS (Windows) o nginx/Apache (Linux)

Configurar el servidor web existente de la organización para servir el directorio `reports/` como sitio estático. El dashboard se actualiza automáticamente cada vez que `run.py` regenera `dashboard.html`.

---

## 7. Estructura de archivos del proyecto

```
cmf-monitor/
│
├── run.py              # Punto de entrada: ejecuta los 6 pasos en secuencia
├── scraper.py          # Descarga y parsea la tabla CMF; extrae entidad y
│                       # tipo de servicio del texto de la resolución;
│                       # incluye repair_entidades() para corregir históricos
├── classifier.py       # Clasifica resoluciones por categoría
├── enricher.py         # Busca cada entidad en CMF y obtiene: RUT completo,
│                       # código de institución, domicilio, contacto, inscripción
├── tareas.py           # Detecta transiciones de código entre corridas
├── mailer.py           # Envía los dos correos vía SMTP (stdlib, sin deps)
├── config.py           # Lee las variables de entorno (SMTP, destinatarios, etc.)
├── dashboard.py        # Genera reports/dashboard.html con panel interactivo
├── requirements.txt    # Dependencias Python
│
├── templates/          # Plantillas editables de los correos (ver §14)
│   ├── mail_nuevas.html
│   ├── mail_nuevas.txt
│   ├── mail_asignados.html
│   └── mail_asignados.txt
│
├── data/
│   ├── 2026-05-04.json       # Datos del día (generado automáticamente)
│   ├── _estado_codigos.json  # Memoria entre corridas (qué entidades estaban
│   │                         # sin código en la corrida anterior). No borrar.
│   └── debug.html            # Última página HTML descargada (diagnóstico)
│
├── reports/
│   ├── dashboard.html              # Panel de control (generado automáticamente)
│   ├── tareas_nuevas_sin_codigo.json   # Solo si hay novedades hoy
│   └── tareas_recien_asignados.json    # Solo si hay novedades hoy
│
└── logs/               # (Solo Windows; en Linux: /var/log/cmf-monitor/)
    └── cmf-monitor.log
```

### Crecimiento esperado del almacenamiento

| Período | Archivos JSON | Tamaño aprox. |
|---------|---------------|---------------|
| 1 semana | 7 archivos | ~5 MB |
| 1 mes | ~30 archivos | ~25 MB |
| 1 año | ~365 archivos | ~300 MB |

---

## 8. Dependencias Python

El archivo `requirements.txt` contiene:

```
requests        # Solicitudes HTTP al sitio CMF
beautifulsoup4  # Parseo de HTML
lxml            # Parser HTML (más robusto que el incluido en Python)
```

Para instalar:
```bash
pip install -r requirements.txt
# o en Linux:
pip3 install -r requirements.txt
```

---

## 9. Variables configurables

Estos parámetros se pueden ajustar editando los archivos Python sin conocimiento avanzado de programación:

| Archivo | Variable | Valor actual | Descripción |
|---------|----------|-------------|-------------|
| `scraper.py` | `DIAS_HISTORICO` | `90` | Días de historia a descargar en cada ejecución |
| `enricher.py` | `DELAY_SEG` | `2.0` | Segundos de pausa entre solicitudes al servidor CMF |
| `enricher.py` | `TIMEOUT` | `25` | Segundos de espera máxima por solicitud HTTP |

---

## 10. Monitoreo y alertas

### Verificar que la ejecución fue exitosa

Después de cada ejecución, revisar que exista el archivo JSON del día:

```powershell
# Windows
Test-Path "C:\cmf-monitor\data\$(Get-Date -Format 'yyyy-MM-dd').json"
```

```bash
# Linux
ls -lh /opt/cmf-monitor/data/$(date +%Y-%m-%d).json
```

### Alerta por correo si la ejecución falla (Linux)

Agregar al crontab una segunda tarea a las 07:00 que revise si el archivo del día existe:

```cron
0 7 * * * test -f /opt/cmf-monitor/data/$(date +%Y-%m-%d).json || echo "CMF Monitor no ejecuto el $(date)" | mail -s "ALERTA CMF Monitor" ti@organizacion.cl
```

### Alerta por correo si la ejecución falla (Windows PowerShell)

Crear `C:\cmf-monitor\check.ps1`:
```powershell
$hoy = Get-Date -Format "yyyy-MM-dd"
$archivo = "C:\cmf-monitor\data\$hoy.json"
if (-not (Test-Path $archivo)) {
    Send-MailMessage `
      -To "ti@organizacion.cl" `
      -From "servidor@organizacion.cl" `
      -Subject "ALERTA: CMF Monitor no ejecuto el $hoy" `
      -SmtpServer "smtp.organizacion.cl"
}
```

Agregar una segunda tarea programada a las 07:00:
```powershell
schtasks /create `
  /tn "CMF Monitor Verificacion" `
  /tr "powershell -File C:\cmf-monitor\check.ps1" `
  /sc DAILY `
  /st 07:00 `
  /ru SYSTEM `
  /f
```

---

## 11. Resolución de problemas comunes

| Síntoma | Causa probable | Solución |
|---------|---------------|----------|
| `ModuleNotFoundError: requests` | Dependencias no instaladas | Ejecutar `pip install -r requirements.txt` |
| `No se encontró ninguna tabla` | CMF cambió el HTML de su página | Revisar `data/debug.html`; ajustar `scraper.py` |
| `ConnectTimeoutError` | CMF no responde o hay rate limiting | El `enricher.py` reintenta automáticamente; si persiste, aumentar `DELAY_SEG` |
| Entidad aparece sin nombre ni RUT | Texto de la resolución no coincide con el patrón esperado | Revisar el campo `resolucion` en el JSON del día; el patrón se puede extender en `scraper.py` |
| JSON del día está vacío o con pocas resoluciones | No hay resoluciones recientes en CMF | Normal en períodos de baja actividad |
| Dashboard desactualizado | La tarea programada no corrió | Verificar el log y ejecutar `python run.py` manualmente |
| Error de codificación en Windows | Terminal Windows no muestra UTF-8 | Normal en la consola; el archivo dashboard.html se genera correctamente en UTF-8 |

---

## 12. Fuente de datos

**Organismo:** Comisión para el Mercado Financiero (CMF Chile)  
**URL principal:** `https://www.cmfchile.cl/institucional/resoluciones/resoluciones_mercados_entidad.php`  
**URL de búsqueda:** `https://www.cmfchile.cl/institucional/mercados/consulta_busqueda.php`  
**URL de detalle:** `https://www.cmfchile.cl/institucional/mercados/entidad.php`  

El sistema consume únicamente páginas HTML públicas del sitio de la CMF. No utiliza APIs privadas, credenciales de acceso ni scraping agresivo. Las pausas incorporadas respetan las buenas prácticas de acceso a sitios gubernamentales.

---

## 13. Resumen para el equipo de TI

Para poner en producción este sistema en un servidor propio, los pasos son:

1. **Instalar Python 3.10+** en el servidor (Windows o Linux).
2. **Obtener el código** vía `git clone -b server https://github.com/jccamus/cmf-monitor.git` (o copiar los archivos listados en §4.0) a la carpeta de destino (`C:\cmf-monitor\` o `/opt/cmf-monitor/`).
3. **Instalar 3 dependencias Python** con `pip install -r requirements.txt` (todas las demás librerías que usa el sistema vienen con la stdlib, incluido el envío SMTP).
4. **Configurar las variables SMTP** (servidor, usuario, password, remitente, destinatarios) — ver §14. En Linux van en `/etc/cmf-monitor.env`; en Windows como Variables de Sistema.
5. **Configurar la zona horaria** del servidor a `America/Santiago` para que el cron corra a las 5:00 AM Santiago todo el año (incluido cambio de horario de verano).
6. **Programar la tarea diaria** a las 05:00 AM (Task Scheduler en Windows; cron + wrapper `run.sh` en Linux — §5).
7. **Publicar el dashboard** vía servidor HTTP simple, carpeta compartida o un servidor web existente — §6.

No se requiere base de datos, Docker, nginx ni librerías SMTP de terceros. Los únicos requisitos de red son **salientes**: HTTPS a `cmfchile.cl` y SMTP a la organización (ver §3.3).

---

## 14. Configuración de notificaciones por correo

El sistema envía **dos correos independientes** cuando hay novedades respecto a la corrida anterior:

| Correo | Cuándo | Destinatario configurable en |
|--------|--------|------------------------------|
| **Nuevas entidades sin código** | Entidad recién detectada como autorizada y aún sin código de institución | `CMF_MAIL_TO_NUEVAS` |
| **Códigos recién asignados** | Entidad que en la corrida anterior estaba pendiente y ahora tiene código asignado | `CMF_MAIL_TO_ASIGNADOS` |

Si en una corrida no hay novedades de un tipo, ese correo simplemente **no se envía** (no es resumen diario; es notificación por evento).

### 14.1 Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `CMF_SMTP_HOST` | Servidor SMTP de la organización | (vacío → no se envía) |
| `CMF_SMTP_PORT` | Puerto SMTP (25, 465 o 587) | `587` |
| `CMF_SMTP_USER` | Usuario para autenticación | (vacío) |
| `CMF_SMTP_PASS` | Contraseña | (vacío) |
| `CMF_SMTP_TLS` | `starttls` / `ssl` / `none` | `starttls` |
| `CMF_MAIL_FROM` | Remitente (puede incluir nombre: `CMF Monitor <cmf@org.cl>`) | (vacío → no se envía) |
| `CMF_MAIL_TO_NUEVAS` | Destinatario(s) del correo 1, separados por coma | (vacío → correo 1 se omite) |
| `CMF_MAIL_TO_ASIGNADOS` | Destinatario(s) del correo 2, separados por coma | (vacío → correo 2 se omite) |
| `CMF_MAIL_SUBJECT_NUEVAS` | Asunto del correo 1 (acepta `$n` y `$fecha`) | Ver `config.py` |
| `CMF_MAIL_SUBJECT_ASIGNADOS` | Asunto del correo 2 (acepta `$n` y `$fecha`) | Ver `config.py` |
| `CMF_DASHBOARD_URL` | URL del dashboard, va al pie del correo | `http://localhost:8080/` |

**Si faltan `CMF_SMTP_HOST` o `CMF_MAIL_FROM`, el sistema no intenta enviar correo y el pipeline sigue corriendo normalmente** (útil para entornos de prueba).

---

### 14.2 Configuración en Linux (archivo de entorno + wrapper)

**Paso 1: Crear el archivo de configuración** `/etc/cmf-monitor.env` (modo 600, dueño root, porque contiene la contraseña):

```bash
sudo tee /etc/cmf-monitor.env > /dev/null <<'EOF'
CMF_SMTP_HOST=smtp.miorganizacion.cl
CMF_SMTP_PORT=587
CMF_SMTP_USER=cmf-monitor@miorganizacion.cl
CMF_SMTP_PASS=cambiar-por-la-real
CMF_SMTP_TLS=starttls
CMF_MAIL_FROM=CMF Monitor <cmf-monitor@miorganizacion.cl>
CMF_MAIL_TO_NUEVAS=registro@miorganizacion.cl
CMF_MAIL_TO_ASIGNADOS=basedatos@miorganizacion.cl
CMF_DASHBOARD_URL=http://servidor.interno:8080/
EOF

sudo chmod 600 /etc/cmf-monitor.env
sudo chown root:root /etc/cmf-monitor.env
```

**Paso 2: Crear el wrapper `/opt/cmf-monitor/run.sh`** que carga las variables antes de ejecutar Python:

```bash
sudo tee /opt/cmf-monitor/run.sh > /dev/null <<'EOF'
#!/usr/bin/env bash
set -e
set -a               # exporta todas las variables que defina el archivo
. /etc/cmf-monitor.env
set +a
cd /opt/cmf-monitor
exec /usr/bin/python3 run.py >> /var/log/cmf-monitor/cmf-monitor.log 2>&1
EOF

sudo chmod +x /opt/cmf-monitor/run.sh
```

**Paso 3: Modificar el crontab** (ver §5.2) para apuntar al wrapper en vez de a Python directo:

```cron
0 5 * * * /opt/cmf-monitor/run.sh
```

Para cambiar contraseñas o destinatarios después: simplemente edita `/etc/cmf-monitor.env` con `sudo nano`. La próxima corrida del cron usa el valor nuevo, sin reiniciar nada.

---

### 14.3 Configuración en Windows Server (variables de sistema)

En Windows, las variables de sistema son heredadas automáticamente por las tareas programadas que corren como `SYSTEM`, así que no hace falta wrapper.

**Vía PowerShell con privilegios de administrador** (una sola vez, durante la instalación):

```powershell
[Environment]::SetEnvironmentVariable("CMF_SMTP_HOST", "smtp.miorganizacion.cl", "Machine")
[Environment]::SetEnvironmentVariable("CMF_SMTP_PORT", "587", "Machine")
[Environment]::SetEnvironmentVariable("CMF_SMTP_USER", "cmf-monitor@miorganizacion.cl", "Machine")
[Environment]::SetEnvironmentVariable("CMF_SMTP_PASS", "cambiar-por-la-real", "Machine")
[Environment]::SetEnvironmentVariable("CMF_SMTP_TLS", "starttls", "Machine")
[Environment]::SetEnvironmentVariable("CMF_MAIL_FROM", "CMF Monitor <cmf-monitor@miorganizacion.cl>", "Machine")
[Environment]::SetEnvironmentVariable("CMF_MAIL_TO_NUEVAS", "registro@miorganizacion.cl", "Machine")
[Environment]::SetEnvironmentVariable("CMF_MAIL_TO_ASIGNADOS", "basedatos@miorganizacion.cl", "Machine")
[Environment]::SetEnvironmentVariable("CMF_DASHBOARD_URL", "http://servidor.interno:8080/", "Machine")
```

Para cambiar un valor después, vuelves a ejecutar `[Environment]::SetEnvironmentVariable` con el valor nuevo, o lo editas desde **Panel de Control → Sistema → Configuración avanzada → Variables de entorno → Variables del sistema**.

**Importante**: si la tarea programada estaba corriendo, no necesita reiniciarse — heredará el valor nuevo en su próxima ejecución. Pero la ventana de PowerShell desde donde ejecutaste estos comandos no verá los cambios hasta que la cierres y abras una nueva.

---

### 14.4 Editar las plantillas de los correos

Las plantillas viven en `templates/`. Cada correo tiene dos archivos:

```
templates/
├── mail_nuevas.html        # Cuerpo HTML del correo 1
├── mail_nuevas.txt         # Cuerpo texto plano (fallback) del correo 1
├── mail_asignados.html     # Cuerpo HTML del correo 2
└── mail_asignados.txt      # Cuerpo texto plano (fallback) del correo 2
```

Las plantillas usan la sintaxis `$variable` (no `{variable}`) para que no entren en conflicto con CSS:

| Placeholder | Lo reemplaza por |
|-------------|------------------|
| `$fecha` | Fecha de la corrida (DD/MM/YYYY) |
| `$n` | Cantidad de entidades en la lista |
| `$tabla` | Tabla con los datos (HTML o ASCII según extensión) |
| `$dashboard_url` | URL del dashboard (de `CMF_DASHBOARD_URL`) |

Cualquier otro texto, formato HTML, logo, instrucciones específicas que pongas en el `.html` se mantienen tal cual. **Editar con cualquier editor y guardar**: la próxima corrida usa el nuevo texto, no requiere reiniciar.

Si la versión `.txt` no existe, se manda solo HTML (funciona, pero algunos filtros antispam castigan correos solo-HTML).

---

### 14.5 Asuntos personalizables

Los asuntos también se controlan por variable de entorno y aceptan `$n` y `$fecha`:

```bash
CMF_MAIL_SUBJECT_NUEVAS=[CMF Monitor] $n nueva(s) entidad(es) sin código — $fecha
CMF_MAIL_SUBJECT_ASIGNADOS=[CMF Monitor] $n código(s) recién asignado(s) — $fecha
```

Si no las defines, se usan los valores por defecto de `config.py` (los mismos que están arriba).

---

### 14.6 Validar el envío manualmente

Antes de dejar el cron corriendo solo, conviene probar:

```bash
# Linux
sudo -u root bash -c 'set -a; . /etc/cmf-monitor.env; set +a; cd /opt/cmf-monitor && python3 run.py'

# Windows (con la sesión que ya ve las env vars)
cd C:\cmf-monitor
python run.py
```

En el output del paso 5 deberías ver una de estas cuatro líneas por correo:

| Línea | Significado |
|-------|-------------|
| `Correo 1 (nuevas sin código): sin novedades, no se envía correo.` | Todo OK; no hubo cambios desde la corrida anterior. |
| `Correo 1 (nuevas sin código): enviando '...' a ...` → `OK` | Enviado correctamente. |
| `Correo 1 (...): hay N novedad(es) pero falta destinatario...` | Falta definir `CMF_MAIL_TO_NUEVAS`. |
| `Correo 1 (...): ERROR enviando correo: ...` | Problema SMTP (ver tabla abajo). |

---

### 14.7 Problemas SMTP frecuentes

| Error | Causa típica | Solución |
|-------|--------------|----------|
| `Connection refused` | Puerto bloqueado por firewall o servidor SMTP no acepta conexiones desde el servidor | Verificar firewall de salida y rangos IP autorizados en el servidor SMTP |
| `Authentication failed` | Usuario o contraseña incorrectos, o el servidor requiere App Password en vez del password normal | Confirmar credenciales; en Gmail/Office365 generar App Password |
| `Sender address not allowed` | El SMTP no permite enviar como esa dirección `From` | Usar como `CMF_MAIL_FROM` la misma dirección que `CMF_SMTP_USER` |
| `STARTTLS extension not supported` | El servidor usa SSL directo (no STARTTLS) | Cambiar `CMF_SMTP_TLS=ssl` y `CMF_SMTP_PORT=465` |
| `SSL: WRONG_VERSION_NUMBER` | Configuración TLS al revés | Probar `CMF_SMTP_TLS=starttls` con puerto 587, o `ssl` con 465 |
| El correo llega a la carpeta de spam | Falta SPF/DKIM o el remitente es genérico | Coordinar con TI para configurar registros DNS del dominio del remitente |

---

*Documento generado en Mayo 2026. Para consultas sobre esta aplicación, contactar al periodista responsable del proyecto.*
