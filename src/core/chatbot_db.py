"""
챗봇 대화 기록 모듈 (비동기, aiosqlite)
DB 파일: data/chatbot.db

유저별로 최근 MAX_HISTORY개의 메시지를 보존하고 오래된 기록은 자동 삭제합니다.
"""

import aiosqlite
from datetime import datetime
from pathlib import Path

DB_PATH = "data/chatbot.db"
MAX_HISTORY = 20  # 유저당 보관할 최대 메시지 수 (user + assistant 합산)
MAX_SHARED_HISTORY = 60  # 길드 공용 맥락 보관 개수

SCOPE_USER = "user"
SCOPE_SHARED = "shared"


async def init_db():
    """테이블 초기화 (봇 시작 시 1회 호출)"""
    Path("data").mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   TEXT NOT NULL,
                user_id    TEXT NOT NULL,
                scope      TEXT NOT NULL DEFAULT 'user',
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        # 기존 DB를 위한 안전한 마이그레이션
        async with db.execute("PRAGMA table_info(conversations)") as cursor:
            columns = await cursor.fetchall()
            column_names = {row[1] for row in columns}

        if "scope" not in column_names:
            await db.execute(
                "ALTER TABLE conversations ADD COLUMN scope TEXT NOT NULL DEFAULT 'user'"
            )

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_guild_user
            ON conversations (guild_id, user_id, created_at)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_guild_scope
            ON conversations (guild_id, scope, created_at)
        """)
        await db.commit()


async def add_message(guild_id, user_id, role: str, content: str, scope: str = SCOPE_USER):
    """메시지를 저장하고 MAX_HISTORY 초과분을 정리합니다."""
    if scope not in (SCOPE_USER, SCOPE_SHARED):
        raise ValueError(f"지원하지 않는 scope입니다: {scope}")

    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (guild_id, user_id, scope, role, content, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (str(guild_id), str(user_id), scope, role, content, now),
        )

        if scope == SCOPE_USER:
            # 사용자 개인 기록은 유저 단위로 정리
            await db.execute(
                """DELETE FROM conversations
                   WHERE id IN (
                       SELECT id FROM conversations
                       WHERE guild_id = ? AND user_id = ? AND scope = ?
                       ORDER BY created_at DESC
                       LIMIT -1 OFFSET ?
                   )""",
                (str(guild_id), str(user_id), SCOPE_USER, MAX_HISTORY),
            )
        else:
            # 공용 기록은 길드 단위로 정리
            await db.execute(
                """DELETE FROM conversations
                   WHERE id IN (
                       SELECT id FROM conversations
                       WHERE guild_id = ? AND scope = ?
                       ORDER BY created_at DESC
                       LIMIT -1 OFFSET ?
                   )""",
                (str(guild_id), SCOPE_SHARED, MAX_SHARED_HISTORY),
            )

        await db.commit()


async def get_history(guild_id, user_id) -> list[dict]:
    """유저의 최근 대화 기록을 오래된 순으로 반환합니다."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT role, content FROM (
                   SELECT role, content, created_at
                   FROM conversations
                   WHERE guild_id = ? AND user_id = ? AND scope = ?
                   ORDER BY created_at DESC
                   LIMIT ?
               ) ORDER BY created_at ASC""",
            (str(guild_id), str(user_id), SCOPE_USER, MAX_HISTORY),
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in rows]


async def get_context_history(guild_id, user_id) -> list[dict]:
    """개인 기록 + 길드 공용 기록을 시간순으로 합쳐 반환합니다."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            WITH user_part AS (
                SELECT role, content, created_at
                FROM conversations
                WHERE guild_id = ? AND user_id = ? AND scope = ?
                ORDER BY created_at DESC
                LIMIT ?
            ),
            shared_part AS (
                SELECT role, content, created_at
                FROM conversations
                WHERE guild_id = ? AND scope = ?
                ORDER BY created_at DESC
                LIMIT ?
            )
            SELECT role, content
            FROM (
                SELECT role, content, created_at FROM user_part
                UNION ALL
                SELECT role, content, created_at FROM shared_part
            )
            ORDER BY created_at ASC
            """,
            (
                str(guild_id),
                str(user_id),
                SCOPE_USER,
                MAX_HISTORY,
                str(guild_id),
                SCOPE_SHARED,
                MAX_SHARED_HISTORY,
            ),
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in rows]


async def clear_history(guild_id, user_id=None):
    """대화 기록 초기화. user_id를 지정하지 않으면 길드 전체를 초기화합니다."""
    async with aiosqlite.connect(DB_PATH) as db:
        if user_id is not None:
            await db.execute(
                "DELETE FROM conversations WHERE guild_id = ? AND user_id = ? AND scope = ?",
                (str(guild_id), str(user_id), SCOPE_USER),
            )
        else:
            await db.execute(
                "DELETE FROM conversations WHERE guild_id = ?",
                (str(guild_id),),
            )
        await db.commit()
