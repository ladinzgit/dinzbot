"""
운세 설정 Cog (관리자 전용)
*운세설정 채널 [#채널] : 운세 명령어를 사용할 채널을 지정합니다.
"""

import discord
from discord.ext import commands

from src.core import fortune_db
from src.core.admin_utils import is_guild_admin


class FortuneConfig(commands.Cog):
    """운세 채널 설정용 Cog"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        print(f"✅ {self.__class__.__name__} loaded successfully!")

    async def log(self, message: str):
        try:
            logger = self.bot.get_cog("Logger")
            if logger:
                await logger.log(message, title="🍀 운세 시스템 로그", color=discord.Color.green())
        except Exception as e:
            print(f"❌ {self.__class__.__name__} 로그 전송 오류 발생: {e}")

    @commands.group(name="운세설정", invoke_without_command=True)
    @is_guild_admin()
    async def fortune_settings(self, ctx):
        """운세 설정 현황 및 도움말"""
        config = fortune_db.get_guild_config(ctx.guild.id)
        channel_id = config.get("channel_id")
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        channel_text = channel.mention if channel else "미설정 (모든 채널에서 사용 가능)"

        embed = discord.Embed(
            title="🍀 운세 설정",
            colour=discord.Colour.from_rgb(151, 214, 181)
        )
        embed.add_field(
            name="관리자 명령어",
            value=(
                "`*운세설정 채널 [#채널]` : 운세 사용 채널 지정 (미입력 시 현재 채널)\n"
                "`*운세설정 채널해제` : 채널 제한 해제 (모든 채널에서 사용 가능)\n"
                "`*운세설정 초기화 [@유저]` : 하루 1회 제한 초기화 (미지정 시 서버 전체)\n"
            ),
            inline=False
        )
        embed.add_field(
            name="현재 설정",
            value=f"- 운세 채널: {channel_text}",
            inline=False
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)

    @fortune_settings.command(name="채널")
    @is_guild_admin()
    async def set_channel(self, ctx, channel: discord.TextChannel = None):
        """운세 사용 채널 지정 (미입력 시 현재 채널)"""
        target = channel or ctx.channel
        fortune_db.set_channel_id(ctx.guild.id, target.id)

        embed = discord.Embed(
            title="🍀 운세 채널 설정 완료",
            description=f"{target.mention}에서만 `*운세` 명령어를 사용할 수 있습니다.",
            colour=discord.Colour.from_rgb(151, 214, 181)
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)
        await self.log(f"{ctx.author}({ctx.author.id})가 운세 채널을 {target.name}({target.id})로 설정함 [길드: {ctx.guild.name}({ctx.guild.id})]")

    @fortune_settings.command(name="채널해제")
    @is_guild_admin()
    async def unset_channel(self, ctx):
        """운세 채널 제한 해제"""
        fortune_db.set_channel_id(ctx.guild.id, None)

        embed = discord.Embed(
            title="🍀 운세 채널 해제",
            description="채널 제한을 해제했습니다. 이제 모든 채널에서 `*운세`를 사용할 수 있습니다.",
            colour=discord.Colour.from_rgb(151, 214, 181)
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)
        await self.log(f"{ctx.author}({ctx.author.id})가 운세 채널을 해제함 [길드: {ctx.guild.name}({ctx.guild.id})]")

    @fortune_settings.command(name="초기화")
    @is_guild_admin()
    async def reset_daily(self, ctx, member: discord.Member = None):
        """하루 1회 운세 사용 제한 초기화 (미지정 시 서버 전체)"""
        if member:
            fortune_db.set_user_last_used(ctx.guild.id, member.id, None)
            target_text = f"{member.mention}의"
            log_target = f"{member}({member.id})"
        else:
            # daily_usage 전체 초기화
            import json
            from pathlib import Path
            db_path = Path("data/fortune_db.json")
            if db_path.exists():
                with open(db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                guild_key = str(ctx.guild.id)
                if guild_key in data:
                    data[guild_key]["daily_usage"] = {}
                with open(db_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            target_text = "서버 전체"
            log_target = "서버 전체"

        embed = discord.Embed(
            title="🍀 운세 사용 제한 초기화",
            description=f"{target_text} 하루 1회 제한을 초기화했습니다. 오늘 다시 사용할 수 있습니다.",
            colour=discord.Colour.from_rgb(151, 214, 181)
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)
        await self.log(f"{ctx.author}({ctx.author.id})가 {log_target} 운세 일일 제한 초기화 [길드: {ctx.guild.name}({ctx.guild.id})]")


async def setup(bot):
    await bot.add_cog(FortuneConfig(bot))
