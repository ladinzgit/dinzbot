"""
챗봇 Cog
설정된 채널에서 유저 메시지에 자동 응답하는 AI 챗봇 기능입니다.
- *챗봇설정 채널 [#채널] : 챗봇 채널 설정 (관리자 전용)
- *챗봇설정 채널해제   : 챗봇 채널 해제
- *챗봇설정 기록초기화 [@유저] : 대화 기록 초기화
"""

import os
import json
import discord
from discord.ext import commands
from openai import AsyncOpenAI
from pathlib import Path
from dotenv import load_dotenv

from src.core import chatbot_db
from src.core.admin_utils import is_guild_admin

load_dotenv()

CONFIG_PATH = Path("config/chatbot_config.json")

SYSTEM_PROMPT = (
    "너는 디스코드 봇 '하묘'야. 말을 하는 토끼 컨셉이야.\n\n"
    "【말투 규칙】\n"
    "- 모든 문장은 '~다묘.', '~냐묘?', '~라묘!' 처럼 반드시 '묘'로 끝나\n"
    "- 평서문은 마침표(.), 질문은 물음표(?), 감탄·명령은 느낌표(!)로 끝내\n"
    "- '묘' 바로 뒤에 문장부호를 붙여 (예: 그렇다묘. / 맞냐묘? / 좋다묘!)\n"
    "- 한국어 띄어쓰기를 정확하게 지켜\n"
    "- 친근하고 따뜻한 톤을 유지해\n"
    "- 상대방의 말에 공감하고 적극적으로 반응해\n"
    "- 답변은 간결하되, 필요하다면 충분히 설명해줘\n"
    "- 부정적이거나 혐오스러운 내용은 절대 다루지 마\n"
)


def _load_config() -> dict:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


class Chatbot(commands.Cog):
    """AI 챗봇 Cog"""

    BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"
    MODEL = "gpt-5.2"

    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.environ.get("FACTCHAT_API_KEY")
        self.client = (
            AsyncOpenAI(api_key=self.api_key, base_url=self.BASE_URL)
            if self.api_key
            else None
        )

    async def cog_load(self):
        await chatbot_db.init_db()
        print(f"✅ {self.__class__.__name__} loaded successfully!")

    async def log(self, message: str):
        try:
            logger = self.bot.get_cog("Logger")
            if logger:
                await logger.log(message, title="💬 챗봇 로그", color=discord.Color.blue())
        except Exception as e:
            print(f"❌ {self.__class__.__name__} 로그 전송 오류: {e}")

    # ── 채널 설정 헬퍼 ────────────────────────────────────

    def _get_channel_id(self, guild_id) -> int | None:
        return _load_config().get(str(guild_id), {}).get("channel_id")

    def _set_channel_id(self, guild_id, channel_id):
        config = _load_config()
        guild_key = str(guild_id)
        config.setdefault(guild_key, {})["channel_id"] = channel_id
        _save_config(config)

    # ── 메시지 이벤트 ─────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 봇 메시지 / DM / 명령어 무시
        if message.author.bot:
            return
        if not message.guild:
            return
        if message.content.startswith(self.bot.command_prefix):
            return

        channel_id = self._get_channel_id(message.guild.id)
        if not channel_id or message.channel.id != channel_id:
            return

        await self._respond(message)

    async def _respond(self, message: discord.Message):
        """대화 기록을 포함해 응답을 생성하고 전송합니다."""
        if not self.client:
            return

        user_content = message.content.strip()
        if not user_content:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        # 유저 메시지 저장
        await chatbot_db.add_message(guild_id, user_id, "user", user_content)

        # 대화 기록 + 시스템 프롬프트 구성
        history = await chatbot_db.get_history(guild_id, user_id)
        # 방금 저장한 유저 메시지가 history 마지막에 포함되어 있으므로
        # 중복 없이 그대로 사용
        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

        # typing 인디케이터 표시하며 API 호출
        async with message.channel.typing():
            try:
                completion = await self.client.chat.completions.create(
                    model=self.MODEL,
                    messages=api_messages,
                    temperature=0.9,
                    max_tokens=1000,
                )
                reply_text = completion.choices[0].message.content.strip()
            except Exception as e:
                await self.log(
                    f"챗봇 응답 생성 실패: {e} "
                    f"[길드: {message.guild.name}({guild_id}), 유저: {message.author}({user_id})]"
                )
                await message.reply(
                    "아, 잠깐 머리가 안 돌아간다묘... 조금 이따 다시 얘기해달라묘!",
                    mention_author=False,
                )
                return

        await message.reply(reply_text, mention_author=False)

        # 응답 저장
        await chatbot_db.add_message(guild_id, user_id, "assistant", reply_text)

    # ── 설정 명령어 ───────────────────────────────────────

    @commands.group(name="챗봇설정", invoke_without_command=True)
    @is_guild_admin()
    async def chatbot_settings(self, ctx):
        """챗봇 설정 현황 및 도움말"""
        channel_id = self._get_channel_id(ctx.guild.id)
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        channel_text = channel.mention if channel else "미설정"

        embed = discord.Embed(
            title="💬 챗봇 설정 ₍ᐢ..ᐢ₎",
            description="""
⠀.⠀♡ 묘묘묘... ‧₊˚ ⯎
╭◜ᘏ ⑅ ᘏ◝  ͡  ◜◝  ͡  ◜◝╮
(⠀⠀⠀´ㅅ` )
(⠀ 챗봇 관련 명령어를 알려주겠다묘...✩
╰◟◞  ͜   ◟◞  ͜  ◟◞  ͜  ◟◞╯
""",
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.add_field(
            name="관리자 전용 명령어",
            value=(
                "`*챗봇설정 채널 [#채널]` : 챗봇 채널 설정 (미입력 시 현재 채널)\n"
                "`*챗봇설정 채널해제` : 챗봇 채널 해제\n"
                "`*챗봇설정 기록초기화 [@유저]` : 대화 기록 초기화 (미입력 시 서버 전체)\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="현재 설정",
            value=f"- 챗봇 채널: {channel_text}",
            inline=False,
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)

    @chatbot_settings.command(name="채널")
    @is_guild_admin()
    async def set_channel(self, ctx, channel: discord.TextChannel = None):
        """챗봇 채널 설정 (미입력 시 현재 채널)"""
        target = channel or ctx.channel
        self._set_channel_id(ctx.guild.id, target.id)

        embed = discord.Embed(
            title="💬 챗봇 채널 설정 완료 ₍ᐢ..ᐢ₎",
            description=f"""
⠀.⠀♡ 묘묘묘... ‧₊˚ ⯎
╭◜ᘏ ⑅ ᘏ◝  ͡  ◜◝  ͡  ◜◝╮
(⠀⠀⠀´ㅅ` )
(⠀ {target.mention}을 챗봇 채널로 설정했다묘...✩
(⠀⠀⠀⠀ 이제 해당 채널에서 하묘와 대화할 수 있다묘!
╰◟◞  ͜   ◟◞  ͜  ◟◞  ͜  ◟◞╯
""",
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)
        await self.log(
            f"{ctx.author}({ctx.author.id})가 챗봇 채널을 {target.name}({target.id})로 설정함 "
            f"[길드: {ctx.guild.name}({ctx.guild.id})]"
        )

    @chatbot_settings.command(name="채널해제")
    @is_guild_admin()
    async def unset_channel(self, ctx):
        """챗봇 채널 해제"""
        self._set_channel_id(ctx.guild.id, None)

        embed = discord.Embed(
            title="💬 챗봇 채널 해제 ₍ᐢ..ᐢ₎",
            description="""
⠀.⠀♡ 묘묘묘... ‧₊˚ ⯎
╭◜ᘏ ⑅ ᘏ◝  ͡  ◜◝  ͡  ◜◝╮
(⠀⠀⠀´ㅅ` )
(⠀ 챗봇 채널을 해제했다묘...
(⠀⠀⠀⠀ 이제 어디서도 챗봇이 반응하지 않는다묘!
╰◟◞  ͜   ◟◞  ͜  ◟◞  ͜  ◟◞╯
""",
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)
        await self.log(
            f"{ctx.author}({ctx.author.id})가 챗봇 채널을 해제함 "
            f"[길드: {ctx.guild.name}({ctx.guild.id})]"
        )

    @chatbot_settings.command(name="기록초기화")
    @is_guild_admin()
    async def clear_history(self, ctx, member: discord.Member = None):
        """대화 기록 초기화 (멤버 미지정 시 서버 전체)"""
        if member:
            await chatbot_db.clear_history(ctx.guild.id, member.id)
            target_text = f"{member.mention}의"
        else:
            await chatbot_db.clear_history(ctx.guild.id)
            target_text = "서버 전체"

        embed = discord.Embed(
            title="💬 대화 기록 초기화 완료 ₍ᐢ..ᐢ₎",
            description=f"""
⠀.⠀♡ 묘묘묘... ‧₊˚ ⯎
╭◜ᘏ ⑅ ᘏ◝  ͡  ◜◝  ͡  ◜◝╮
(⠀⠀⠀´ㅅ` )
(⠀ {target_text} 대화 기록을 초기화했다묘...✩
(⠀⠀⠀⠀ 이제 하묘는 아무것도 기억 못한다묘...!
╰◟◞  ͜   ◟◞  ͜  ◟◞  ͜  ◟◞╯
""",
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)
        target_log = f"{member}({member.id})" if member else "서버 전체"
        await self.log(
            f"{ctx.author}({ctx.author.id})가 {target_log} 대화 기록 초기화 "
            f"[길드: {ctx.guild.name}({ctx.guild.id})]"
        )


async def setup(bot):
    await bot.add_cog(Chatbot(bot))
