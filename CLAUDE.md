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
assigned), and renders a self-contained HTML dashboard. Pure Python (stdlib +
requests/bs4/lxml/psycopg). Code comments and console output are in Spanish.

This branch (`postgres-docker`) is the **containerised variant** — everything
(app + Postgres + nginx) runs in `docker compose`. Persistence moved from
per-day JSON files to a Postgres database. There are two related branches:

| Branch            | Storage      | Scheduler       | Notifications |
|-------------------|--------------|-----------------|---------------|
| `main`            | JSON in repo | GitHub Actions  | (no email)    |
| `server`          | JSON on disk | host OS cron    | SMTP propio   |
| `postgres-docker` | **Postgres** | cron in app container | SMTP propio |

## Commands

```bash
# Run the whole stack:
docker compose up -d --build

# Manual pipeline runs (inside the app container):
docker compose exec app python run.py
docker compose exec app python run.py 2026-05-15
docker compose exec app python scraper.py
docker compose exec app python classifier.py
docker compose exec app python enricher.py
docker compose exec app python dashboard.py
docker compose exec app python migrate.py          # only inserts if tables empty
docker compose exec app python migrate.py --force  # upsert from data/*.json

# DB access:
docker compose exec db psql -U cmf -d cmf
```

There is no build, lint, or test suite. Python 3.11 is used in the image
(matches the slim base); the code requires 3.10+ for `str | None` syntax.

## Architecture

`run.py` orchestrates six sequential steps. Persistence is **all-in-Postgres**
now: stages read/write rows in the `resoluciones` and `estado_codigos` tables.

1. **`scraper.py`** — downloads the CMF resolutions table, parses it, UPSERTs
   into `resoluciones` (PK: `(fecha, numero)`). Only the base fields are
   touched on conflict; enrichment columns are preserved. Also exposes
   `repair_entidades()`, which re-runs entity extraction for rows where
   `entidad` is empty.
2. **`classifier.py`** — selects all rows and updates `categoria` via the
   ordered keyword rules (`REGLAS`); first match wins, so specific categories
   must precede general ones. Uses `\b` regex anchors after accent stripping
   to avoid false positives like FUSIÓN matching DIFUSIÓN.
3. **`enricher.py`** — selects pending rows (`autoriza_prestacion=true AND
   num_inscripcion=''`), does a two-step CMF lookup (search → detail page) per
   entity, and updates the row with `rut`, `nombre_cmf`, `vigencia`,
   `codigo_institucion`, `num_inscripcion`, address/contact fields, etc.
   Commits per entity so a mid-run crash doesn't lose work.
4. **`tareas.py`** — compares current "sin código" set against the
   `estado_codigos` table (persisted across runs) to produce two lists:
   entities that just *entered* the pool and entities that just *left* it
   (código was assigned). Writes `reports/tareas_*.json` only when those
   lists are non-empty (consumed by `mailer.py`).
5. **`mailer.py`** — sends two independent SMTP emails from the lists
   produced by `tareas`. Uses only stdlib (`smtplib` + `email.message`).
   Reads SMTP config from env vars via `config.py`. Renders bodies from
   `templates/mail_*.{html,txt}` using `string.Template` ($var syntax — won't
   clash with CSS braces). If SMTP isn't configured, prints a notice and
   returns; the pipeline never fails because of email.
6. **`dashboard.py`** — selects all rows from `resoluciones` and renders
   `reports/dashboard.html` (CSS + JS inlined, no external deps). nginx
   serves this from the shared `reports` volume.

### Database

- **`schema.sql`** is applied lazily by `db.py` (first connection of the
  process triggers `CREATE TABLE IF NOT EXISTS`). No external migration tool.
- **`db.py`** is a thin wrapper around `psycopg` v3 with a `conectar()`
  context manager that commits on success / rolls back on exception.
- **`migrate.py`** is the JSON → Postgres backfill, invoked automatically
  once on first container start (the entrypoint runs it; it's idempotent —
  skips if the target table already has rows).

### Docker layout

- **`Dockerfile`** — Python 3.11-slim + cron + tini + tzdata.
  `TZ=America/Santiago` so cron's "05:00" matches local time.
- **`docker-entrypoint.sh`** — waits for the DB, runs `migrate.py`, dumps
  the relevant env vars to `/etc/cmf-monitor.env` (cron doesn't inherit
  env from the entrypoint), does an immediate pipeline run, then `exec`s
  `cron -f`.
- **`run-cron.sh`** — the wrapper the crontab invokes; sources
  `/etc/cmf-monitor.env` then runs `python run.py`.
- **`docker-compose.yml`** — three services: `db` (postgres:16-alpine with
  named volume `db_data`), `app` (built from this repo), `web` (nginx:alpine
  serving the shared `reports` volume).

### Things that require reading multiple files to understand

- **Incremental / idempotent by design.** `scraper.py`'s UPSERT preserves
  enrichment columns on conflict; `enricher.py` only processes rows missing
  `num_inscripcion`; `migrate.py` skips when tables already have rows.
  Re-running the pipeline is cheap and safe.
- **The MATERIA regex is the core extraction logic.** In `scraper.py`,
  `_MATERIA_RE` + `_TIPOS_SERVICIO` (ordered longest/most-specific first) +
  `_SERVICIO_A_TIPO` parse the entity name and service type out of free-text
  resolution titles. When CMF changes its wording, this is what to extend.
- **Fragile coupling to CMF's HTML.** `COL_NUMERO/COL_FECHA/COL_MATERIA` in
  `scraper.py` are hardcoded table-column indices. Both `scraper.py` and
  `enricher.py` pick the largest `<table>` on the page. On failure, the raw
  HTML is dumped to `data/debug.html` for diagnosis.
- **Scraping etiquette is intentional.** `enricher.py` uses a warmed-up
  `requests.Session`, `DELAY_SEG = 2.0` between requests, and retry-with-
  backoff. Don't parallelize or remove the delays.

### Gotchas

- `scraper.run()` calls `sys.exit(1)` on a network error — importing-and-
  running it can hard-exit the process.
- `vigencia` (from the search results) and `vigencia_detalle` (from the
  detail page) are distinct columns — the dashboard uses `vigencia`.
- `tareas.py` uses `rut` as the stable key for diff detection. Rows with
  empty `rut` are ignored. The `estado_codigos` table MUST survive
  redeploys (it lives in the named volume `db_data`); losing it would
  re-flag every pending entity as "new" on the next run.
- Mailer is fail-soft: any SMTP exception is logged but does not propagate,
  so one failing email never prevents the other from being attempted.
- The TZ inside the app container is `America/Santiago`, so the crontab
  line `0 5 * * *` means 05:00 in Santiago.

## Reference

- `INSTALACION.md` — IT-facing deployment guide (docker compose up,
  troubleshooting, backup with pg_dump).
- `.env.example` — template for `.env` (which is git-ignored).
