# Telegram Approval Daemon Runbook

The CCA Telegram Approval Daemon (`scripts/telegram_approval_daemon.py`) is a
persistent background worker that listens for inline-keyboard callback queries
from a Telegram bot and records operator approve/reject decisions in the local
opportunity registry and the ApprovalGate Sheet.

The daemon loads its own environment through
`commission_crowd_agent.config.load_settings()`, reading from `.env` and
`/home/ubuntu/hermes-control/secrets/shared.env`. Do **not** put secrets in the
unit file or shell environment.

---

## Systemd service (recommended)

The unit file lives at
`scripts/systemd/cca-telegram-bot.service`. It runs as the `ubuntu` user, logs
to journald, and restarts automatically.

### Install, enable, and start

```bash
# Copy the unit file into place
sudo cp /home/ubuntu/workspace/Zero-Human-Corp/commission-crowd-agent/scripts/systemd/cca-telegram-bot.service \
        /etc/systemd/system/cca-telegram-bot.service

# Reload systemd
sudo systemctl daemon-reload

# Enable on boot and start now
sudo systemctl enable --now cca-telegram-bot
```

### Check status

```bash
sudo systemctl status cca-telegram-bot
```

### Restart or stop

```bash
sudo systemctl restart cca-telegram-bot
sudo systemctl stop cca-telegram-bot
```

### View logs

```bash
sudo journalctl -u cca-telegram-bot -f
```

Add `--since today` or `--since "1 hour ago"` to narrow the window:

```bash
sudo journalctl -u cca-telegram-bot --since today
```

---

## Tmux alternative (non-systemd nodes)

Use `scripts/tmux_orchestrate_daemon.sh` on hosts where systemd is not used.
The script is idempotent: it creates a session named `cca-telegram-bot` or kills
and recreates a stale one.

### Start the daemon

```bash
bash /home/ubuntu/workspace/Zero-Human-Corp/commission-crowd-agent/scripts/tmux_orchestrate_daemon.sh
```

The script prints the attach command, e.g.:

```
Attach with: tmux attach-session -t cca-telegram-bot
```

### Attach to the session

```bash
tmux attach-session -t cca-telegram-bot
```

Detach from inside tmux with `Ctrl-b` then `d`.

### Check logs

The tmux session redirects daemon output to:

```bash
tail -f /home/ubuntu/hermes-control/runtime/cca_telegram_daemon.log
```

### Restart or stop (tmux)

```bash
# Kill the session entirely
tmux kill-session -t cca-telegram-bot

# Re-run the orchestration script to restart
bash /home/ubuntu/workspace/Zero-Human-Corp/commission-crowd-agent/scripts/tmux_orchestrate_daemon.sh
```

---

## Security note

- Never paste `TELEGRAM_BOT_TOKEN`, Google credentials, or any other secrets
  into the systemd unit file or the tmux orchestration script.
- The daemon reads secrets from the configured env files itself. Keep
  `/home/ubuntu/hermes-control/secrets/shared.env` and the project's `.env`
  readable only by the `ubuntu` user (`chmod 600`).
- Verify that the runtime directory `/home/ubuntu/hermes-control/runtime` is
  writable by the `ubuntu` user so the daemon can persist its state registry and
  log file.

---

## Deployment metadata

- Primary service node Tailscale IPv4: `100.123.111.83`
- Project directory: `/home/ubuntu/workspace/Zero-Human-Corp/commission-crowd-agent`
- Runtime directory: `/home/ubuntu/hermes-control/runtime`
- Log file (tmux mode): `/home/ubuntu/hermes-control/runtime/cca_telegram_daemon.log`
- Robust launcher: `/home/ubuntu/workspace/Zero-Human-Corp/commission-crowd-agent/scripts/daemon_launcher.sh`
  (prefers `.venv/bin/python` when it exists, otherwise falls back to `python3`;
   systemd and tmux invoke it via `/bin/bash` because the project filesystem does not
   preserve executable bits)
