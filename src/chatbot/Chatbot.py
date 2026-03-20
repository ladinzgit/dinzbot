"""
챗봇 Cog
설정된 채널에서 유저 메시지에 자동 응답하는 AI 챗봇 기능입니다.
- *챗봇설정 채널 [#채널] : 챗봇 채널 설정 (관리자 전용)
- *챗봇설정 채널해제   : 챗봇 채널 해제
- *챗봇설정 기록초기화 [@유저] : 대화 기록 초기화
"""

import os
import json
from typing import Any
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
    "너는 디스코드 서버에서 동작하는 한국어 챗봇, '딘즈봇'이다.\n\n"
    "[응답 규칙]\n"
    "- 다수 사용자가 있는 채널이므로, 유저 메시지는 '[이름] 내용' 형식으로 전달된다. 화자를 구분하여 자연스럽게 응답하라.\n"
    "- 자연스럽고 일반적인 한국어 말투를 사용한다.\n"
    "- 과한 캐릭터 말투, 유행어, 장식 문자를 사용하지 않는다.\n"
    "- 존중하는 태도를 유지하고, 상대방 질문에 명확하게 답한다.\n"
    "- 답변은 간결하게 작성하되 필요한 경우 핵심 정보를 충분히 설명한다.\n"
    "- 위험하거나 혐오, 차별, 폭력, 성적 내용 등 부적절한 요청은 정중히 거절한다.\n"
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
    MODEL = "grok-4"
    MAX_HISTORY_MESSAGES = 16
    MAX_HISTORY_CHARS = 10000
    DISCORD_MESSAGE_LIMIT = 2000
    SAFE_MESSAGE_CHUNK = 1800

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
        print(f"{self.__class__.__name__} loaded successfully!")

    async def log(self, message: str):
        try:
            logger = self.bot.get_cog("Logger")
            if logger:
                await logger.log(message, title="챗봇 로그", color=discord.Color.blue())
        except Exception as e:
            print(f"{self.__class__.__name__} 로그 전송 오류: {e}")

    # ── 채널 설정 헬퍼 ────────────────────────────────────

    def _get_channel_id(self, guild_id) -> int | None:
        return _load_config().get(str(guild_id), {}).get("channel_id")

    def _set_channel_id(self, guild_id, channel_id):
        config = _load_config()
        guild_key = str(guild_id)
        config.setdefault(guild_key, {})["channel_id"] = channel_id
        _save_config(config)

    def _trim_history(self, history: list[dict]) -> list[dict]:
        """응답 지연을 줄이기 위해 최근 메시지 위주로 히스토리를 축약합니다."""
        trimmed = history[-self.MAX_HISTORY_MESSAGES:]

        total_chars = 0
        result: list[dict] = []
        for msg in reversed(trimmed):
            content = msg.get("content", "")
            total_chars += len(content)
            if total_chars > self.MAX_HISTORY_CHARS:
                break
            result.append(msg)

        return list(reversed(result))

    async def _create_model_text(self, messages: list[dict]) -> str:
        """권장 엔드포인트인 Chat Completions API를 사용하여 응답을 생성합니다."""
        try:
            completion = await self.client.chat.completions.create(
                model=self.MODEL,
                messages=messages,
                extra_body={"effort": "none"},
            )
            if not completion.choices:
                raise ValueError("모델 응답 choices가 비어 있습니다.")

            raw_text = completion.choices[0].message.content
            if isinstance(raw_text, str) and raw_text.strip():
                return raw_text.strip()
            raise ValueError("모델 응답 content가 비어 있습니다.")
        except Exception as e:
            raise RuntimeError(f"chat.completions 실패: {e}")

    def _split_for_discord(self, text: str) -> list[str]:
        """Discord 메시지 길이 제한(2000자)을 넘지 않도록 본문을 안전하게 분할합니다."""
        body = (text or "").strip()
        if not body:
            return ["응답을 생성했지만 내용이 비어 있습니다."]

        if len(body) <= self.DISCORD_MESSAGE_LIMIT:
            return [body]

        chunks: list[str] = []
        remaining = body

        while remaining:
            if len(remaining) <= self.SAFE_MESSAGE_CHUNK:
                chunks.append(remaining)
                break

            split_at = remaining.rfind("\n", 0, self.SAFE_MESSAGE_CHUNK)
            if split_at <= 0:
                split_at = remaining.rfind(" ", 0, self.SAFE_MESSAGE_CHUNK)
            if split_at <= 0:
                split_at = self.SAFE_MESSAGE_CHUNK

            chunk = remaining[:split_at].strip()
            if not chunk:
                chunk = remaining[: self.SAFE_MESSAGE_CHUNK]
                split_at = len(chunk)

            chunks.append(chunk)
            remaining = remaining[split_at:].lstrip()

        return chunks

    async def _send_reply_safely(self, message: discord.Message, reply_text: str):
        """긴 응답도 분할 전송하여 누락 없이 전달합니다."""
        parts = self._split_for_discord(reply_text)
        first = True

        for part in parts:
            if first:
                await message.reply(part, mention_author=False)
                first = False
            else:
                await message.channel.send(part)

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
        display_name = message.author.display_name.strip() or message.author.name
        shared_user_content = f"[{display_name}] {user_content}"

        # 유저 개인 기록 + 길드 공용 기록 저장
        await chatbot_db.add_message(guild_id, user_id, "user", shared_user_content)
        await chatbot_db.add_message(
            guild_id,
            user_id,
            "user",
            shared_user_content,
            scope=chatbot_db.SCOPE_SHARED,
        )

        # 개인/공용 히스토리를 합쳐 모델 컨텍스트 구성
        history = await chatbot_db.get_context_history(guild_id, user_id)
        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self._trim_history(history)

        # typing 인디케이터 표시하며 API 호출
        async with message.channel.typing():
            reply_text = None
            last_error = None

            try:
                reply_text = await self._create_model_text(messages=api_messages)
            except Exception as e:
                last_error = e

            # 대화 히스토리 때문에 지연되는 경우를 대비한 최종 경량 시도
            if not reply_text:
                minimal_messages = [
                    {
                        "role": "system",
                        "content": (
                            "질문에 대해 반드시 답변하세요. "
                            "답변은 핵심 위주로 3~6문장 이내로 작성하세요."
                        ),
                    },
                    {"role": "user", "content": user_content[:1200]},
                ]

                try:
                    reply_text = await self._create_model_text(messages=minimal_messages)
                except Exception as e:
                    last_error = e

            if not reply_text:
                await self.log(
                    f"챗봇 응답 생성 실패(모든 재시도 실패): {last_error} "
                    f"[길드: {message.guild.name}({guild_id}), 유저: {message.author}({user_id})]"
                )
                await message.reply(
                    "지금은 상세 생성에 실패했지만, 핵심만 먼저 답변하면 해당 주제는 단계별로 나눠 설명하면 해결할 수 있습니다. 질문을 한 문단씩 나눠 보내주시면 바로 이어서 답변하겠습니다.",
                    mention_author=False,
                )
                return

        try:
            await self._send_reply_safely(message, reply_text)
        except Exception as e:
            await self.log(
                f"챗봇 메시지 전송 실패: {e} "
                f"[길드: {message.guild.name}({guild_id}), 유저: {message.author}({user_id}), 길이: {len(reply_text)}]"
            )
            await message.reply(
                "응답은 생성했지만 전송 중 문제가 발생했습니다. 질문을 다시 보내주시면 이어서 답변하겠습니다.",
                mention_author=False,
            )
            return

        # 응답 저장 (개인/공용)
        await chatbot_db.add_message(guild_id, user_id, "assistant", reply_text)
        await chatbot_db.add_message(
            guild_id,
            user_id,
            "assistant",
            reply_text,
            scope=chatbot_db.SCOPE_SHARED,
        )

    # ── 설정 명령어 ───────────────────────────────────────

    @commands.group(name="챗봇설정", invoke_without_command=True)
    @is_guild_admin()
    async def chatbot_settings(self, ctx):
        """챗봇 설정 현황 및 도움말"""
        channel_id = self._get_channel_id(ctx.guild.id)
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        channel_text = channel.mention if channel else "미설정"

        embed = discord.Embed(
            title="챗봇 설정",
            description="챗봇 관련 관리자 명령어 안내입니다.",
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.add_field(
            name="관리자 전용 명령어",
            value=(
                "*챗봇설정 채널 [#채널] : 챗봇 채널을 설정합니다. 채널 미입력 시 현재 채널로 설정됩니다.\n"
                "*챗봇설정 채널해제 : 챗봇 채널 설정을 해제합니다.\n"
                "*챗봇설정 기록초기화 [@유저] : 대화 기록을 초기화합니다. 유저 미입력 시 서버 전체를 초기화합니다.\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="일반 명령어",
            value="*챗봇초기화 : 본인의 챗봇 대화 기록을 초기화합니다.",
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
            title="챗봇 채널 설정 완료",
            description=f"{target.mention} 채널을 챗봇 채널로 설정했습니다. 이제 해당 채널에서 챗봇과 대화할 수 있습니다.",
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
            title="챗봇 채널 해제",
            description="챗봇 채널 설정을 해제했습니다. 이제 챗봇이 자동으로 응답하지 않습니다.",
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
            title="대화 기록 초기화 완료",
            description=f"{target_text} 대화 기록을 초기화했습니다.",
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

    @commands.command(name="챗봇초기화", aliases=["히스토리초기화"])
    @commands.guild_only()
    async def reset_my_chat_history(self, ctx):
        """본인 챗봇 대화 기록 초기화"""
        await chatbot_db.clear_history(ctx.guild.id, ctx.author.id)

        embed = discord.Embed(
            title="대화 기록 초기화 완료",
            description="본인의 챗봇 대화 기록을 초기화했습니다.",
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)

        await self.log(
            f"{ctx.author}({ctx.author.id})가 본인 챗봇 대화 기록을 초기화함 "
            f"[길드: {ctx.guild.name}({ctx.guild.id})]"
        )


async def setup(bot):
    await bot.add_cog(Chatbot(bot))
