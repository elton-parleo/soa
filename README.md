# SoA Platform — Monorepo

Agent Commerce Command Center.
Measures Share of Algorithm across AI shopping agents.

## Structure

```
packages/
  shared/               Python package shared by both apps
    soa_shared/         Models, database, config
                        → pip install -e packages/shared

apps/
  api/                  FastAPI + React frontend → Deploy to Vercel
    api/
      index.py          Vercel serverless entry point (imports app only)
    app/
      app.py            FastAPI application
      schemas.py        Pydantic request/response models
      routers/
        studies.py      GET /api/studies, /api/studies/{type}/queries
        entities.py     GET/POST /api/entities
        cycles.py       GET/POST /api/cycles, /api/cycles/check
    web/                React/Vite frontend
      src/
        App.jsx         View routing (dashboard ↔ wizard)
        api.js          API client
        components/
          CycleDashboard.jsx   Cycle management page
          NewCycleWizard.jsx   5-step new cycle wizard
    requirements.txt
    vercel.json

  pipeline/             Pipeline runner + worker → Deploy to Railway
    orchestrator/       PipelineOrchestrator (runner → coding → metrics)
    runners/            ChatGPT, Gemini, Claude, Perplexity runners
    parser/             Response coding and validation
    metrics/            Metrics calculation and xlsx export
    seeds/              Query and entity seed scripts
    alembic/            Database migrations
    worker.py           Polling worker (polls soa_cycles every 30s)
    main.py             CLI entry point
    railway.toml
    requirements.txt
```

## Architecture

The API and pipeline communicate ONLY through the database.

```
Browser → Vercel (apps/api)
  POST /api/cycles
  → writes soa_cycles status='planned'
  → returns 201 immediately

Railway (apps/pipeline/worker.py)
  → polls soa_cycles every 30s
  → picks up status='planned'
  → runs PipelineOrchestrator
  → updates status='complete'
```

## Local Development

### 1. Shared package
```bash
cd packages/shared
pip install -e . --break-system-packages
```

### 2. Pipeline worker
```bash
cd apps/pipeline
pip install -r requirements.txt --break-system-packages
cp .env.example .env  # fill DATABASE_URL
python worker.py      # start polling
# or use CLI directly:
python main.py pipeline --cycle 2026-05 --study-type retailer_sephora
```

### 3. API + Frontend
```bash
cd apps/api
pip install -r requirements.txt --break-system-packages
cp .env.example .env  # fill DATABASE_URL
uvicorn app.app:app --reload --port 8000 &
cd web && npm install && npm run dev
# Frontend: http://localhost:5173
# API:      http://localhost:8000/api
```

## Deployment

### Vercel (apps/api)
1. Connect repo to Vercel
2. Set Root Directory: `apps/api`
3. Set env vars:
   - `DATABASE_URL_POOLED` (Supabase Transaction pooler URL)
   - `USE_POOLED_DB=true`

### Railway (apps/pipeline)
1. Connect repo to Railway
2. Set Root Directory: `apps/pipeline`
3. Start command: `python worker.py`
4. Set env vars:
   - `DATABASE_URL` (Supabase direct connection)
   - `USE_POOLED_DB=false`
   - `OPEN_AI_API_KEY`
   - `GEMINI_API_KEY`
   - `PERPLEXITY_API_KEY`
   - `ANTHROPIC_CLAUDE_API_KEY`
