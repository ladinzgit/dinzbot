"""
관리자 유틸리티: GUILD_IDS 및 권한 체크 데코레이터
.env의 GUILD_IDS 환경 변수에서 서버 ID 목록을 읽습니다. (쉼표 구분)
예: GUILD_IDS=123456789,987654321
"""

import os
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()


def _parse_guild_ids() -> list[int]:
    raw = os.environ.get("GUILD_IDS", "")
    ids = []
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            ids.append(int(item))
    return ids


GUILD_IDS: list[int] = _parse_guild_ids()


def only_in_guild():
    """서버(길드) 내에서만 명령을 사용할 수 있도록 하는 데코레이터"""
    async def predicate(ctx: commands.Context) -> bool:
        return ctx.guild is not None
    return commands.check(predicate)


def is_guild_admin():
    """서버 관리자 또는 봇 소유자만 명령을 사용할 수 있도록 하는 데코레이터"""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return False
        return (
            ctx.author.guild_permissions.administrator
            or await ctx.bot.is_owner(ctx.author)
        )
    return commands.check(predicate)
