# n8n Self-hosted AI Starter Kit - AI Assistant Instructions

## Project Overview

This is a Docker Compose-based starter kit that provides a complete local AI development environment combining n8n (workflow automation), Ollama (local LLMs), Qdrant (vector database), and PostgreSQL. The project enables rapid prototyping of AI workflows while maintaining complete privacy and offline capability.

## Core Architecture

### Service Stack
- **n8n**: Main workflow platform at `localhost:5678`
- **Ollama**: LLM inference server at `localhost:11434` (CPU/GPU profiles)
- **Qdrant**: Vector database at `localhost:6333`
- **PostgreSQL**: Persistent storage with shared volumes
- **n8n-import**: Init container that seeds database from `n8n/demo-data/`

### Key Files
- `docker-compose.yml`: Multi-profile setup (cpu, gpu-nvidia, gpu-amd)
- `render.yaml`: Production deployment blueprint for Render.com
- `scripts/export_n8n_data.py`: Export workflows/credentials from live instance
- `scripts/import_n8n_data.py`: Import workflows/credentials (idempotent)
- `n8n/demo-data/`: Repository-tracked workflow/credential JSON files

## Development Workflows

### Local Development
```bash
# CPU-only setup
docker compose --profile cpu up

# GPU setup (Nvidia)
docker compose --profile gpu-nvidia up

# Mac with local Ollama
OLLAMA_HOST=host.docker.internal:11434 docker compose up
```

### Docker Image Updates
**Problem**: n8n image may be behind by several versions
**Solution**:
1. **Use latest for automatic updates** in `render.yaml`:
   ```yaml
   image:
     url: docker.io/n8nio/n8n:latest
   ```
2. **Update workflow**:
   - Render automatically pulls latest on rebuild
   - Monitor for breaking changes in n8n releases
3. **For local development**: Pin specific versions in `docker-compose.yml` for consistency

### Production Deployment (Render)
1. **Environment Setup**: Keep `N8N_ENCRYPTION_KEY` identical across deploys (credentials become unreadable if changed)
2. **Data Export**: `python scripts/export_n8n_data.py` (requires Basic Auth env vars)
3. **Deploy**: Push to main branch triggers Render rebuild
4. **Data Import**: `python scripts/import_n8n_data.py --wait-ready 120` (or use GitHub Actions)
5. **Prevent Sleep**: Render free tier services sleep after inactivity
   - Use n8n's built-in HTTP Request node to ping your service every 10-14 minutes
   - Create a simple workflow with Cron trigger: `*/10 * * * *`
   - HTTP Request to your own Render URL: `https://your-n8n.onrender.com/rest/healthz`
   - Alternative: Use external monitoring services that support custom headers for Basic Auth

### GitHub Actions Integration
- `.github/workflows/sync-n8n.yml`: Manual workflow dispatch for data sync
- Requires repository secrets: `N8N_BASE_URL`, `N8N_BASIC_AUTH_USER`, `N8N_BASIC_AUTH_PASSWORD`
- Use `--min-workflows` and `--min-credentials` for safety guards
- Run from GitHub Actions tab for automated import

## Project-Specific Patterns

### Data Management
- **Encrypted Credentials**: JSON files contain encrypted blobs (safe to commit with same encryption key)
- **Workflow IDs**: Never manually edit `id` fields - scripts handle upsert by ID
- **File Naming**: Auto-generated as `{id}-{slugified-name}.json`

### Container Dependencies
- `n8n-import` runs first, seeds database, then exits successfully
- Main `n8n` service waits for postgres health check + successful import
- Ollama auto-pulls `llama3.2:latest` on first startup

### Environment Variables
- Local: Copy `.env.example` to `.env`, generate 32-char hex for `N8N_ENCRYPTION_KEY`
- Render: Database vars auto-injected via `render.yaml`, manually set auth/encryption vars
- Mac Users: Set `OLLAMA_HOST=host.docker.internal:11434` for local Ollama
- **File Permissions**: Add `N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true` to fix settings file permissions warnings

### File System Access
- Shared volume mounted at `/data/shared` inside n8n container
- Use this path in File Read/Write nodes, Execute Command nodes, Local File Trigger

## Critical Considerations

### Encryption Key Management
**NEVER** change `N8N_ENCRYPTION_KEY` after first deploy - existing credentials become permanently unreadable. Keep backups of this value.

### Import/Export Safety
- Scripts are idempotent (safe to run multiple times)
- Use `--dry-run` flag to validate before actual import
### n8ncloud — AI agent quick guide

Short, actionable notes an AI assistant needs to be productive in this repo.

What this repo is: a Docker Compose-based n8n starter (n8n + Ollama + Qdrant + Postgres) with a Render deployment blueprint.

Essential files:
- `docker-compose.yml` — local runtime; supports profiles `cpu`, `gpu-nvidia`, `gpu-amd`.
- `render.yaml` — Render service manifest. Declares env keys (most marked `sync:false`) — set secrets in Render dashboard or via CLI.
- `n8n/demo-data/` — workflows + credentials used by `n8n-import`. Filenames are `{id}-{slugified-name}.json` and imports are idempotent.
- `scripts/import_n8n_data.py` / `scripts/export_n8n_data.py` — import/export tooling. Use `--dry-run` and `--wait-ready` when automating.

Concrete commands (copy/paste):
- Start local stack (CPU):
   docker compose --profile cpu up
- Import demo data (wait for service readiness):
   python scripts/import_n8n_data.py --wait-ready 120
- Test a Postgres URL (useful when validating Neon):
   docker run --rm postgres:17 psql "<POSTGRES_URL>?sslmode=require&channel_binding=require" -c "SELECT version();"

Project-specific conventions & gotchas:
- NEVER rotate `N8N_ENCRYPTION_KEY` after deploy — encrypted credentials become unreadable.
- Credential files in `n8n/demo-data/` are encrypted blobs; workflows reference credential names (not raw secrets).
- This repo avoids storing secrets: `.gitignore` includes `.env` and `credentials/`. For runtime, prefer `DB_POSTGRESDB_CONNECTION_URL` (full URL) or set `DB_POSTGRESDB_*` envs.
- On Render, set `DB_POSTGRESDB_CONNECTION_URL` exactly (including `sslmode=require&channel_binding=require`) — common deploy errors (ENOTFOUND, ECONNREFUSED, "connection insecure") come from wrong/missing env values.
   - Recommended production DB: Neon (https://neon.tech). Prefer supplying the full Neon connection URL to Render's `DB_POSTGRESDB_CONNECTION_URL` (example: `postgresql://USER:PASSWORD@ep-xxxxxx-pooler.c-1.region.aws.neon.tech/DBNAME?sslmode=require&channel_binding=require`).
   - If the Neon URL (or password) was ever committed to git history, rotate the Neon password/role immediately and update Render secrets. Use `docker run --rm postgres:17 psql "<NEON_URL>?sslmode=require&channel_binding=require" -c "SELECT version();"` to validate connectivity.
- macOS Docker + Ollama: use `OLLAMA_HOST=host.docker.internal:11434`.

Integration flow (high level):
- n8n connects to Postgres (DB_POSTGRESDB_CONNECTION_URL). n8n-import seeds database from `n8n/demo-data/`. Workflows may call Ollama/Qdrant via internal Docker network when run locally.

First tasks for an AI agent arriving here:
1. Open `docker-compose.yml` and `render.yaml` to read runtime envs and service profiles.
2. Inspect `n8n/demo-data/` and `scripts/import_n8n_data.py` to learn import conventions and filename patterns.
3. Run the local compose stack and tail `n8n` logs (`docker compose logs -f n8n`) to observe import/db errors.

If you want this trimmed further (deploy automation snippets, Render CLI usage, or import script examples), tell me which section to expand and I will iterate.
