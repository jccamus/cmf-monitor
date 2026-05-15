"""
Lee todos los archivos JSON en data/ y genera reports/dashboard.html,
un panel de control autocontenido (sin dependencias externas).
"""

import glob
import html as html_lib
import json
import os
from collections import Counter
from datetime import datetime, timedelta

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

COLORES: dict[str, str] = {
    "nueva_actividad":    "#276749",
    "inscripcion":        "#2b6cb0",
    "cancelacion":        "#9b2c2c",
    "cambio_directivo":   "#975a16",
    "fusion_adquisicion": "#553c9a",
    "compraventa":        "#285e61",
    "modificacion":       "#4a5568",
    "sancion":            "#742a2a",
    "suspension":         "#c05621",
    "otro":               "#718096",
}

# Campos que se muestran en la ventana modal, en orden
CAMPOS_MODAL: list[tuple[str, str]] = [
    ("rut_completo",           "RUT"),
    ("codigo_institucion",     "Código de la Institución"),
    ("razon_social",           "Razón Social"),
    ("nombre_fantasia",        "Nombre de Fantasía"),
    ("vigencia_detalle",       "Vigencia"),
    ("num_inscripcion",        "N° de Inscripción"),
    ("fecha_inscripcion",      "Fecha de Inscripción"),
    ("antecedentes_inscripcion","Antecedentes de Inscripción"),
    ("fecha_cancelacion",      "Fecha de Cancelación"),
    ("telefono",               "Teléfono"),
    ("fax",                    "Fax"),
    ("domicilio",              "Domicilio"),
    ("region",                 "Región"),
    ("ciudad",                 "Ciudad"),
    ("comuna",                 "Comuna"),
    ("email",                  "E-mail de contacto"),
    ("sitio_web",              "Sitio web"),
    ("codigo_postal",          "Código Postal"),
]

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


def to_display_date(s: str) -> str:
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return s or "-"


def mes_nombre(ym: str) -> str:
    try:
        y, m = int(ym[:4]), int(ym[5:7])
        return f"{MESES_ES[m]} {y}"
    except (ValueError, IndexError):
        return ym


def json_para_script(obj) -> str:
    """json.dumps seguro para incrustar en un <script>: evita que un '</script>'
    presente en los datos cierre la etiqueta, y escapa los separadores de linea
    U+2028/U+2029 que romperian el literal JavaScript."""
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------

def cargar_datos() -> list[dict]:
    seen: set[tuple] = set()
    records: list[dict] = []
    # De más nuevo a más viejo: para cada (fecha, numero) se conserva la versión
    # del archivo más reciente, que es la que trae los datos enriquecidos al día.
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "????-??-??.json")), reverse=True):
        with open(path, encoding="utf-8") as f:
            for r in json.load(f):
                key = (r.get("fecha", ""), r.get("numero", ""))
                if key not in seen:
                    seen.add(key)
                    records.append(r)
    return sorted(records, key=lambda r: r.get("fecha", ""), reverse=True)


# ---------------------------------------------------------------------------
# Componentes HTML
# ---------------------------------------------------------------------------

def badge(categoria: str) -> str:
    color = COLORES.get(categoria, "#718096")
    label = categoria.replace("_", " ").title()
    return f'<span class="badge" style="background:{color}">{label}</span>'


def vig_html(v: str) -> str:
    if v == "Vigente":
        return '<span class="vig-ok">Vigente</span>'
    return f'<span class="vig-no">{html_lib.escape(v or "-")}</span>' if v else ""


def tabla_resumen(counter: Counter, label_col: str) -> str:
    filas = "\n".join(
        f"<tr><td>{k.replace('_',' ').title()}</td><td class='n'>{v}</td></tr>"
        for k, v in counter.most_common()
    )
    return f"""<table>
      <thead><tr><th>{label_col}</th><th class="n">Total</th></tr></thead>
      <tbody>{filas}</tbody>
    </table>"""


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; background: #edf2f7;
       color: #2d3748; font-size: 14px; }
header { background: #1a365d; color: white; padding: 18px 32px; }
header h1 { font-size: 1.4rem; }
header p  { font-size: 0.8rem; opacity: .75; margin-top: 4px; }
.container { max-width: 1440px; margin: 0 auto; padding: 20px 32px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 20px; }
.card { background: white; border-radius: 8px; padding: 16px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,.1); }
.card .val { font-size: 2rem; font-weight: 700; color: #1a365d; }
.card .lbl { font-size: 0.75rem; color: #718096; margin-top: 4px;
             text-transform: uppercase; letter-spacing: .04em; }
.chart-wrap { padding: 20px 24px 12px; }
.bar-row { display: flex; align-items: center; margin-bottom: 10px; gap: 12px; }
.bar-label { width: 240px; font-size: .8rem; color: #4a5568; text-align: right;
             flex-shrink: 0; line-height: 1.3; }
.bar-track { flex: 1; background: #edf2f7; border-radius: 4px; height: 26px;
             display: flex; align-items: center; overflow: hidden; }
.bar-fill { height: 100%; background: #2b6cb0; border-radius: 4px 0 0 4px;
            min-width: 2px; transition: width .4s ease; }
.bar-count { font-size: .82rem; font-weight: 700; color: #2d3748;
             min-width: 28px; margin-left: 8px; }
.section { background: white; border-radius: 8px; margin-bottom: 20px;
           box-shadow: 0 1px 3px rgba(0,0,0,.1); overflow: hidden; }
.section-title { padding: 11px 20px; background: #edf2f7; font-size: .82rem;
                 font-weight: 700; border-bottom: 1px solid #e2e8f0; color: #2d3748;
                 text-transform: uppercase; letter-spacing: .05em; }
.search-bar { padding: 10px 20px; border-bottom: 1px solid #f0f4f8;
              display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.search-bar input[type=text] { flex: 1; min-width: 200px; padding: 6px 10px;
  border: 1px solid #e2e8f0; border-radius: 4px; font-size: .82rem; }
.search-bar input[type=text]:focus { outline: none; border-color: #2b6cb0; }
.btn-buscar { padding: 6px 18px; background: #1a365d; color: white; border: none;
              border-radius: 4px; cursor: pointer; font-size: .82rem; font-weight: 600; }
.btn-buscar:hover { background: #2b6cb0; }
.btn-limpiar { padding: 6px 14px; background: white; color: #4a5568; border: 1px solid #cbd5e0;
               border-radius: 4px; cursor: pointer; font-size: .82rem; font-weight: 600; }
.btn-limpiar:hover { background: #edf2f7; border-color: #a0aec0; }
#ap-count { font-size: .8rem; color: #718096; }
table { width: 100%; border-collapse: collapse; }
th { background: #f7fafc; padding: 9px 12px; text-align: left;
     border-bottom: 2px solid #e2e8f0; font-size: .75rem; color: #4a5568;
     text-transform: uppercase; letter-spacing: .03em; }
td { padding: 8px 12px; border-bottom: 1px solid #f0f4f8;
     vertical-align: middle; line-height: 1.45; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f7fafc; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; color: white;
         font-size: .7rem; font-weight: 600; white-space: nowrap; }
.n { text-align: right; font-weight: 600; }
.summary-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
.summary-grid > div { padding: 16px 20px; }
.summary-grid > div:first-child { border-right: 1px solid #e2e8f0; }
.hidden { display: none !important; }
.vig-ok  { color: #276749; font-weight: 600; }
.vig-no  { color: #9b2c2c; font-weight: 600; }
.mono    { font-family: monospace; font-size: .8rem; }
.cod-inst { display: inline-block; background: #ebf8ff; color: #2b6cb0;
            border: 1px solid #bee3f8; border-radius: 4px; padding: 1px 6px;
            font-size: .72rem; font-weight: 700; margin-left: 6px; }
.cod-na   { display: inline-block; background: #f7fafc; color: #a0aec0;
            border: 1px solid #e2e8f0; border-radius: 4px; padding: 1px 6px;
            font-size: .72rem; }
.btn-ver  { padding: 3px 10px; background: #1a365d; color: white; border: none;
            border-radius: 4px; cursor: pointer; font-size: .75rem; white-space: nowrap; }
.btn-ver:hover { background: #2b6cb0; }
.mes-header td { background: #edf2f7; font-size: .78rem; font-weight: 700;
                 color: #4a5568; text-transform: uppercase; letter-spacing: .05em;
                 padding: 7px 12px; border-top: 2px solid #e2e8f0; }
.mes-header:hover td { background: #edf2f7; }
/* Modal */
.modal-backdrop { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.45);
                  z-index: 1000; align-items: center; justify-content: center; }
.modal-backdrop.open { display: flex; }
.modal { background: white; border-radius: 10px; padding: 0; width: 620px;
         max-width: 95vw; max-height: 90vh; overflow-y: auto;
         box-shadow: 0 20px 60px rgba(0,0,0,.3); }
.modal-header { padding: 18px 24px; background: #1a365d; color: white;
                border-radius: 10px 10px 0 0; display: flex;
                justify-content: space-between; align-items: flex-start; }
.modal-header h2 { font-size: 1rem; font-weight: 700; }
.modal-header .sub { font-size: .8rem; opacity: .75; margin-top: 3px; }
.modal-close { background: none; border: none; color: white; font-size: 1.4rem;
               cursor: pointer; line-height: 1; padding: 0 4px; opacity: .8; }
.modal-close:hover { opacity: 1; }
.modal-body { padding: 0; }
.modal-row { display: grid; grid-template-columns: 190px 1fr; border-bottom: 1px solid #f0f4f8; }
.modal-row:last-child { border-bottom: none; }
.modal-label { padding: 10px 16px; font-size: .78rem; font-weight: 600; color: #4a5568;
               background: #f7fafc; }
.modal-val   { padding: 10px 16px; font-size: .82rem; color: #2d3748; word-break: break-word; }
.modal-val a { color: #2b6cb0; }
.modal-highlight { background: #ebf8ff; }
@media (max-width: 900px) {
  .stats { grid-template-columns: 1fr 1fr; }
  .summary-grid { grid-template-columns: 1fr; }
  .modal { width: 98vw; }
  .modal-row { grid-template-columns: 1fr; }
  .modal-label { border-bottom: none; }
}
"""

# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

JS_TEMPLATE = """
// Datos de detalle por RUT
const DETALLES = {detalles_json};

// Busqueda en tabla de autorizadas
const apRows = Array.from(document.querySelectorAll('#ap-table tbody tr'));
const cntAp  = document.getElementById('ap-count');

function buscar() {{
  const texto = document.getElementById('f-buscar').value.toLowerCase().trim();
  // Filtrar filas de datos
  apRows.forEach(tr => {{
    if (tr.classList.contains('mes-header')) return;
    const ok = !texto || tr.textContent.toLowerCase().includes(texto);
    tr.classList.toggle('hidden', !ok);
  }});
  // Ocultar cabeceras de mes sin filas visibles debajo
  const mesRows = apRows.filter(tr => tr.classList.contains('mes-header'));
  mesRows.forEach((mesRow, idx) => {{
    const nextMes = mesRows[idx + 1] || null;
    let hasVisible = false;
    let el = mesRow.nextElementSibling;
    while (el && el !== nextMes) {{
      if (!el.classList.contains('hidden')) {{ hasVisible = true; break; }}
      el = el.nextElementSibling;
    }}
    mesRow.classList.toggle('hidden', !hasVisible);
  }});
  // Actualizar contador
  const vis = apRows.filter(tr => !tr.classList.contains('mes-header') && !tr.classList.contains('hidden')).length;
  cntAp.textContent = texto ? vis + ' resultado(s) de ' + apRows.filter(tr => !tr.classList.contains('mes-header')).length : '';
}}

function limpiar() {{
  document.getElementById('f-buscar').value = '';
  apRows.forEach(tr => tr.classList.remove('hidden'));
  cntAp.textContent = '';
}}

document.getElementById('btn-buscar').addEventListener('click', buscar);
document.getElementById('btn-limpiar').addEventListener('click', limpiar);
document.getElementById('f-buscar').addEventListener('keydown', e => {{ if (e.key === 'Enter') buscar(); }});

// Modal
const backdrop = document.getElementById('modal-backdrop');
const mTitle   = document.getElementById('modal-title');
const mSub     = document.getElementById('modal-sub');
const mBody    = document.getElementById('modal-body');

const CAMPOS = {campos_json};

function verDetalle(rut) {{
  const d = DETALLES[rut] || {{}};
  mTitle.textContent = d.razon_social || d.nombre_cmf || rut;
  mSub.textContent   = 'RUT: ' + (d.rut_completo || rut);
  mBody.innerHTML    = '';
  CAMPOS.forEach(([key, label]) => {{
    const val = (d[key] || '').toString().trim();
    if (!val && key !== 'codigo_institucion' && key !== 'rut_completo') return;
    const row = document.createElement('div');
    row.className = 'modal-row' + (key === 'codigo_institucion' ? ' modal-highlight' : '');
    const lbl = document.createElement('div');
    lbl.className = 'modal-label';
    lbl.textContent = label;
    const v = document.createElement('div');
    v.className = 'modal-val';
    if (key === 'sitio_web' && val && val !== '---') {{
      const a = document.createElement('a');
      a.href = val.startsWith('http') ? val : 'http://' + val;
      a.target = '_blank';
      a.textContent = val;
      v.appendChild(a);
    }} else if (key === 'email' && val && val !== '---') {{
      const a = document.createElement('a');
      a.href = 'mailto:' + val;
      a.textContent = val;
      v.appendChild(a);
    }} else {{
      v.textContent = val || (key === 'codigo_institucion' ? 'No asignado' : '-');
    }}
    row.appendChild(lbl);
    row.appendChild(v);
    mBody.appendChild(row);
  }});
  backdrop.classList.add('open');
}}

function cerrarModal() {{ backdrop.classList.remove('open'); }}
backdrop.addEventListener('click', e => {{ if (e.target === backdrop) cerrarModal(); }});
document.getElementById('modal-close').addEventListener('click', cerrarModal);
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') cerrarModal(); }});
"""


# ---------------------------------------------------------------------------
# HTML principal
# ---------------------------------------------------------------------------

def generar_html(records: list[dict]) -> str:
    hoy      = datetime.now().strftime("%d/%m/%Y %H:%M")
    corte_90 = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    fecha_ini = to_display_date(corte_90)

    # Tarjeta 1: resoluciones en los últimos 90 días
    total_90d = sum(1 for r in records if r.get("fecha", "") >= corte_90)

    # Resumen por categoria y tipo — se calcula DESPUES de definir autorizadas
    # (ver más abajo, tras filtrar autorizadas)

    # Rango de fechas del conjunto completo desde 2024
    fechas_2024 = sorted(r["fecha"] for r in records if r.get("fecha", "") >= "2024-01-01")
    rango = (
        f"{to_display_date(fechas_2024[0])} - {to_display_date(fechas_2024[-1])}"
        if fechas_2024 else "-"
    )

    # Autorizadas desde 2024 y vigentes (base de todo el dashboard)
    autorizadas = [
        r for r in records
        if r.get("autoriza_prestacion")
        and r.get("fecha", "") >= "2024-01-01"
        and r.get("vigencia", "").strip().lower() != "no vigente"
    ]

    # Resumen por categoria y tipo: últimos 90 días
    cats  = Counter(r.get("categoria", "otro") for r in autorizadas if r.get("fecha", "") >= corte_90)
    tipos = Counter(r.get("tipo_empresa", "Otra") for r in autorizadas if r.get("fecha", "") >= corte_90)

    # Grafico: conteo por tipo de servicio — últimos 90 días
    servicios_counter = Counter(
        r.get("tipo_servicio", "") or "Sin clasificar"
        for r in autorizadas
        if r.get("entidad") and r.get("fecha", "") >= corte_90
    )
    max_s = max(servicios_counter.values()) if servicios_counter else 1

    # Tarjetas 2 y 3: datos de los últimos 90 días
    autorizadas_90d = sum(1 for r in autorizadas if r.get("fecha", "") >= corte_90)
    sin_codigo_90d = sum(
        1 for r in autorizadas
        if r.get("fecha", "") >= corte_90
        and r.get("codigo_institucion", "") in ("", "No asignado")
    )

    # --- Diccionario de detalles para el modal (indexado por RUT) ---
    detalles: dict[str, dict] = {}
    for r in autorizadas:
        rut = r.get("rut", "")
        if rut:
            detalles[rut] = {k: r.get(k, "") for k, _ in CAMPOS_MODAL}
            detalles[rut]["nombre_cmf"] = r.get("nombre_cmf", "")

    detalles_json = json_para_script(detalles)
    campos_json   = json_para_script([[k, lbl] for k, lbl in CAMPOS_MODAL])

    js = JS_TEMPLATE.format(
        detalles_json=detalles_json,
        campos_json=campos_json,
    )

    # --- Tabla AUTORIZA LA PRESTACION agrupada por mes ---
    filas_ap: list[str] = []
    mes_actual = None
    for r in autorizadas:
        fecha_iso = r.get("fecha", "")
        ym = fecha_iso[:7] if len(fecha_iso) >= 7 else ""
        if ym and ym != mes_actual:
            mes_actual = ym
            filas_ap.append(
                f'<tr class="mes-header">'
                f'<td colspan="7">{mes_nombre(ym)}</td>'
                f'</tr>'
            )
        rut = r.get("rut", "")
        rut_fmt = r.get("rut_completo") or rut or "-"
        cod = r.get("codigo_institucion", "")
        cod_html = (
            f'<span class="cod-inst">Cod. {cod}</span>'
            if cod and cod != "No asignado"
            else '<span class="cod-na">No asignado</span>'
        )
        btn = (
            f'<button class="btn-ver" onclick="verDetalle(\'{rut}\')" title="Ver ficha CMF">Ver</button>'
            if rut else ""
        )
        filas_ap.append(
            f"<tr>"
            f"<td>{to_display_date(fecha_iso)}</td>"
            f"<td><strong>{html_lib.escape(r.get('entidad',''))}</strong></td>"
            f"<td class='mono'>{html_lib.escape(rut_fmt)} {cod_html}</td>"
            f"<td>{html_lib.escape(r.get('tipo_servicio',''))}</td>"
            f"<td>{html_lib.escape(r.get('tipo_entidad_cmf',''))}</td>"
            f"<td>{vig_html(r.get('vigencia',''))}</td>"
            f"<td>{btn}</td>"
            f"</tr>"
        )

    sin_ap = (
        '<tr><td colspan="7" style="text-align:center;color:#718096;padding:20px">'
        'Sin registros AUTORIZA LA PRESTACION en el periodo</td></tr>'
    )

    # --- Barras del grafico de tipo de servicio ---
    barras = ""
    for servicio, count in servicios_counter.most_common():
        pct = round(count / max_s * 100)
        barras += (
            f'<div class="bar-row">'
            f'<div class="bar-label">{html_lib.escape(servicio)}</div>'
            f'<div class="bar-track">'
            f'<div class="bar-fill" style="width:{pct}%"></div>'
            f'</div>'
            f'<span class="bar-count">{count}</span>'
            f'</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Monitoreo CMF - Resoluciones de Autorización de Entidades</title>
  <style>{CSS}</style>
</head>
<body>

<!-- Modal -->
<div class="modal-backdrop" id="modal-backdrop">
  <div class="modal" role="dialog" aria-modal="true">
    <div class="modal-header">
      <div>
        <h2 id="modal-title">Ficha de la Entidad</h2>
        <div class="sub" id="modal-sub"></div>
      </div>
      <button class="modal-close" id="modal-close" aria-label="Cerrar">&times;</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<header>
  <h1>Monitoreo CMF - Resoluciones de Autorización de Entidades</h1>
  <p>Fuente: Comision para el Mercado Financiero (CMF Chile) &nbsp;&middot;&nbsp;
     Periodo: {rango} &nbsp;&middot;&nbsp; Actualizado: {hoy}</p>
</header>

<div class="container">

  <div class="stats">
    <div class="card">
      <div class="val">{total_90d}</div>
      <div class="lbl">Resoluciones en los últimos 90 días (desde {fecha_ini})</div>
    </div>
    <div class="card">
      <div class="val">{autorizadas_90d}</div>
      <div class="lbl">Entidades autorizadas en los últimos 90 días (desde {fecha_ini})</div>
    </div>
    <div class="card">
      <div class="val">{sin_codigo_90d}</div>
      <div class="lbl">Sin código de institución en los últimos 90 días (desde {fecha_ini})</div>
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">Entidades autorizadas por Tipo de Servicio en los últimos 90 días ({autorizadas_90d}) (desde {fecha_ini})</h2>
    <div class="chart-wrap">
      {barras if barras else '<p style="color:#718096;font-size:.85rem;">Sin datos</p>'}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">
      Nuevas Entidades Autorizadas - AUTORIZA LA PRESTACION ({len(autorizadas)})
      &nbsp;<span style="font-weight:400;font-size:.75rem;color:#718096">Haz clic en "Ver" para abrir la ficha oficial CMF</span>
    </h2>
    <div class="search-bar">
      <input type="text" id="f-buscar" placeholder="Buscar entidad, RUT, tipo de servicio...">
      <button class="btn-buscar" id="btn-buscar">Buscar</button>
      <button class="btn-limpiar" id="btn-limpiar">Limpiar</button>
      <span id="ap-count"></span>
    </div>
    <table id="ap-table">
      <thead>
        <tr>
          <th>Fecha</th>
          <th>Entidad</th>
          <th>RUT / Cod. Institucion</th>
          <th>Tipo de Servicio</th>
          <th>Registro CMF</th>
          <th>Vigencia</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {"".join(filas_ap) if filas_ap else sin_ap}
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2 class="section-title">Resumen por categoría y tipo de empresa en los últimos 90 días (desde {fecha_ini})</h2>
    <div class="summary-grid">
      <div>
        <strong style="font-size:.82rem;color:#4a5568;">Por categoria</strong>
        {tabla_resumen(cats, "Categoria")}
      </div>
      <div>
        <strong style="font-size:.82rem;color:#4a5568;">Por tipo de empresa</strong>
        {tabla_resumen(tipos, "Tipo de empresa")}
      </div>
    </div>
  </div>

</div>
<script>{js}</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def run() -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    records = cargar_datos()

    if not records:
        print("No hay datos en data/. Ejecuta scraper.py y classifier.py primero.")
        return ""

    html = generar_html(records)
    path = os.path.join(REPORTS_DIR, "dashboard.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard generado: {path}")
    return path


if __name__ == "__main__":
    run()
