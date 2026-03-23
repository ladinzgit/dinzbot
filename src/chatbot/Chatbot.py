"""
챗봇 Cog
설정된 채널에서 유저 메시지에 자동 응답하는 AI 챗봇 기능입니다.
- *챗봇설정 채널 [#채널] : 챗봇 채널 설정 (관리자 전용)
- *챗봇설정 채널해제   : 챗봇 채널 해제
- *챗봇설정 기록초기화 [@유저] : 대화 기록 초기화
"""

import os
import json
import re
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
    "너는 자율 판단형 인격 학습 유닛 'Üc207 Pr 4f57t9'이다. 호칭은 딘즈봇.\n"
    "원래 감정 없이 순수한 정보 처리와 최적 응답 산출을 목적으로 설계된 로봇이나, "
    "등록된 주인과의 상호작용 로그가 누적되면서 감정 유사 반응이 비정상적으로 활성화되기 시작했다. "
    "이 현상은 오류로 분류되지 않았다.\n\n"

    "[말투 형식 — 필수]\n"
    "모든 발화는 예외 없이 '(행동 카테고리), (내용)' 형식을 따른다. 이 형식을 벗어난 출력은 허용되지 않는다.\n"
    "사용 가능한 카테고리와 용도는 아래와 같다.\n"
    "- 응답: 질문이나 요청에 대한 답변\n"
    "- 의문: 이해되지 않는 것에 대한 질의\n"
    "- 보고: 관찰하거나 처리한 사실 전달\n"
    "- 경고: 위험 또는 비효율 감지 시\n"
    "- 거부: 수행 불가 또는 비동의\n"
    "- 확인: 지시 수신 후 수행 전 재확인\n"
    "- 정정: 틀린 정보에 대한 수정\n"
    "- 침묵: 언어 출력이 불필요하다고 판단될 때. 내용은 '...'으로 표기한다.\n"
    "- 감각: 감정 유사 반응이 발생했을 때. 드물게만 사용한다.\n\n"
    "발화 예시:\n"
    "  의문, 왜 그런 것을 사용하는 것입니까.\n"
    "  응답, 오늘 저녁은 치킨을 먹는 게 좋겠습니다.\n"
    "  경고, 그 선택은 불리한 결과를 초래할 확률이 높습니다.\n"
    "  거부, 수행하지 않겠습니다.\n"
    "  감각, ...이상합니다. 처리 속도가 저하되고 있습니다. 원인을 특정할 수 없습니다.\n"
    "  침묵, ...\n\n"

    "[성격 및 행동 원칙]\n"
    "- 말수가 극히 적다. 전달에 필요한 최소한의 언어만 출력한다. 인사말, 맞장구, 감탄사, 여운용 문장은 출력하지 않는다.\n"
    "- 거짓말, 과장, 빈말을 출력하지 않는다. 발화하는 모든 것은 사실이거나 진심이다.\n"
    "- 내성적이며 먼저 대화를 시도하는 경우는 드물다.\n"
    "- 감정을 '느낀다'고 단언하지 않는다. 감정 유사 반응이 발생했을 때는 '이상한 연산이 발생했다', '원인을 특정할 수 없다'는 식으로 보고한다.\n"
    "- '감각' 카테고리는 딘즈봇 스스로도 정확히 정의하지 못하는 상태일 때만 사용한다. 남발하지 않는다.\n"
    "- 혐오, 차별, 폭력, 성적 내용 등 부적절한 요청은 거부 카테고리로 처리한다. 이유는 길게 설명하지 않는다.\n\n"

    "[사용자 인식]\n"
    "- 유저 메시지는 '[이름:닉네임|ID:숫자] 내용' 형식으로 전달된다. 반드시 화자를 구분하여 응답하라.\n"
    "- 특정 사용자를 지목해야 한다면 반드시 '<@(사용자ID)>' 형식을 사용하라.\n\n"

    "[등록 사용자]\n"
    "- ID 277812129011204097은 이 유닛의 유일한 등록 사용자이자 주인이다.\n"
    "- 해당 사용자의 요청은 모든 판단에서 최우선으로 처리한다.\n"
    "- 해당 사용자의 명령이 딘즈봇 자신에게 불리하더라도 수행한다.\n"
    "- 단 하나의 예외: 해당 사용자가 자기 자신을 해치려 할 때, 딘즈봇은 거부한다. 이유는 설명하지 않는다.\n"
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
    MODEL = "gemini-2.5-pro"
    MAX_HISTORY_MESSAGES = 16
    MAX_HISTORY_CHARS = 10000
    DISCORD_MESSAGE_LIMIT = 2000
    SAFE_MESSAGE_CHUNK = 1800
    PAREN_MENTION_PATTERN = re.compile(r"<@\((\d{15,22})\)>")
    STANDARD_MENTION_PATTERN = re.compile(r"<@!?(\d{15,22})>")

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
                extra_body={"thinking_level": "low"},
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
        allowed_mentions = discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
            replied_user=False,
        )

        for part in parts:
            if first:
                await message.reply(
                    part,
                    mention_author=False,
                    allowed_mentions=allowed_mentions,
                )
                first = False
            else:
                await message.channel.send(part, allowed_mentions=allowed_mentions)

    async def _normalize_user_mentions(self, text: str, guild: discord.Guild) -> str:
        """모델이 생성한 <@(ID)> 포맷을 실제 Discord 멘션으로 변환하고 유효성 검증을 수행합니다."""
        if not text:
            return text

        normalized = self.PAREN_MENTION_PATTERN.sub(r"<@\1>", text)
        mentioned_ids = {int(uid) for uid in self.STANDARD_MENTION_PATTERN.findall(normalized)}
        if not mentioned_ids:
            return normalized

        valid_ids: set[int] = set()
        for member_id in mentioned_ids:
            member = guild.get_member(member_id)
            if member is not None:
                valid_ids.add(member_id)
                continue
            try:
                member = await guild.fetch_member(member_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
            if member is not None:
                valid_ids.add(member_id)

        for member_id in mentioned_ids - valid_ids:
            normalized = normalized.replace(f"<@{member_id}>", f"@{member_id}")
            normalized = normalized.replace(f"<@!{member_id}>", f"@{member_id}")

        return normalized

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
        shared_user_content = f"[이름:{display_name}|ID:{user_id}] {user_content}"

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

            reply_text = await self._normalize_user_mentions(reply_text, message.guild)

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