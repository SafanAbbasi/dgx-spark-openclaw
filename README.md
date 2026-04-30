# DGX Spark + OpenClaw Setup

A local-first AI assistant running on an NVIDIA DGX Spark (128GB unified memory) with OpenClaw, Ollama, and Telegram integration. Everything runs on-device — no cloud AI costs, full privacy.

## Hardware

- **NVIDIA DGX Spark** — GB10 GPU, 128GB unified LPDDR5x memory, ARM64 (aarch64)
- Memory bandwidth: ~273 GB/s
- Storage: 3.6TB NVMe

## Architecture

```
Telegram <--> OpenClaw Gateway <--> gpt-oss:120b (via Ollama)
                  |
                  +--> Cron Jobs:
                  |     • Morning Briefing (7 AM)
                  |     • System Monitor (every 30 min)
                  |     • Gmail Auth Check (8 AM)
                  |     • Gmail Triage (9 AM)
                  |     • Gmail Draft Watcher (every 15 min, 6 AM–midnight)
                  |     • Evening Quran Verse (9 PM)
                  |     • Telegram Cleanup Reminder (1st of month, 9 AM)
                  +--> Skills & Tools (web search, exec, calendar, gmail)
                  +--> Shell Scripts (system stats, calendar, quran, gmail triage,
                                      draft assistant, telegram cleanup)
```

## What's Installed

| Component | Version | Purpose |
|-----------|---------|---------|
| Ollama | 0.19.0 | Local LLM inference server |
| OpenClaw | 2026.3.31 | AI agent framework with Telegram integration |
| gog (gogcli) | 0.12.0 | Google Workspace CLI (Calendar, Gmail) |
| Telethon | 1.43.2 | MTProto userbot client (for Telegram chat cleanup) |
| hijri-converter / hijridate | latest | Gregorian → Hijri date conversion |

## Models

### Full Benchmark (DGX Spark GB10)

| Model | Size | Speed | Architecture | Use Case |
|-------|------|-------|-------------|----------|
| nemotron-3-nano:30b | 30GB | ~70.8 tok/s | Dense (NVIDIA) | Fastest option — good for speed-critical tasks |
| gpt-oss:20b | 13GB | ~54.9 tok/s | MoE (OpenAI) | Fast + lightweight |
| gpt-oss:120b | 65GB | ~39.8 tok/s | MoE (OpenAI) | **Primary model** — best quality + fast |
| llama3.1:8b | 4.9GB | ~38.8 tok/s | Dense (Meta) | Basic quality, small footprint |
| qwen3:32b | 20GB | ~9.4 tok/s | Dense (Alibaba) | Good quality but slower |
| llama3.1:70b | 42GB | ~4.5 tok/s | Dense (Meta) | Too slow for interactive use |
| nomic-embed-text | 274MB | — | — | Embeddings |

> **Primary model:** gpt-oss:120b is an [OpenAI open-source model](https://openai.com/index/introducing-gpt-oss/) (Apache 2.0) using a Mixture-of-Experts (MoE) architecture — 116.8B total parameters but only 5.1B active per token (128 experts, Top-4 routing). This is why it runs at 40 tok/s despite being 65GB on disk. It uses MXFP4 quantization for the MoE weights with BF16 for other layers. NVIDIA recommends it as the best model for the DGX Spark.
>
> **Fast fallback:** nemotron-3-nano:30b is NVIDIA's own model and the fastest on the Spark at 71 tok/s. Consider using it for speed-critical requests where response time matters more than depth.

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
ollama pull gpt-oss:120b      # primary
ollama pull nemotron-3-nano:30b  # fast fallback
ollama pull nomic-embed-text  # embeddings
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
        "primary": "ollama/gpt-oss:120b"
      },
      "timeoutSeconds": 300
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

### Gmail Triage (9 AM daily)

Sends a Telegram digest of the last 24 hours of inbox messages, classified into 5 buckets:
- 🔴 **Needs reply** — a human is waiting on your response
- 🟡 **Action** — pay/click/review/update, but no reply needed
- 🔵 **FYI** — interview times, order confirmations, personal notifications
- 🟢 **Newsletters** — sender names only
- ⚫ **Noise** — job alerts, promo, automated notifications

Read-only — never mutates Gmail. Pre-processing in [scripts/gmail-triage.py](scripts/gmail-triage.py) handles thread dedup, self-reply filtering, HTML-entity decoding, and merges related threads (e.g. calendar invite + scheduling chatter for the same meeting) into a single event before the LLM classifies them.

```bash
openclaw cron add \
  --name "Gmail Triage" \
  --cron "0 9 * * *" \
  --tz "America/Chicago" \
  --session isolated \
  --model "ollama/gpt-oss:120b" \
  --timeout-seconds 300 \
  --announce --channel telegram --to "YOUR_TELEGRAM_CHAT_ID" \
  --message "Run: bash ~/.openclaw/scripts/gmail-triage.sh ; classify each event into one of the 5 buckets ..."
```

Edit [scripts/gmail-triage.py](scripts/gmail-triage.py) and replace the `USER_EMAILS` / `USER_NAMES` constants with your own — these gate the self-reply filter.

### Gmail Draft Watcher (every 15 min, 6 AM–midnight)

Polls the inbox and creates a Gmail **draft** for any thread you've previously replied to. Never sends mail. Runs frequently so drafts are ready when you open Gmail.

Three-layer safety:
1. **Thread-history gate** ([gmail-draft-watcher.py](scripts/gmail-draft-watcher.py)) — only emits a candidate if the threadId appears in your last 30 days of `in:sent`. New senders are skipped.
2. **State-file dedup** — once a draft is created for a thread, it's not redrafted for 24 hours.
3. **Send-flag guard wrapper** ([gmail-draft-create.sh](scripts/gmail-draft-create.sh)) — the only path that can create a draft. Hardcodes `gog gmail drafts create` (no `send` subcommand exists in its arg list), refuses any flag matching `^--[a-zA-Z-]*send[a-zA-Z-]*`, and post-verifies that the result has the `DRAFT` label and *not* the `SENT` label before logging success.

```bash
openclaw cron add \
  --name "Gmail Draft Watcher" \
  --every "15m" \
  --session isolated \
  --no-deliver \
  --message "Run: bash ~/.openclaw/scripts/gmail-draft-watcher.sh ; for each candidate, draft a reply via ~/.openclaw/scripts/gmail-draft-create.sh ..."
```

`--no-deliver` keeps the cron silent on Telegram. The wrapper appends to `gmail-draft-log.tsv` for audit, and the watcher's `gmail-draft-state.json` (auto-pruned to 7-day TTL) provides dedup.

### Gmail Auth Check (8 AM daily)

Probes Gmail with a trivial API call to detect whether the OAuth refresh token is still valid. **Why this exists:** Google enforces a 7-day refresh-token expiry for OAuth apps using sensitive/restricted scopes (Gmail/Calendar) that haven't gone through formal app verification, even when the app is published "In production". You'll need to re-run `gog login` weekly. This cron makes that pain visible:

- **Healthy:** silent.
- **Day 6 of the 7-day window:** Telegram heads-up: "Gmail re-auth due tomorrow."
- **Auth expired:** urgent Telegram alert with the exact `gog login <email>` command to run.

The watcher and triage scripts also detect `invalid_grant` inside their `run_gog()` calls and pipe the alert through the same shared helper ([scripts/_auth_state.py](scripts/_auth_state.py)). Alerts are rate-limited to once per 6 hours so a 15-min cron doesn't spam during the gap between expiry and you running `gog login`.

State is tracked in `gmail-auth-state.json` (gitignored). Login transitions are auto-detected: when an API call succeeds after a known-broken state, the helper treats it as a fresh `gog login` and resets the 7-day clock — no manual bookkeeping required.

```bash
openclaw cron add \
  --name "Gmail Auth Check" \
  --cron "0 8 * * *" \
  --tz "America/Chicago" \
  --session isolated \
  --no-deliver \
  --timeout-seconds 90 \
  --message "Run: bash ~/.openclaw/scripts/gmail-auth-check.sh"
```

### Telegram Cleanup Reminder (1st of month, 9 AM)

Monthly nudge to clean up dead Telegram chats — empty stubs from the "Contact joined Telegram" auto-creation, and chats with deleted-account counterparties.

The cron just runs the read-only scan. Actual deletion is **manual** — you review the report, then run `tg-clean.sh --confirm` and type `DELETE` interactively. The cron pings Telegram only if there are candidates worth cleaning, and stays silent otherwise.

See [scripts/tg-cleanup/](scripts/tg-cleanup/) for the scripts and the setup steps below.

```bash
openclaw cron add \
  --name "Telegram Cleanup Reminder" \
  --cron "0 9 1 * *" \
  --tz "America/Chicago" \
  --session isolated \
  --no-deliver \
  --timeout-seconds 180 \
  --message "Run: bash ~/.openclaw/scripts/tg-cleanup/tg-cleanup-reminder.sh"
```

## Telegram Chat Cleanup Setup

The cleanup uses Telethon (MTProto userbot client) to scan and delete dead 1:1 chats. **Delete-for-me-only** — the other person sees nothing change.

What gets flagged:
- **stub-only** chats — every message is a `MessageActionContactSignUp` ("Contact joined Telegram") service stub.
- **deleted-account** chats — the counterparty's Telegram account is gone (Telethon `deleted=True`, or all of name+username+phone are empty).

What gets preserved: any chat with a real message, a phone-call log entry (`MessageActionPhoneCall`), or any other service event.

```bash
# 1. Get API credentials from https://my.telegram.org/auth (Tools > API Development Tools)

# 2. Create venv with Telethon
python3 -m venv ~/.openclaw/scripts/tg-cleanup-venv
~/.openclaw/scripts/tg-cleanup-venv/bin/pip install telethon

# 3. Copy the example config and fill in api_id / api_hash
cd ~/.openclaw/scripts/tg-cleanup
cp config.example.json config.json
# Edit config.json — set api_id (integer) and api_hash (string)

# 4. One-time interactive auth (asks for phone, SMS code, optional 2FA password)
VENV_PY=~/.openclaw/scripts/tg-cleanup-venv/bin/python3 bash tg-auth.sh

# 5. Dry-run scan — writes tg-scan-report.tsv with a 'reason' column
VENV_PY=~/.openclaw/scripts/tg-cleanup-venv/bin/python3 bash tg-scan.sh

# 6. Preview deletions
VENV_PY=~/.openclaw/scripts/tg-cleanup-venv/bin/python3 bash tg-clean.sh

# 7. Live deletions (interactive — type DELETE to confirm)
VENV_PY=~/.openclaw/scripts/tg-cleanup-venv/bin/python3 bash tg-clean.sh --confirm
```

To preserve specific chats unconditionally, copy `whitelist.txt.example` to `whitelist.txt` and add lower-cased names, `@usernames`, or `+E164` phone numbers (one per line). The whitelist file is gitignored.

## Scripts

### `scripts/morning-stats.sh`
Gathers system stats and calendar data with exact numbers to prevent LLM hallucination. Local models tend to fabricate numbers when asked to run commands and report results, so this script pre-formats everything.

### `scripts/word-of-day.sh`
Pulls the real Word of the Day from Merriam-Webster's RSS feed. Called from `morning-stats.sh`.

### `scripts/system-monitor.sh`
Watchdog driver for the System Monitor cron. Prints `HEARTBEAT_OK` (suppressed by OpenClaw) when healthy or an alert string otherwise.

### `scripts/quran-verse.sh`
Fetches a daily Quran verse from the Al Quran Cloud API. Picks a different verse each day using a deterministic formula based on the day of the year.

### `scripts/telegram-send.sh`
Send a Telegram message to your own chat from any other script (body via stdin, refuses empty messages). Used by `tg-cleanup-reminder.sh` and ad-hoc agent calls. Edit the `CHAT_ID` constant.

### `scripts/gmail-triage.sh` / `gmail-triage.py`
Read-only Gmail Inbox scan emitter for the Gmail Triage cron. Handles thread dedup, self-reply filtering, HTML decoding, and cross-thread merging by normalized subject. Edit `USER_EMAILS` / `USER_NAMES` in the .py.

### `scripts/gmail-draft-watcher.sh` / `gmail-draft-watcher.py`
Inbox watcher that emits draft candidates. Gates on thread-history (must have replied in last 30 days), state-file dedup (24-hour TTL per thread), and self-sent skip. Edit `USER_EMAILS` / `USER_NAMES` in the .py.

### `scripts/_auth_state.py`
Shared Gmail auth-health helpers used by triage, draft watcher, and auth check. Tracks last successful auth, last failure, last alert; auto-detects login transitions; rate-limits Telegram pings.

### `scripts/gmail-auth-check.sh` / `gmail-auth-check.py`
Daily probe + day-6 reminder. Pings Telegram only on (a) day 6 of the 7-day refresh window, or (b) actual `invalid_grant` failure.

### `scripts/gmail-draft-create.sh`
**The only path that creates Gmail drafts.** Hardcodes `gog gmail drafts create`, refuses suspicious flag names, post-verifies that the result has `DRAFT` label and not `SENT`, and updates the watcher's state file. The cron prompt must instruct the LLM to use only this wrapper for drafting.

### `scripts/tg-cleanup/`
Telegram chat cleanup using Telethon. See the [Telegram Chat Cleanup Setup](#telegram-chat-cleanup-setup) section above.
- `tg-auth.sh` / `tg-auth.py` — one-time interactive Telethon auth.
- `tg-scan.sh` / `tg-scan.py` — read-only scan; writes a `tg-scan-report.tsv` with reason column.
- `tg-clean.sh` / `tg-clean.py` — dry-run preview by default, deletes for-me-only with `--confirm`. FloodWait-aware.
- `tg-cleanup-reminder.sh` — monthly cron driver; runs the scan, pings Telegram only if there are candidates.
- `_common.py` — shared config / whitelist loaders.

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

### Agent Default Timeout Is Tight
`agents.defaults.timeoutSeconds` defaults to ~90s. That's enough for cheap models but too tight for `gpt-oss:120b` jobs that include ~25K input tokens and tool use (e.g. the morning briefing). Bump it globally to 300+ in `~/.openclaw/openclaw.json` and use `--timeout-seconds` per cron for the heavy ones. Restart the gateway after editing the global default (`systemctl --user restart openclaw-gateway`).

### Cold Model Loads Are 16 Seconds, Not Free
gpt-oss:120b is 65GB. NVMe at ~4 GB/s means a cold start reads for ~16 seconds before any inference begins, which can blow a tight per-job timeout. Watch `curl -s localhost:11434/api/ps` to see what's currently resident.

### BIDI / Invisible Characters Need Explicit `\u` Escapes
When stripping zero-width / bidi controls from email subjects, `re.compile("[​-‏...]")` works. Pasting the *literal* characters into a regex character class can silently make ASCII space land *inside* a range and break the regex with "bad character range" — even when the source file looks correct.

### Output Buffering When Piping Python to a Log
Long-running Python scripts piped to a file (`bash tg-clean.sh > out.log`) appear frozen because stdout is block-buffered when not a TTY. The actual progress is real but invisible. Either run with `python3 -u`, or write progress to an append-mode file directly (the cleanup log is append-mode TSV for this reason).

### Drafts Aren't `id`, They're `draftId`
`gog gmail drafts create` returns `{"draftId": "r123...", "message": {...}}`. The verification call needs to look at `draftId`, not `id`, or it'll silently fail and lose the draft handle. Test drafts left behind during this confusion are easy to miss — verify in the Gmail UI as well as the `drafts get` API call.

### OAuth Refresh Tokens Expire Every 7 Days
Google enforces a 7-day refresh-token expiry on OAuth apps using sensitive/restricted scopes (Gmail/Calendar) that haven't gone through verification — even apps in "Production" status. The 100-user cap on the OAuth consent screen is the giveaway: it shows up only when scopes are unapproved. There's no workaround short of formal app verification (manual review, often a paid security assessment for restricted scopes). Workspace service accounts with domain-wide delegation can't help either — they can only impersonate users *within* the same Workspace domain, not personal `@gmail.com` accounts. Practical mitigation: detect the failure fast and remind the user — that's what `gmail-auth-check.{sh,py}` and the shared `_auth_state.py` exist to do.

### Cron Self-Replication Is a Real Risk
An agent given exec/full security can call `openclaw cron add`. If a poorly-scoped cron prompt encourages "set up a follow-up", you can end up with thousands of duplicate jobs in `~/.openclaw/cron/jobs.json`. Audit `openclaw cron list | wc -l` periodically; a healthy setup has under 20 jobs. The repo's cron prompts use `--no-deliver` and explicit `EXEC RULES:` headers to keep the LLM on rails.

## File Locations

| File | Purpose |
|------|---------|
| `~/.openclaw/openclaw.json` | Main OpenClaw config |
| `~/.openclaw/agents/main/agent/auth-profiles.json` | Model auth credentials |
| `~/.openclaw/agents/main/agent/models.json` | Model registry |
| `~/.openclaw/cron/jobs.json` | Cron job definitions |
| `~/.openclaw/scripts/morning-stats.sh` | Morning briefing data script |
| `~/.openclaw/scripts/word-of-day.sh` | Word-of-the-day fetcher (called by morning-stats) |
| `~/.openclaw/scripts/system-monitor.sh` | System monitor watchdog |
| `~/.openclaw/scripts/quran-verse.sh` | Evening Quran verse script |
| `~/.openclaw/scripts/telegram-send.sh` | Send to own Telegram from any script (stdin body) |
| `~/.openclaw/scripts/gmail-triage.{sh,py}` | Daily inbox triage emitter |
| `~/.openclaw/scripts/gmail-draft-watcher.{sh,py}` | Draft-candidate watcher |
| `~/.openclaw/scripts/gmail-draft-create.sh` | Safety-wrapped draft creator |
| `~/.openclaw/scripts/gmail-draft-state.json` | Watcher dedup state (gitignored) |
| `~/.openclaw/scripts/gmail-draft-log.tsv` | Audit log of every draft created (gitignored) |
| `~/.openclaw/scripts/_auth_state.py` | Shared Gmail auth-health helpers |
| `~/.openclaw/scripts/gmail-auth-check.{sh,py}` | Daily auth probe + reminder |
| `~/.openclaw/scripts/gmail-auth-state.json` | Auth health state (gitignored) |
| `~/.openclaw/scripts/tg-cleanup/` | Telegram chat cleanup (Telethon) |
| `~/.openclaw/scripts/tg-cleanup/config.json` | Telethon api_id/api_hash (gitignored) |
| `~/.openclaw/scripts/tg-cleanup/tg.session` | Telethon auth tokens (gitignored) |
| `~/.openclaw/scripts/tg-cleanup-venv/` | Python venv with Telethon |
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

# Gmail
gog gmail messages search "in:inbox newer_than:1d" --json --results-only --all
bash ~/.openclaw/scripts/gmail-triage.sh
bash ~/.openclaw/scripts/gmail-draft-watcher.sh

# Telegram cleanup (require VENV_PY env var)
VENV_PY=~/.openclaw/scripts/tg-cleanup-venv/bin/python3 \
  bash ~/.openclaw/scripts/tg-cleanup/tg-scan.sh
VENV_PY=~/.openclaw/scripts/tg-cleanup-venv/bin/python3 \
  bash ~/.openclaw/scripts/tg-cleanup/tg-clean.sh           # dry-run
VENV_PY=~/.openclaw/scripts/tg-cleanup-venv/bin/python3 \
  bash ~/.openclaw/scripts/tg-cleanup/tg-clean.sh --confirm # live

# System
free -h
nvidia-smi
df -h /
```
