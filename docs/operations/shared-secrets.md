# Shared Secrets — Operator Runbook

## Where secrets live

On the OCI server, secrets are stored **outside** any Git repository to prevent accidental commits:

```
/home/ubuntu/hermes-control/secrets/shared.env
```

This path is the default for `commission-crowd-agent`. The project reads it automatically; no repo-local `.env` is required on OCI.

## How the project loads secrets

1. **Environment variables** take highest precedence (`os.environ`).
2. **Shared env file** is read from `/home/ubuntu/hermes-control/secrets/shared.env` (or override via `COMMISSION_CROWD_SHARED_ENV_PATH`).
3. **Pydantic defaults** apply when a value is absent from both sources.

Empty strings in the shared file are treated as "not set" and do not override Pydantic defaults.

## Adding or rotating a secret

1. SSH into OCI from your MacBook:
   ```bash
   ssh oci
   ```
2. Edit the shared env file:
   ```bash
   nano /home/ubuntu/hermes-control/secrets/shared.env
   ```
3. Restart `hermes-gateway` if the secret is used by Hermes itself:
   ```bash
   sudo systemctl restart hermes-gateway
   ```
4. Verify with the project's preflight command:
   ```bash
   cd /home/ubuntu/projects/commission-crowd-agent
   source .venv/bin/activate
   python -m commission_crowd_agent.cli preflight
   ```

## What must NOT be done

- ❌ Do **not** create a real `.env` inside the repo and commit it.
- ❌ Do **not** paste secret values into Telegram chat or Git commit messages.
- ❌ Do **not** copy the shared env file into any other repo.
- ❌ Do **not** set `git add .` or `git add -A` anywhere near the repo.

## Running locally (not on OCI)

If you clone the repo to a local machine, copy `.env.example` to `.env` and populate values manually. The `.env` file is gitignored and should never be committed.

```bash
cp .env.example .env
# Fill in values
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Telegram token: ❌ not configured` | Token missing from shared.env | Add `TELEGRAM_BOT_TOKEN=...` to shared.env |
| `Shared env file: ⚠️ missing` | File does not exist at default path | Ensure file exists, or set `COMMISSION_CROWD_SHARED_ENV_PATH` |
| `MissingEnvFileError` in tests | Test environment has no fake env | Tests use temporary files — this should not happen in normal runs |
