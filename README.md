# Google-crypto-bot

## System Architecture

This project runs a three-layer agent system:

```
You (Telegram) ← → REPENT (Overseer Bot)
                         |
                    MetaClaw (Brain)
                         |
                    OpenClaw (Body)
```

### Agents

| Agent | Role | Description |
|-------|------|-------------|
| **REPENT** | Overseer | Telegram bot that gives you real-time control and visibility |
| **MetaClaw** | Brain | Monitors system state, makes decisions, commands OpenClaw |
| **OpenClaw** | Body | Executes trades and actions on the Jetson device |

---

## Telegram Status Integration

### How REPENT Reports Status

REPENT is your command-and-control interface via Telegram. It receives status updates from MetaClaw and relays them to you.

**Status flow:**
```
OpenClaw (executes) → MetaClaw (interprets) → REPENT → Telegram → You
```

### Bot Identity

- Your Telegram bot is identified by its **bot token**, not a name.
- You can rename the bot later via BotFather once it's fully operational.
- To check which bot is active: the token in your config is the source of truth.

### Setting Up Your Telegram Bot Token

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Run `/newbot` or retrieve an existing token with `/mybots`
3. Copy the token (format: `123456789:AABBCCddEEffGGhh...`)
4. Add it to your MetaClaw config (see below)

### MetaClaw Config Template

```yaml
telegram:
  bot_token: "YOUR_BOT_TOKEN_HERE"
  chat_id: "YOUR_CHAT_ID_HERE"
  status_interval_seconds: 60   # How often MetaClaw reports to you

metaclaw:
  poll_interval_seconds: 10     # How often MetaClaw polls OpenClaw

openclaw:
  api_endpoint: "http://localhost:8080"
  api_key: "YOUR_OPENCLAW_API_KEY"

repent:
  log_all_commands: true
  alert_on_failure: true
```

---

## Quarantine Protocol (Critical)

MetaClaw and OpenClaw do **not** talk to each other directly. This is intentional.

**Why quarantine matters:**
- OpenClaw cannot initiate anything to MetaClaw
- MetaClaw cannot be compromised by OpenClaw
- REPENT logs every command and response
- You can pause or kill either agent without cascading failure

**How MetaClaw controls OpenClaw without "talking":**
- MetaClaw **pulls** data from OpenClaw's API (one-way read)
- MetaClaw **pushes** commands to OpenClaw's API (one-way write)
- OpenClaw executes and reports back via API
- MetaClaw interprets results and decides the next action
- REPENT observes all of it

```
MetaClaw ──[API commands]──► OpenClaw
MetaClaw ◄─[API responses]── OpenClaw
MetaClaw ──[status reports]─► REPENT ──► Telegram ──► You
```

---

## Telegram Status Message Types

| Status | Meaning |
|--------|---------|
| `ONLINE` | Agent is running and responsive |
| `POLLING` | MetaClaw actively checking OpenClaw |
| `COMMAND_SENT` | MetaClaw issued a command to OpenClaw |
| `ERROR` | An agent has failed or is unreachable |
| `PAUSED` | Agent manually paused via Telegram command |
| `RESTARTED` | Agent came back up after being down |

### Checking Status via Telegram

Send these commands to your REPENT bot in Telegram:

| Command | Action |
|---------|--------|
| `/status` | Get current status of all agents |
| `/metaclaw` | MetaClaw-specific health report |
| `/openclaw` | OpenClaw-specific health report |
| `/pause metaclaw` | Pause MetaClaw |
| `/pause openclaw` | Pause OpenClaw |
| `/resume` | Resume paused agents |
| `/logs` | Get recent activity log |

---

## Troubleshooting: "It repaired yet?" / Up-and-Down Status

If you've been restarting agents and aren't sure if Telegram status is working:

1. **Check the bot token** — confirm the token in your config matches the one from BotFather
2. **Check the chat ID** — make sure REPENT is reporting to the correct Telegram chat
3. **Send `/status`** to your REPENT bot — if it responds, the Telegram link is alive
4. **Check MetaClaw logs** — look for `telegram: message sent` or errors connecting to the API
5. **Restart order matters** — always start REPENT first, then MetaClaw, then OpenClaw

If REPENT goes silent after a restart, it usually means:
- The bot token is correct but the process crashed (check logs)
- Network connectivity to Telegram API is down
- The chat ID changed (e.g., you messaged a different bot)

---

## Saved Configuration Reference

All architecture decisions are documented here:

- MetaClaw config template (above)
- REPENT routing architecture (above)
- Quarantine protocol (above)
- Telegram bot setup steps (above)
- API key management — never hardcode; use environment variables or a secrets file outside the repo

---

## Visual Dashboard (Planned)

A cartoon-style agent dashboard is planned to show each agent as a character in real-time — what they're working on, what commands are flowing, and the overall system health at a glance. Video reference to be integrated once located.
