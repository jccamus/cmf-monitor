# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Note: this directory (`Nuevas entidades en CMF/`) is its own git repository. The
> `CLAUDE.md` one level up (`Curso/CLAUDE.md`) describes an unrelated course-materials
> repo and does not apply here.

## What this is

**Monitoreo CMF** — a daily pipeline that scrapes authorization resolutions from
Chile's Comisión para el Mercado Financiero (CMF), classifies them, enriches new
entities with official registry data, generates two task-notification emails
(new entities without código de institución; entities whose código was just
assigned), and renders a self-contained HTML dashboard. Pure Python, no
framework. Code comments and console output are in Spanish.

This branch (`server`) is the self-hosted variant — cron + SMTP propio + local
HTTP server. The `main` branch is the GitHub-Actions + Pages variant; the code
overlaps but the deployment target is different.

## Commands

```powershell
python -m pip install -r requirements.txt   # install deps (requests, beautifulsoup4, lxml)

python run.py                # run full pipeline for today
python run.py 2026-05-03     # run full pipeline for a specific date (YYYY-MM-DD)

# each stage is also runnable standalone (same optional date arg):
python scraper.py [fecha]    # also runs repair_entidades() only via run.py
python classifier.py [fecha]
python enricher.py [fecha]   # slow: ~2s/entity, network-bound
python dashboard.py          # no date arg; aggregates all of data/
```

There is no build, lint, or test suite. Requires Python 3.10+ (`str | None` syntax).

## Architecture

`run.py` orchestrates five sequential steps over four modules. The key design fact:
**all stages read and mutate the same per-day file `data/YYYY-MM-DD.json` in place**,
each adding fields to every record. The record schema therefore grows as it flows
through the pipeline:

1. **`scraper.py`** — downloads the CMF resolutions table, parses it, writes the
   day's JSON with base fields (`fecha`, `numero`, `entidad`, `tipo_servicio`,
   `resolucion`, `autoriza_prestacion`, `tipo_empresa`, empty `categoria`). Also
   exposes `repair_entidades()`, which re-runs entity extraction across *all*
   historical JSONs for records where the old regex left `entidad` empty.
2. **`classifier.py`** — fills `categoria` per record via ordered keyword rules
   (`REGLAS`); first match wins, so specific categories must precede general ones.
3. **`enricher.py`** — for each `autoriza_prestacion` entity, does a two-step CMF
   lookup (search → detail page) adding `rut`, `nombre_cmf`, `vigencia`,
   `codigo_institucion`, `num_inscripcion`, address/contact fields, etc.
4. **`tareas.py`** — diffs against `data/_estado_codigos.json` (persisted across
   runs) to produce two lists: entities that just *entered* the "sin código"
   pool, and entities that just *left* it (código was assigned). Writes
   `reports/tareas_*.json` only when those lists are non-empty.
5. **`mailer.py`** — sends two independent SMTP emails from the lists produced by
   `tareas`. Uses only stdlib (`smtplib` + `email.message`). Reads SMTP and
   recipient config from env vars via `config.py`. Renders bodies from
   `templates/mail_*.{html,txt}` using `string.Template` ($var syntax — won't
   clash with CSS braces). If SMTP isn't configured, prints a notice and
   returns; the pipeline never fails because of email.
6. **`dashboard.py`** — reads **every** `data/*.json`, dedups by `(fecha, numero)`,
   and renders `reports/dashboard.html` (CSS + JS inlined, no external deps).

### Things that require reading multiple files to understand

- **Incremental / idempotent by design.** `enricher.py` skips records that already
  have `num_inscripcion`; `repair_entidades()` only touches records with empty
  `entidad`. Re-running the pipeline is cheap and safe — it only does new work.
- **The MATERIA regex is the core extraction logic.** In `scraper.py`,
  `_MATERIA_RE` + `_TIPOS_SERVICIO` (ordered longest/most-specific first) +
  `_SERVICIO_A_TIPO` parse the entity name and service type out of free-text
  resolution titles. When CMF changes its wording, this is what to extend.
- **Fragile coupling to CMF's HTML.** `COL_NUMERO/COL_FECHA/COL_MATERIA` in
  `scraper.py` are hardcoded table-column indices. Both `scraper.py` and
  `enricher.py` pick the largest `<table>` on the page. On failure, the raw HTML
  is dumped to `data/debug*.html` for diagnosis.
- **Two windows that must stay in sync.** `DIAS_HISTORICO = 90` in `scraper.py`
  bounds what gets scraped; `dashboard.py` independently hardcodes a 90-day cutoff
  for its summary cards/charts, and separately filters the main table to
  `autoriza_prestacion` records since `2024-01-01` that are not "no vigente".
- **Scraping etiquette is intentional.** `enricher.py` uses a warmed-up
  `requests.Session`, `DELAY_SEG = 2.0` between requests, and retry-with-backoff.
  Don't parallelize or remove the delays.

### Gotchas

- `scraper.run()` calls `sys.exit(1)` on a network error — importing-and-running
  it can hard-exit the process.
- `data/`, `reports/`, `logs/`, and `__pycache__/` are gitignored (with one
  exception: `data/*.json` IS tracked, so the cron can preserve enrichment
  across runs; `data/debug*.html` stays ignored).
- `vigencia` (from the search results) and `vigencia_detalle` (from the detail
  page) are distinct fields — the dashboard uses `vigencia`.
- `tareas.py` uses `rut` as the stable key for diff detection. Records with
  empty `rut` are ignored. The `_estado_codigos.json` file MUST be preserved
  across runs (it's in `data/`, which is tracked) — losing it would re-flag
  every pending entity as "new" on the next run.
- Mailer is fail-soft: any SMTP exception is logged but does not propagate, so
  one failing email never prevents the other from being attempted.

## Reference

`INSTALACION.md` is the IT-facing deployment doc (Windows Task Scheduler / Linux
cron at 05:00 America/Santiago, dashboard publishing options, troubleshooting).
