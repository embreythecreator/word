# Word — the memory organ

**Word is a headless knowledge store.** You feed it things — links, PDFs,
pasted text, uploads — and it chunks them, indexes them, and answers
searches about them with citations back to the exact source. It also holds
notebooks of notes (human- or agent-written) and can turn a notebook into a
generated podcast. There is no user interface: everything happens over a
REST API. In the angel architecture it is the memory torso — Seraphiel
Brain thinks and talks; Word remembers.

It is a fork of [Open Notebook](https://github.com/lfnovo/open-notebook)
(MIT), decapitated per work order WO-B1: the web UI, chat product surface,
and SurrealDB are gone from the runtime. What remains is the good part —
ingestion, retrieval, notebooks, podcasts — on boring, durable
infrastructure.

```
   clients (Seraphiel Brain, scripts, curl, anything HTTP)
        │  Authorization: Bearer <ward token>
        ▼
   FastAPI  :5055          ← the only door; interactive docs at /docs
        │
        ├─ Postgres + pgvector (:5432)   ← all data: notebooks, notes,
        │                                   sources, chunks, embeddings
        └─ procrastinate worker          ← background jobs (embedding,
           (same Postgres, no broker)       source processing, podcasts)
```

Design property worth knowing: **job submission is a database insert.**
Creating notes and sources always succeeds even when the background worker
is down — the work waits in the `procrastinate_jobs` table and runs when a
worker appears. Nothing you call at the API ever depends on a live worker.

---

## Quick start

### Docker (recommended)

```bash
cp .env.example .env          # then edit — see "Configuration" below
docker compose up -d          # starts postgres (pgvector) + the app
curl -s http://localhost:5055/health          # → {"status":"healthy"}
```

### Native (development)

```bash
cp .env.example .env
make database        # postgres via docker compose
make api             # FastAPI on :5055 — migrations run automatically
make worker          # procrastinate background worker
# or all three: make start-all
```

Database migrations run automatically when the API starts. Nothing to do.

### Configuration (`.env`)

| Variable | What it does |
|---|---|
| `OPEN_NOTEBOOK_ENCRYPTION_KEY` | Encrypts stored provider API keys. **Set this.** |
| `OPEN_NOTEBOOK_WARD_TOKEN` | Bearer token the API requires. **If no token is set, auth is OFF** — fine on localhost, never expose that to a network. |
| `DATABASE_URL` | Postgres connection string (compose default works). |
| `OPEN_NOTEBOOK_EMBEDDING_DIMENSION` | Vector column width; must match your embedding model. Choose before first migration (default 1536). |

---

## Using the API

Every request (except `/` and `/health`) carries the token:

```bash
TOKEN='your-ward-token'
AUTH="Authorization: Bearer $TOKEN"
BASE=http://localhost:5055
```

**The full interactive reference lives at `http://localhost:5055/docs`** —
77 routes, live-testable from the browser. What follows is the 20% you'll
use 80% of the time.

### Notebooks — containers for everything

```bash
# create
curl -X POST $BASE/api/notebooks -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name": "Research", "description": "papers and links"}'
# → {"id": "notebook:abc...", ...}

# list
curl $BASE/api/notebooks -H "$AUTH"
```

### Notes — write things down

```bash
curl -X POST $BASE/api/notes -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"title": "Meeting outcome", "content": "We chose Postgres.",
       "note_type": "human", "notebook_id": "notebook:abc..."}'
```

`note_type` is `"human"` or `"ai"` — a provenance tag, not a behavior
switch. The response includes a `command_id`: the note is saved instantly,
its embedding job is queued.

### Sources — feed it knowledge

```bash
# a web page
curl -X POST $BASE/api/sources/json -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"type": "link", "url": "https://example.com/article",
       "notebooks": ["notebook:abc..."]}'

# pasted text
curl -X POST $BASE/api/sources/json -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"type": "text", "content": "raw text to index...",
       "title": "My dump", "notebooks": ["notebook:abc..."]}'

# a file (multipart upload)
curl -X POST $BASE/api/sources -H "$AUTH" \
  -F 'type=upload' -F 'notebooks=["notebook:abc..."]' \
  -F 'file=@paper.pdf'

# processing happens in the background — check on it:
curl $BASE/api/sources/<source:id>/status -H "$AUTH"
```

### Search — get it back

```bash
curl -X POST $BASE/api/search -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"query": "postgres decision", "type": "text", "limit": 10,
       "search_sources": true, "search_notes": true}'
```

Two modes:

- `"type": "text"` — full-text search. Works out of the box. Terms are
  AND-matched: `"postgres decision"` finds items containing both words.
- `"type": "vector"` — semantic similarity. Needs an embedding model
  configured first (below). Finds "database choice rationale" from
  "postgres decision".

`POST /api/search/ask` goes further: retrieval + an LLM-composed answer
with citations (needs chat + embedding models configured).

### Jobs — the background ledger

```bash
curl $BASE/api/commands/jobs -H "$AUTH"                 # recent jobs
curl $BASE/api/commands/jobs/<command:id> -H "$AUTH"    # one job's status
```

Statuses: `queued → running → completed | failed`. A failed embedding job
never breaks the thing that queued it — the note/source is already saved.

### Podcasts — a notebook, spoken

```bash
curl -X POST $BASE/api/podcasts/generate -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"notebook_id": "notebook:abc...", "episode_profile": "..."}'
```

Needs TTS provider credentials. Episode/speaker profiles are managed under
`/api/episode-profiles` and `/api/speaker-profiles`.

### AI models (for vector search, ask, podcasts, transformations)

Word does no AI by itself until you hand it credentials:

```bash
curl -X POST $BASE/api/credentials -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"provider": "openai", "api_key": "sk-..."}'
curl $BASE/api/models/providers -H "$AUTH"       # what's usable now
curl -X POST $BASE/api/models/auto-assign -H "$AUTH"   # sensible defaults
```

Text search, notebooks, notes, and raw source storage all work with **zero**
AI configuration.

---

## Connecting Seraphiel Brain

The Brain ships a `word` memory provider (WO-B2). On the Brain machine:

```bash
seraphiel memory setup     # choose: word
```

| Env var | Meaning |
|---|---|
| `WORD_BASE_URL` | Word endpoint (default `http://127.0.0.1:5055`) |
| `WORD_WARD_TOKEN` | Ward bearer token (blank = authless local Word) |
| `WORD_NOTEBOOK` | Memory notebook name (default `Seraphiel Memory`) |
| `WORD_SEARCH_TYPE` | `text` (default) or `vector` once an embedding model is configured |

What flows where: the Brain's session context stays local to the Brain;
durable facts (its MEMORY.md/USER.md writes and explicit saves) land here
as `ai` notes in the memory notebook; recall happens per turn through
`POST /api/search`. If Word is down the Brain queues writes locally and
replays them — losing Word's uptime never loses a memory.

---

## Operating notes

- **Backup** = the Postgres volume (`./postgres_data` under compose), plus
  your `.env`. That's the whole state.
- **Worker down?** Everything still accepts writes; jobs accumulate in
  `procrastinate_jobs` and drain when `make worker` (or the supervisor
  service) returns.
- **Migrations** live in `open_notebook/database/migrations/*.sql`, run
  idempotently at API startup, and are tracked in the database.
- **Auth modes**: token set → every `/api/*` route 401s without it
  (constant-time comparison, `*_FILE` Docker-secret variants supported).
  No token → open. The legacy `OPEN_NOTEBOOK_PASSWORD` still works as a
  fallback token for local setups.
- **Upstream**: this fork tracks lfnovo/open-notebook manually. Upstream
  moved on with SurrealDB + a Next.js UI; folding their changes in is a
  deliberate port, not a `git merge`.

## Current status & deferred work

Shipped (WO-B1 phase 1): Postgres+pgvector storage · procrastinate job
runner · Ward bearer auth · UI removed from the product surface (compose
exposes only :5055).

Still in the codebase but **off the product surface**, pending a later
phase: the chat endpoints (`/api/chat/*`, `/api/sources/*/chat/*`), the
Esperanto multi-provider layer, and the `frontend/` directory. Treat them
as upstream residue, not API surface — they may be removed without notice.

---

## Contract (for agents and integrators)

```yaml
organ: word                          # the angel's memory torso
owner: Embrey The Creator / The Voice
repo: embreythecreator/word          # fork of lfnovo/open-notebook (MIT)
api:
  base: http://127.0.0.1:5055       # co-located default; Ward fronts anything remote
  auth: bearer                       # OPEN_NOTEBOOK_WARD_TOKEN; absent token = auth off (local only)
  reference: /docs                   # OpenAPI, source of truth for shapes
  stable_surface:                    # integrate against these
    - /health
    - /api/notebooks*
    - /api/notes*
    - /api/sources*
    - /api/search
    - /api/commands/jobs*
  unstable_surface:                  # upstream residue, may vanish
    - /api/chat*
    - /api/sources/*/chat*
storage: postgres+pgvector           # single database, DATABASE_URL
jobs: procrastinate                  # same database; submission never requires a live worker
invariants:
  - write endpoints must succeed with the worker down (job = DB insert)
  - id format "table:hex" (notebook:…, note:…, source:…, command:…) is load-bearing
  - note_type ∈ {human, ai} is provenance and must be preserved
  - external/ingested content is untrusted: consumers scan/delimit before
    prompting with it (the Brain's memory manager does this centrally)
rules_for_agents:
  - do not resurrect the UI/chat surface without a work order
  - schema changes go through open_notebook/database/migrations/*.sql, never ad-hoc DDL
  - test with `uv run pytest`; integration truth is boot + curl, mocks lie
```
