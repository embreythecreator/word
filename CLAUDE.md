# Word - Root CLAUDE.md

This file provides architectural guidance for contributors working on this repo at the project level.

## Project Overview

**Word** is a headless knowledge store — the angel architecture's memory organ. It is a fork of Open Notebook (an open-source Notebook LM alternative), decapitated per work order WO-B1: ingestion, chunking/embedding, notebooks/notes, citation-grounded search, and the podcast engine remain; the web UI and chat product surface are off the product surface; storage is Postgres+pgvector and background jobs run on procrastinate. Everything happens over a Ward-authenticated REST API on :5055.

**Read [WORD.md](WORD.md) first** — identity, quick start, API how-to, and the agent/integrator contract (stable vs unstable surface, invariants).

**Key Values**: Privacy-first, boring durable infrastructure, API-only surface, open-source transparency.

---

## Three-Tier Architecture

```
┌─────────────────────────────────────────────────────────┐
│              API (FastAPI)                              │
│              api/ @ port 5055 — the only product door   │
├─────────────────────────────────────────────────────────┤
│ - REST endpoints for notebooks, sources, notes, search  │
│ - Ward bearer-token auth middleware                     │
│ - LangGraph workflow orchestration                      │
│ - procrastinate job queue (async embedding/podcasts)    │
│ - Multi-provider AI provisioning via Esperanto          │
└────────────────────────┬────────────────────────────────┘
                         │ SQL (psycopg)
┌────────────────────────▼────────────────────────────────┐
│         Database (Postgres + pgvector)                  │
│         @ port 5432                                     │
├─────────────────────────────────────────────────────────┤
│ - Records: Notebook, Source, Note, ChatSession, Credential│
│ - Relationships: source-to-notebook, note-to-source     │
│ - pgvector embeddings for semantic search               │
│ - procrastinate_jobs table (the job queue IS the DB)    │
└─────────────────────────────────────────────────────────┘

(frontend/ still exists in-repo but is OFF the product surface —
upstream residue pending removal; do not build features on it.)
```

---

## Useful sources

User documentation is at @docs/

## Tech Stack

### Frontend (`frontend/`)
- **Framework**: Next.js 16 (React 19)
- **Language**: TypeScript
- **State Management**: Zustand
- **Data Fetching**: TanStack Query (React Query)
- **Styling**: Tailwind CSS + Shadcn/ui
- **Build Tool**: Webpack (via Next.js)
- **i18n compatible**: All front-end changes must also consider the translation keys

### API Backend (`api/` + `open_notebook/`)
- **Framework**: FastAPI 0.104+
- **Language**: Python 3.11+
- **Workflows**: LangGraph state machines
- **Database**: Postgres + pgvector (psycopg3, async)
- **AI Providers**: Esperanto library (8+ providers: OpenAI, Anthropic, Google, Groq, Ollama, Mistral, DeepSeek, xAI)
- **Job Queue**: procrastinate (Postgres-native) for async jobs — submission is a DB insert; no live worker required by any request path
- **Logging**: Loguru
- **Validation**: Pydantic v2
- **Testing**: Pytest

### Database
- **Postgres + pgvector**: relational store with vector similarity search
- **Schema Migrations**: plain SQL in `open_notebook/database/migrations/*.sql`, applied automatically on API startup via AsyncMigrationManager

### Additional Services
- **Content Processing**: content-core library (file/URL extraction)
- **Prompts**: AI-Prompter with Jinja2 templating
- **Podcast Generation**: podcast-creator library
- **Embeddings**: Multi-provider via Esperanto

---

## Architecture Highlights

### 1. Async-First Design
- All database queries, graph invocations, and API calls are async (await)
- psycopg3 async connection pool to Postgres
- FastAPI handles concurrent requests efficiently

### 2. LangGraph Workflows
- **source.py**: Content ingestion (extract → embed → save)
- **chat.py**: Conversational agent with message history
- **ask.py**: Search + synthesis (retrieve relevant sources → LLM)
- **transformation.py**: Custom transformations on sources
- All use `provision_langchain_model()` for smart model selection

### 3. Multi-Provider AI
- **Esperanto library**: Unified interface to 8+ AI providers
- **Credential system**: Individual encrypted credential records per provider; models link to credentials for direct config
- **ModelManager**: Factory pattern with fallback logic; uses credential config when available, env vars as fallback
- **Smart selection**: Detects large contexts, prefers long-context models
- **Override support**: Per-request model configuration

### 4. Database Schema
- **Automatic migrations**: AsyncMigrationManager runs on API startup
- **Relational model**: Records with relationship tables and pgvector embedding columns; SurrealDB-style `table:hex` ids preserved as strings (load-bearing across the API)
- **Vector search**: Built-in semantic search across all content
- **Transactions**: Repo functions handle ACID operations

### 5. Authentication
- **Current**: Simple password middleware (insecure, dev-only)
- **Production**: Replace with OAuth/JWT (see CONFIGURATION.md)

---

## Important Quirks & Gotchas

### API Startup
- **Migrations run automatically** on startup; check logs for errors
- **Must start API before UI**: UI depends on API for all data
- **Postgres must be running**: API fails without database connection (`docker compose up -d postgres`)

### Frontend-Backend Communication
- **Base API URL**: Configured in `.env.local` (default: http://localhost:5055)
- **CORS enabled**: Configured in `api/main.py` (allow all origins in dev)
- **Rate limiting**: Not built-in; add at proxy layer for production

### LangGraph Workflows
- **Blocking operations**: Chat/podcast workflows may take minutes; no timeout
- **State persistence**: Uses SQLite checkpoint storage in `/data/sqlite-db/`
- **Model fallback**: If primary model fails, falls back to cheaper/smaller model

### Podcast Generation
- **Async job queue**: `podcast_service.py` submits jobs but doesn't wait
- **Track status**: Use `/api/commands/jobs/{job_id}` to poll status
- **TTS failures**: Fall back to silent audio if speech synthesis fails

### Content Processing
- **File extraction**: Uses content-core library; supports 50+ file types
- **URL handling**: Extracts text + metadata from web pages
- **Large files**: Content processing is sync; may block API briefly

---

## Component References

See dedicated CLAUDE.md files for detailed guidance:

- **[frontend/CLAUDE.md](frontend/CLAUDE.md)**: React/Next.js architecture, state management, API integration
- **[api/CLAUDE.md](api/CLAUDE.md)**: FastAPI structure, service pattern, endpoint development
- **[open_notebook/CLAUDE.md](open_notebook/CLAUDE.md)**: Backend core, domain models, LangGraph workflows, AI provisioning
- **[open_notebook/domain/CLAUDE.md](open_notebook/domain/CLAUDE.md)**: Data models, repository pattern, search functions
- **[open_notebook/ai/CLAUDE.md](open_notebook/ai/CLAUDE.md)**: ModelManager, AI provider integration, Esperanto usage
- **[open_notebook/graphs/CLAUDE.md](open_notebook/graphs/CLAUDE.md)**: LangGraph workflow design, state machines
- **[open_notebook/database/CLAUDE.md](open_notebook/database/CLAUDE.md)**: Postgres/pgvector operations, migrations, async patterns

---

## Documentation Map

- **[WORD.md](WORD.md)**: THE entry point — organ identity, quick start, API how-to, agent contract
- **[README.md](README.md)**: Upstream project overview (kept for lineage)
- **[docs/index.md](docs/index.md)**: Complete user & deployment documentation
- **[CONFIGURATION.md](CONFIGURATION.md)**: Environment variables, model configuration
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: Contribution guidelines
- **[MAINTAINER_GUIDE.md](MAINTAINER_GUIDE.md)**: Release & maintenance procedures

---

## Testing Strategy

- **Unit tests**: `tests/test_domain.py`, `test_models_api.py`
- **Graph tests**: `tests/test_graphs.py` (workflow integration)
- **Utils tests**: `tests/test_utils.py`, `tests/test_chunking.py`, `tests/test_embedding.py`
- **Run all**: `uv run pytest tests/`
- **Coverage**: Check with `pytest --cov`

---

## Common Tasks

### Add a New API Endpoint
1. Create router in `api/routers/feature.py`
2. Create service in `api/feature_service.py`
3. Define schemas in `api/models.py`
4. Register router in `api/main.py`
5. Test via http://localhost:5055/docs

### Add a New LangGraph Workflow
1. Create `open_notebook/graphs/workflow_name.py`
2. Define StateDict and node functions
3. Build graph with `.add_node()` / `.add_edge()`
4. Invoke in service: `graph.ainvoke({"input": ...}, config={"..."})`
5. Test with sample data in `tests/`

### Add Database Migration
1. Create `open_notebook/database/migrations/XXX_description.sql`
2. Write plain SQL schema changes (idempotent where possible)
3. API auto-detects on startup; migration runs if newer than recorded version

### Deploy to Production
1. Review [CONFIGURATION.md](CONFIGURATION.md) for security settings
2. Use `make docker-release` for multi-platform image
3. Push to Docker Hub / GitHub Container Registry
4. Deploy `docker compose --profile multi up`
5. Verify migrations via API logs

---

## Support & Community

- **Documentation**: https://open-notebook.ai
- **Discord**: https://discord.gg/37XJPXfz2w
- **Issues**: https://github.com/lfnovo/open-notebook/issues
- **License**: MIT (see LICENSE)

