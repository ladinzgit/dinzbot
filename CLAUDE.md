# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
poetry install

# Run the bot
python main.py
```

## Environment Variables

Required in a `.env` file (loaded via `python-dotenv`):
- `DISCORD_BOT_TOKEN` — Discord bot token
- `APPLICATION_ID` — Discord application ID
- `FACTCHAT_API_KEY` — FactChat API key (운세·챗봇 기능, base_url: `https://factchat-cloud.mindlogic.ai/v1/gateway`)
- `GUILD_IDS` — comma-separated guild IDs (e.g. `123,456`)

## Architecture

DinzBot is a Korean-language Discord bot built with discord.py using a **Cog-based modular architecture**.

**Entry point:** `main.py` initializes the bot, loads all cogs from `src/`, and provides a `*sync` command (owner-only) to register slash commands with Discord.

**Cog loading order matters:** `Scheduler` is loaded first because other cogs register tasks with it at startup.

### Core modules (`src/core/`)
- `birthday_db.py` — async SQLite, birthday data (`data/birthdays.db`)
- `fortune_db.py` — sync JSON, fortune data (`data/fortune_db.json`)
- `chatbot_db.py` — async SQLite, conversation history (`data/chatbot.db`, max 20 msgs/user)
- `admin_utils.py` — `GUILD_IDS`, `only_in_guild()`, `is_guild_admin()` decorators

### Feature cogs
| Cog | Responsibility |
|-----|---------------|
| `src/utils/Scheduler.py` | Central scheduler; runs every minute, executes daily/one-time tasks registered by other cogs |
| `src/birthday/Birthday.py` | Modal-based birthday registration, edit limit (max 2 per user) |
| `src/birthday/BirthdayInterface.py` | Live birthday list message in a channel; auto-updates at midnight via Scheduler |
| `src/fortune/FortuneCommand.py` | `*운세` — AI fortune (FactChat API), one per day per user |
| `src/fortune/FortuneConfig.py` | `*운세설정` admin — channel, role, send times, target users, buttons |
| `src/fortune/FortuneTimer.py` | Midnight task — decrements counts, syncs roles, scheduled mentions |
| `src/chatbot/Chatbot.py` | `*챗봇설정` admin — AI chatbot with per-user conversation memory |

### Data storage
- SQLite via `aiosqlite` (async) — birthday, chatbot
- JSON file — fortune config/data (`data/fortune_db.json`)
- `config/birthday_config.json` — per-guild birthday channel/message IDs
- `config/chatbot_config.json` — per-guild chatbot channel ID
- Timezone: `Asia/Seoul` (KST) — all scheduled tasks use this timezone

### AI API (운세·챗봇 공통)
- Provider: FactChat (MindLogic) — OpenAI-compatible gateway
- `base_url`: `https://factchat-cloud.mindlogic.ai/v1/gateway`
- Model: `gpt-5.2`
- Client: `AsyncOpenAI(api_key=FACTCHAT_API_KEY, base_url=BASE_URL)`

### Bot conventions
- Command prefix: `*` (e.g., `*운세`, `*sync`)
- Slash commands are also supported
- The bot has a rabbit character persona ("하묘") and ends sentences with "묘"
- All database calls are async
