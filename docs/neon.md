# Neon DB (recommended) — setup & Render steps

This project prefers Neon (https://neon.tech) as the production Postgres provider. This short doc shows the minimal, safe steps to configure Neon for `n8n` on Render and how to validate and rotate credentials.

1) Create or obtain your Neon connection string
- In the Neon dashboard, create a database or role and copy the full connection string. It must include SSL settings for Render. Example (replace values):

  postgresql://USER:PASSWORD@ep-xxxxxx-pooler.c-1.region.aws.neon.tech/DBNAME?sslmode=require&channel_binding=require

2) Configure Render (Dashboard)
- Go to your Render service > Environment > Environment Variables (or service settings).
- Add a secret environment variable named `DB_POSTGRESDB_CONNECTION_URL` and paste the full Neon connection string (no surrounding quotes).
- Ensure `DB_TYPE` is `postgresdb` (this is typically in `render.yaml`).
- Set `DB_POSTGRESDB_SSL=true` if present in the manifest.
- Save and trigger a deploy (or click "Manual Deploy").

Why a full URL? n8n and Render handle connection strings reliably when SSL params are present in the URL. Missing `sslmode=require&channel_binding=require` is a common cause of "connection is insecure" or TLS failures.

3) Validate connectivity (local quick test)
- From any machine with Docker available you can quickly test the Neon URL with the official postgres client container:

```powershell
# PowerShell / pwsh example (replace <NEON_URL> with the full connection string)
docker run --rm postgres:17 psql "<NEON_URL>?sslmode=require&channel_binding=require" -c "SELECT version();"
```

If that returns a PostgreSQL version, the URL and auth are valid.

4) Common Render deploy failures and what they mean
- `ENOTFOUND` / `getaddrinfo` — the hostname in Render is incorrect (copying a host with an extra char or leaving a placeholder). Fix by re-pasting the full Neon URL in Render.
- `ECONNREFUSED ::1:5432` — Render attempted to connect to localhost; double-check you didn't set host to `localhost` or left `DB_POSTGRESDB_CONNECTION_URL` blank.
- `connection is insecure` or TLS errors — missing `sslmode=require&channel_binding=require` in the connection string.

5) Rotating Neon credentials (if leaked)
- If the Neon role/password was ever committed to git history or otherwise exposed, rotate immediately:
  - Preferred: In the Neon dashboard, create a new role with a strong password and update `DB_POSTGRESDB_CONNECTION_URL` in Render to use the new credentials.
  - Alternative: In Neon, rotate the existing role's password (if supported) and update Render.
- After updating the secret in Render, redeploy the service.
- Validate with the same `docker run postgres:17 psql ...` command above.

6) Automation options
- Render UI: easiest for one-off updates.
- CLI/API: you can use the Render CLI or Render API to programmatically set environment variables; the repository includes `scripts/install_render_cli.ps1` to install the Render CLI on Windows. After installing, refer to Render docs or `render --help` for the exact commands to update service envs.

7) Safety checklist before a deploy
- `N8N_ENCRYPTION_KEY` is present and unchanged (credentials will be unreadable if key changes).
- `DB_POSTGRESDB_CONNECTION_URL` contains `sslmode=require&channel_binding=require`.
- `DB_TYPE=postgresdb` is set.
- If you changed connection credentials, run the `psql` test above before deploying.

If you'd like, I can:
- Generate a PowerShell script (template) that uses the Render API to atomically update `DB_POSTGRESDB_CONNECTION_URL` given a Render API key and service ID.
- Or create a GitHub Action that validates the Neon connection string before pushing it to Render (safe pattern: do not commit secrets; pass via secrets).

