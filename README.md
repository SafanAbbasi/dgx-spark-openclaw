# DGX Spark + OpenClaw Setup

A local-first AI assistant running on an NVIDIA DGX Spark (128GB unified memory) with OpenClaw, Ollama, and Telegram integration. Everything runs on-device — no cloud AI costs, full privacy.

## Hardware

- **NVIDIA DGX Spark** — GB10 GPU, 128GB unified LPDDR5x memory, ARM64 (aarch64)
- Memory bandwidth: ~273 GB/s
- Storage: 3.6TB NVMe

## Architecture

```
Telegram <--> OpenClaw Gateway <--> qwen3:32b (via Ollama)
                  |
                  +--> Cron Jobs (morning briefing, system monitor, evening verse)
                  +--> Skills & Tools (web search, exec, calendar, gmail)
                  +--> Shell Scripts (system stats, calendar, quran API)
```

## What's Installed

| Component | Version | Purpose |
|-----------|---------|---------|
| Ollama | 0.19.0 | Local LLM inference server |
| OpenClaw | 2026.3.31 | AI agent framework with Telegram integration |
| gog (gogcli) | 0.12.0 | Google Workspace CLI (Calendar, Gmail) |

## Models

| Model | Size | Speed | Use Case |
|-------|------|-------|----------|
| gpt-oss:120b | 65GB | ~42.7 tok/s | Primary model for OpenClaw (best quality + fast, MoE architecture) |
| qwen3:32b | 20GB | ~8.4 tok/s | Alternative model, good quality |
| llama3.1:8b | 4.9GB | ~38.8 tok/s | Fast responses, basic quality |
| llama3.1:70b | 42GB | ~4.1 tok/s | Available but too slow for interactive use |
| nomic-embed-text | 274MB | — | Embeddings |

> **Note:** gpt-oss:120b is surprisingly fast despite its size — likely a mixture-of-experts (MoE) model that only activates a fraction of its parameters per token. NVIDIA recommends it as the best model for the DGX Spark.

### Why These Speeds?

LLM token generation speed is bottlenecked by memory bandwidth:

```
tokens/sec ≈ memory bandwidth / model size
```

The DGX Spark's GB10 has ~273 GB/s (LPDDR5x) vs 3,350 GB/s on an H100 (HBM3). The tradeoff: the Spark can *run* models that won't fit on consumer GPUs (128GB unified memory), but at desktop speeds.

## Setup Steps

### 1. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:32b
ollama pull llama3.1:8b
ollama pull llama3.1:70b
ollama pull nomic-embed-text
```

Ollama runs as a systemd service on port 11434.

### 2. Install OpenClaw

```bash
npm install -g openclaw
openclaw onboard
```

### 3. Configure OpenClaw for Local Ollama

**Set the primary model** (`~/.openclaw/openclaw.json`):

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "ollama/qwen3:32b"
      }
    }
  },
  "tools": {
    "exec": {
      "security": "full"
    }
  }
}
```

**Create auth profile** (`~/.openclaw/agents/main/agent/auth-profiles.json`):

```json
{
  "profiles": {
    "ollama:default": {
      "type": "api_key",
      "provider": "ollama",
      "key": "ollama-local"
    }
  }
}
```

**Set env var** (`~/.openclaw/.env`):

```
OLLAMA_API_KEY=ollama-local
```

### 4. Telegram Bot Setup

1. Message @BotFather on Telegram, send `/newbot`
2. Choose a name and username (must end in `bot`)
3. Copy the bot token into `~/.openclaw/openclaw.json`:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "YOUR_BOT_TOKEN_HERE"
    }
  }
}
```

4. Message your bot on Telegram — it will give you a pairing code
5. Approve it: `openclaw pairing approve telegram <CODE>`

### 5. Install gog (Google Calendar/Gmail)

```bash
# Download ARM64 binary
curl -L "https://github.com/steipete/gogcli/releases/latest/download/gogcli_0.12.0_linux_arm64.tar.gz" -o /tmp/gogcli.tar.gz
tar xzf /tmp/gogcli.tar.gz -C /tmp/
mkdir -p ~/.local/bin
mv /tmp/gog ~/.local/bin/gog
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

**Google Cloud Setup (free):**

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project
3. Enable **Google Calendar API** and **Gmail API**
4. Create OAuth credentials (Desktop app)
5. Download the credentials JSON
6. Configure and login:

```bash
gog auth credentials ~/Downloads/client_secret_*.json
gog auth login
```

7. Add yourself as a test user in the OAuth consent screen if you get "Access blocked"

### 6. Install Hijri Date Converter

```bash
python3 -m venv ~/.local/hijri-venv
~/.local/hijri-venv/bin/pip install hijri-converter hijridate
```

## Cron Jobs

### Morning Briefing (7 AM daily)

Sends a Telegram message with:
- Date (Gregorian + Hijri)
- Houston weather (via DuckDuckGo search)
- DGX system stats (disk, memory, GPU temp)
- Today's calendar events (all Google Calendars)
- Tomorrow's calendar events
- Word of the day
- Thought of the day

```bash
openclaw cron add \
  --name "Morning Briefing" \
  --cron "0 7 * * *" \
  --tz "America/Chicago" \
  --session isolated \
  --message "..." \
  --announce \
  --channel telegram \
  --to "YOUR_TELEGRAM_CHAT_ID"
```

The briefing uses a shell script ([scripts/morning-stats.sh](scripts/morning-stats.sh)) to gather exact system stats and calendar data, preventing the LLM from hallucinating numbers.

### System Monitor (every 30 minutes)

Silent watchdog — only messages you on Telegram if something needs attention:
- Disk usage over 85%
- Available memory below 10GB
- GPU temperature over 80C
- Ollama not running
- Load average over 8

Responds with `HEARTBEAT_OK` (suppressed by OpenClaw) when everything is fine.

```bash
openclaw cron add \
  --name "System Monitor" \
  --every "30m" \
  --session isolated \
  --message "..." \
  --announce \
  --channel telegram \
  --to "YOUR_TELEGRAM_CHAT_ID"
```

### Evening Quran Verse (9 PM daily)

Sends a verified Quran verse via the [Al Quran Cloud API](https://alquran.cloud/api):
- Uthmani Arabic script
- Sahih International English translation
- Different verse each day

Uses [scripts/quran-verse.sh](scripts/quran-verse.sh) to fetch from the API.

```bash
openclaw cron add \
  --name "Evening Quran Verse" \
  --cron "0 21 * * *" \
  --tz "America/Chicago" \
  --session isolated \
  --message "..." \
  --announce \
  --channel telegram \
  --to "YOUR_TELEGRAM_CHAT_ID"
```

## Scripts

### `scripts/morning-stats.sh`

Gathers system stats and calendar data with exact numbers to prevent LLM hallucination. The qwen3:32b model tends to make up numbers when asked to run commands and report results, so this script pre-formats everything.

### `scripts/quran-verse.sh`

Fetches a daily Quran verse from the Al Quran Cloud API. Picks a different verse each day using a deterministic formula based on the day of the year.

## Lessons Learned

### LLM Hallucination with System Commands
The 32B model frequently fabricates numbers when asked to run system commands and report results (e.g., reporting 256GB RAM on a 128GB machine). Solution: use shell scripts to generate exact data and instruct the model to copy output verbatim.

### Model Speed vs Quality Tradeoff
On the GB10's ~273 GB/s memory bandwidth:
- 8B models: fast (~39 tok/s) but basic
- 32B models: usable (~8.4 tok/s) and good quality
- 70B models: too slow (~4.1 tok/s) for interactive chat

### Timezone Issues
The DGX Spark runs in UTC by default. Calendar events and scheduled tasks need explicit timezone handling (`TZ="America/Chicago"`, `--tz "America/Chicago"`, `gog --today` flag) to avoid showing events on the wrong day.

### Ollama Auth Profile Format
OpenClaw expects auth profiles in a specific format with `type`, `provider`, and `key` fields under a `profiles` object. The provider key must match the pattern `provider:identifier` (e.g., `ollama:default`).

## File Locations

| File | Purpose |
|------|---------|
| `~/.openclaw/openclaw.json` | Main OpenClaw config |
| `~/.openclaw/agents/main/agent/auth-profiles.json` | Model auth credentials |
| `~/.openclaw/agents/main/agent/models.json` | Model registry |
| `~/.openclaw/cron/jobs.json` | Cron job definitions |
| `~/.openclaw/scripts/morning-stats.sh` | Morning briefing data script |
| `~/.openclaw/scripts/quran-verse.sh` | Evening Quran verse script |
| `~/.openclaw/.env` | Environment variables for the gateway service |
| `~/.config/gogcli/config.json` | Google Workspace CLI config |
| `~/.local/hijri-venv/` | Python venv for Hijri date conversion |

## Services

```bash
# OpenClaw gateway (user-level systemd)
systemctl --user status openclaw-gateway
systemctl --user restart openclaw-gateway

# Ollama (system-level systemd)
systemctl status ollama
sudo systemctl restart ollama
```

## Useful Commands

```bash
# Check models and speed
ollama list
ollama ps
curl -s http://localhost:11434/api/generate -d '{"model":"qwen3:32b","prompt":"Hello","stream":false}' | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{d[\"eval_count\"]/(d[\"eval_duration\"]/1e9):.1f} tok/s')"

# OpenClaw
openclaw status
openclaw cron list
openclaw cron run <job-id>
openclaw sessions
openclaw models status
openclaw doctor

# Calendar
gog calendar list --today --all
gog calendar list --tomorrow --all

# System
free -h
nvidia-smi
df -h /
```
