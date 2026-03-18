"""
생일 데이터베이스 모듈 (비동기, aiosqlite)
DB 파일: data/birthdays.db

테이블:
  birthdays         - 실제 생일 정보 (삭제 가능)
  user_edit_counts  - 수정 횟수 (삭제 후에도 유지)
"""

import aiosqlite
from datetime import datetime
from pathlib import Path

DB_PATH = "data/birthdays.db"


async def init_db():
    """테이블 초기화 (봇 시작 시 1회 호출)"""
    Path("data").mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS birthdays (
                user_id      TEXT PRIMARY KEY,
                year         INTEGER,
                month        INTEGER NOT NULL,
                day          INTEGER NOT NULL,
                registered_at TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_edit_counts (
                user_id    TEXT PRIMARY KEY,
                edit_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.commit()


async def get_birthday(user_id: str) -> dict | None:
    """유저의 생일 정보를 반환. 없으면 None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT b.user_id, b.year, b.month, b.day,
                      b.registered_at, b.updated_at,
                      COALESCE(ec.edit_count, 0) AS edit_count
               FROM   birthdays b
               LEFT JOIN user_edit_counts ec ON b.user_id = ec.user_id
               WHERE  b.user_id = ?""",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def register_birthday(user_id: str, year, month: int, day: int) -> bool:
    """생일 등록/수정. 성공 시 edit_count 1 증가. 실패 시 False."""
    now = datetime.now().isoformat()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_id FROM birthdays WHERE user_id = ?", (user_id,)
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                await db.execute(
                    "UPDATE birthdays SET year=?, month=?, day=?, updated_at=? WHERE user_id=?",
                    (year, month, day, now, user_id),
                )
            else:
                await db.execute(
                    "INSERT INTO birthdays (user_id, year, month, day, registered_at, updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (user_id, year, month, day, now, now),
                )

            # edit_count 증가 (없으면 1로 삽입)
            await db.execute(
                """INSERT INTO user_edit_counts (user_id, edit_count) VALUES (?, 1)
                   ON CONFLICT(user_id) DO UPDATE SET edit_count = edit_count + 1""",
                (user_id,),
            )
            await db.commit()
            return True
    except Exception:
        return False


async def delete_birthday(user_id: str) -> bool:
    """생일 정보 삭제. edit_count는 유지됨."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM birthdays WHERE user_id = ?", (user_id,))
            await db.commit()
            return True
    except Exception:
        return False


async def get_user_edit_count(user_id: str) -> int:
    """수정 횟수 반환 (생일 삭제 후에도 유지)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT edit_count FROM user_edit_counts WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def get_all_birthdays() -> list[dict]:
    """등록된 모든 생일 목록을 월/일 순으로 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, year, month, day FROM birthdays ORDER BY month, day"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def admin_update_birthday(user_id: str, year, month: int, day: int) -> bool:
    """관리자 강제 변경 — edit_count 변경 없음."""
    now = datetime.now().isoformat()
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_id FROM birthdays WHERE user_id = ?", (user_id,)
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                await db.execute(
                    "UPDATE birthdays SET year=?, month=?, day=?, updated_at=? WHERE user_id=?",
                    (year, month, day, now, user_id),
                )
            else:
                await db.execute(
                    "INSERT INTO birthdays (user_id, year, month, day, registered_at, updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (user_id, year, month, day, now, now),
                )
            await db.commit()
            return True
    except Exception:
        return False


async def reset_edit_count(user_id: str) -> bool:
    """수정 횟수를 0으로 초기화."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE user_edit_counts SET edit_count = 0 WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()
            return True
    except Exception:
        return False
