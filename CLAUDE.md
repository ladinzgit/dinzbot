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
- `PINECONE_API_KEY` — Pinecone vector DB key (챗봇 장기 기억 기능)
- `GUILD_IDS` — comma-separated guild IDs (e.g. `123,456`)

## Architecture

DinzBot is a Korean-language Discord bot built with discord.py using a **Cog-based modular architecture**.

**Entry point:** `main.py` initializes the bot, loads all cogs from `src/`, and provides a `?!sync` command (owner-only) to register slash commands with Discord.

**Cog loading order matters:** `src/utils/` cogs (Logger, Scheduler) are loaded first; all other cogs load after.

### Core modules (`src/core/`)
- `birthday_db.py` — async SQLite, birthday data (`data/birthdays.db`)
- `fortune_db.py` — sync JSON, fortune data (`data/fortune_db.json`)
- `chatbot_db.py` — async SQLite, conversation history (`data/chatbot.db`, max 20 msgs/user); supports per-user (`SCOPE_USER`) and shared guild (`SCOPE_SHARED`) contexts
- `chatbot_memory.py` — Pinecone vector DB long-term memory; uses `multilingual-e5-large` embeddings, cosine similarity with time-decay scoring
- `admin_utils.py` — `GUILD_IDS`, `only_in_guild()`, `is_guild_admin()` decorators

### Feature cogs
| Cog | Responsibility |
|-----|---------------|
| `src/utils/Logger.py` | Sends embed log messages to a configured Discord channel; set via `?!로그채널설정` (owner-only) |
| `src/utils/Scheduler.py` | Central scheduler; runs every minute, executes daily/one-time tasks registered by other cogs |
| `src/birthday/Birthday.py` | Modal-based birthday registration, edit limit (max 2 per user) |
| `src/birthday/BirthdayInterface.py` | Live birthday list message in a channel; auto-updates at midnight via Scheduler |
| `src/fortune/FortuneCommand.py` | `?!운세` — AI fortune (FactChat API), one per day per user |
| `src/fortune/FortuneConfig.py` | `?!운세설정` admin — channel, role, send times, target users, buttons |
| `src/fortune/FortuneTimer.py` | Midnight task — decrements counts, syncs roles, scheduled mentions |
| `src/chatbot/Chatbot.py` | `?!챗봇설정` admin — AI chatbot with dual-scope memory (SQLite + Pinecone); `?!챗봇초기화` user command; `?!기억동기화설정` admin sync for Pinecone |
| `src/music/music.py` | 채널 고정형 단일 embed 플레이어; 명령어 없음 — 채널 텍스트 입력으로 검색·재생; Lavalink 서버 필요 (`localhost:2333`) |
| `src/music/MusicConfig.py` | `?!음악설정` 관리자 전용 — 음악 채널 지정·초기화·비활성화 (`config/music_config.json`) |

### Data storage
- SQLite via `aiosqlite` (async) — birthday, chatbot
- JSON file — fortune config/data (`data/fortune_db.json`)
- `config/birthday_config.json` — per-guild birthday channel/message IDs
- `config/chatbot_config.json` — per-guild chatbot channel ID
- `config/logger_config.json` — log channel ID for the Logger cog
- `config/music_config.json` — per-guild music command channel ID
- Timezone: `Asia/Seoul` (KST) — all scheduled tasks use this timezone

### AI API (운세·챗봇 공통)
- Provider: FactChat (MindLogic) — OpenAI-compatible gateway
- `base_url`: `https://factchat-cloud.mindlogic.ai/v1/gateway`
- Chatbot model: `gemini-3.1-pro-preview` (with `extra_body={"thinking_level": "low"}`)
- Client: `AsyncOpenAI(api_key=FACTCHAT_API_KEY, base_url=BASE_URL)`

### Chatbot persona & memory
- Chatbot character: "슈비 (Suubi)" — autonomous learning unit persona; responses use `(category), (content)` format (categories: 응답/의문/보고/경고/거부/확인/정정/침묵/감각)
- Intimacy levels: changes response style based on history length (<10, ≥10, ≥50 messages, or owner)
- Context window: last 16 messages or 10,000 chars, whichever is smaller
- Memory: user messages stored to Pinecone on send; top 3 relevant memories (score ≥ 0.75) injected into system prompt

### Bot conventions
- Command prefix: `?!` (e.g., `?!운세`, `?!sync`)
- Slash commands are also supported
- The bot has a rabbit character persona ("하묘") and ends sentences with "묘"
- All database calls are async
