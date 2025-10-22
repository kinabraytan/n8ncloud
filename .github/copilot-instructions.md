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
- `--wait-ready` flag prevents importing to unhealthy services
- Export before major changes to avoid data loss

### Profile Selection
- Use specific profiles (`--profile cpu`) to avoid resource conflicts
- GPU profiles require proper Docker/driver setup (see Ollama Docker docs)
- Mac users cannot expose GPU to Docker containers

## Common Pitfalls

1. **Wrong Ollama Host**: Mac users must use `host.docker.internal:11434`
2. **Missing Encryption Key**: Service starts but credentials fail to decrypt
3. **Profile Mismatch**: Running without `--profile` may not start Ollama
4. **Import Timing**: Importing before service ready causes partial failures
5. **Credential Editing**: Manual ID changes cause duplicate workflows
6. **Data Not Loading**: If `credentials1.json` and `workflows1.json` don't load:
   - Verify files are properly formatted JSON arrays (not objects)
   - Check n8n-import container logs: `docker compose logs n8n-import`
   - Ensure import container completes successfully before main n8n starts
   - Files in `n8n/demo-data/` must use correct naming: `{id}-{name}.json`
   - Run manual import: `python scripts/import_n8n_data.py --dry-run` to validate

## Extension Points

- Add new AI services via additional Docker services in `networks: ['demo']`
- Extend `n8n/demo-data/` with new workflow templates
- Customize Ollama models by modifying pull commands in init containers
- Add volume mounts for additional shared data access patterns

## Production Stability Setup

### Automated Maintenance
1. **Health Monitoring**: Create workflows that monitor service health and restart if needed
2. **Backup Automation**: Schedule regular exports using GitHub Actions
3. **Update Notifications**: Monitor for n8n updates and test in staging first

### Render Optimization
1. **Environment Variables**: Set all required vars in Render dashboard:
   ```
   N8N_BASIC_AUTH_ACTIVE=true
   N8N_BASIC_AUTH_USER=your-email
   N8N_BASIC_AUTH_PASSWORD=your-password
   N8N_ENCRYPTION_KEY=your-32-char-hex-key
   N8N_USER_MANAGEMENT_JWT_SECRET=your-secret
   WEBHOOK_URL=https://your-n8n.onrender.com
   TRUST_PROXY=true
   N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true
   ```
2. **Auto-scaling**: Free tier limitations - consider upgrading for production use
3. **Database Persistence**: Render PostgreSQL free tier persists data automatically

### Data Import Troubleshooting
- **Array Format**: Ensure JSON files contain arrays of objects, not single objects
- **ID Consistency**: Don't manually edit `id` fields in JSON files
- **Import Verification**: Always run with `--dry-run` first
- **Workflow Files**: If workflows are in an array file (e.g., `workflows1.json`), split them into individual files named `{id}-{slugified-name}.json` using the provided `scripts/split_workflows.py` script
- **Manual Blueprint**: Add data import as manual step in render.yaml if needed:
  ```yaml
  buildCommand: python scripts/import_n8n_data.py --wait-ready 120
  ```