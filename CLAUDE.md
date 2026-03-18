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
- `OPENAI_API_KEY` — OpenAI API key for fortune generation

## Architecture

DinzBot is a Korean-language Discord bot built with discord.py using a **Cog-based modular architecture**.

**Entry point:** `main.py` initializes the bot, loads all cogs from `src/`, and provides a `*sync` command (owner-only) to register slash commands with Discord.

**Cog loading order matters:** `Scheduler` is loaded first because other cogs register tasks with it at startup.

### Core modules (in `src/core/`, not all present in repo)
- `birthday_db.py` — async SQLite operations for birthday data
- `fortune_db.py` — async SQLite operations for fortune data
- `admin_utils.py` — exports `GUILD_IDS`, `only_in_guild()`, `is_guild_admin()` decorators

### Feature cogs (`src/`)
| Cog | Responsibility |
|-----|---------------|
| `Scheduler.py` | Central scheduler; runs every minute, executes daily (hour/minute) and one-time (datetime) tasks registered by other cogs |
| `Birthday.py` | Modal-based birthday registration, slash commands, edit limit (max 2 per user) |
| `BirthdayInterface.py` | Maintains a live birthday list message in a channel; auto-updates at midnight |
| `FortuneCommand.py` | `*운세` command — ChatGPT fortune with eligibility check (one per day per user) |
| `FortuneConfig.py` | `*운세설정` admin command — configure fortune feature, roles, buttons |
| `FortuneTimer.py` | Midnight task — decrements user counts, syncs roles, sends scheduled mentions |

### Data storage
- SQLite via `aiosqlite` (async)
- `config/birthday_config.json` — per-guild birthday channel/message IDs
- Timezone: `Asia/Seoul` (KST) — all scheduled tasks use this timezone

### Bot conventions
- Command prefix: `*` (e.g., `*운세`, `*sync`)
- Slash commands are also supported
- The bot has a rabbit character persona ("하묘") and ends sentences with "묘"
- All database calls are async
