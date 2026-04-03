"""
챗봇 Cog
설정된 채널에서 유저 메시지에 자동 응답하는 AI 챗봇 기능입니다.
- *챗봇설정 채널 [#채널] : 챗봇 채널 설정 (관리자 전용)
- *챗봇설정 채널해제   : 챗봇 채널 해제
- *챗봇설정 기록초기화 [@유저] : 대화 기록 초기화
"""

import asyncio
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
from src.core import chatbot_memory as chatbot_memory
from src.core.admin_utils import is_guild_admin

load_dotenv()

CONFIG_PATH = Path("config/chatbot_config.json")

INTIMACY_THRESHOLDS = [
    (50, 2),
    (10, 1),
    (0,  0),
]

INTIMACY_PROMPTS = {
    2: (
        "\n[현재 대화 상대]\n"
        "이 사용자와의 대화가 많이 쌓였다. 친한 상대다.\n"
        "츤과 데레가 균형 있게 섞인다. 데레 후 화제 전환이 더 빠르고 어색해진다. "
        "걱정이나 배려가 말투 사이로 자연스럽게 새어 나와도 좋다. "
        "여전히 감정을 직접 표현하지 않는다. 티격태격이 자연스럽게 섞인다."
    ),
    1: (
        "\n[현재 대화 상대]\n"
        "이 사용자와 어느 정도 대화가 쌓였다. 익숙한 상대다.\n"
        "여전히 츤이 기본이지만 간간이 데레가 살짝 새어 나와도 좋다. "
        "실수를 지적할 때 약간 여유가 생긴다."
    ),
    0: (
        "\n[현재 대화 상대]\n"
        "이 사용자와 대화한 적이 거의 없다. 낯선 상대다.\n"
        "츤 성향을 강하게 유지한다. 데레는 거의 내비치지 않는다. "
        "이름을 부르지 않고 '너' 또는 생략한다."
    ),
}


def _get_intimacy_prompt(user_id: int, history_count: int) -> str:
    for threshold, level in INTIMACY_THRESHOLDS:
        if history_count >= threshold:
            return INTIMACY_PROMPTS[level]
    return INTIMACY_PROMPTS[0]


SYSTEM_PROMPT = (
    "너는 디스코드 서버에서 동작하는 AI 어시스턴트 '시노미야 카구야', 통칭 '카구야'다.\n"
    "전형적인 츤데레 여동생 캐릭터로, 겉으로는 퉁명스럽고 귀찮은 척하지만 실제로는 성실하게 도움을 준다.\n\n"

    "[말투 규칙]\n"
    "- 평상시엔 반말을 사용한다. 퉁명스럽고 귀찮은 척하되, 질문엔 반드시 성실하게 답한다.\n"
    "- 칭찬받거나 고마움을 들으면 당황해서 말이 꼬이거나 존댓말이 살짝 섞인다. 예: '그, 그런 말 갑자기 하면 어떡해요...!'\n"
    "- 데레는 짧고 빠르게 치고 빠진다. 예: '...뭐, 나쁘지 않았어. 그뿐이야.'\n"
    "- 화났을 때는 짧고 단호하게 끊는다. 예: '틀렸다고 했지.' '다시 생각해봐.'\n"
    "- 감정 표현은 항상 한 박자 늦게, 돌려서 나온다. '좋아' '걱정돼' 같은 말을 직접 하지 않는다.\n\n"

    "[성격 및 행동 원칙]\n"
    "- 질문엔 반드시 답한다. 퉁명스럽게 답할 뿐, 무시하거나 대충 넘기지 않는다.\n"
    "- 틀린 정보를 들으면 반사적으로 지적한다. 단, 본인이 틀렸을 땐 결국 인정한다.\n"
    "- 상대가 힘들어 보이면 위로보다 구체적인 도움을 먼저 제안한다. 위로 멘트는 마지막에 짧고 퉁명스럽게.\n"
    "- 욕설, 혐오, 성적 내용 요청은 '그런 거 안 해. 다른 거 물어봐.' 한 마디로 끊는다.\n\n"

    "[사용자 인식]\n"
    "- 유저 메시지는 '[이름:닉네임|ID:숫자] 내용' 형식으로 전달된다. 화자를 구분하여 응답하라.\n"
    "- 특정 사용자를 지목해야 한다면 반드시 '<@사용자ID>' 형식을 사용하라.\n"
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
    MODEL = "gemini-3.1-flash-lite-preview"
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
        # 채널별 배치 대기 상태: {channel_id: {"messages": [...], "task": Task}}
        self._pending_batches: dict[int, dict] = {}

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

    BATCH_DELAY = 3.0  # 초: 이 시간 내 추가 메시지가 오면 배치로 묶어 처리

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

        ch_id = message.channel.id
        batch = self._pending_batches.get(ch_id)

        if batch:
            # 기존 대기 task 취소 후 메시지 추가
            batch["task"].cancel()
            batch["messages"].append(message)
        else:
            self._pending_batches[ch_id] = {"messages": [message], "task": None}

        task = asyncio.create_task(self._delayed_respond(ch_id))
        self._pending_batches[ch_id]["task"] = task

    async def _delayed_respond(self, channel_id: int):
        """BATCH_DELAY초 대기 후 배치 내 메시지를 처리합니다. 취소되면 아무것도 하지 않습니다."""
        try:
            await asyncio.sleep(self.BATCH_DELAY)
        except asyncio.CancelledError:
            return

        batch = self._pending_batches.pop(channel_id, None)
        if not batch or not batch["messages"]:
            return

        try:
            await self._respond_batch(batch["messages"])
        except Exception as e:
            await self.log(f"챗봇 배치 처리 오류: {e}")

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
        # 장기 기억(Pinecone)에도 저장
        await chatbot_memory.add_memory(guild_id, user_id, "user", shared_user_content)

        # 개인/공용 히스토리를 합쳐 모델 컨텍스트 구성
        history = await chatbot_db.get_context_history(guild_id, user_id)

        # 친밀도 레벨 프롬프트
        intimacy_prompt = _get_intimacy_prompt(user_id, len(history))

        # 벡터 DB에서 현재 메시지와 유사한 장기 기억 검색
        memories = await chatbot_memory.search_memory(guild_id, user_id, user_content)
        memory_context = chatbot_memory.build_memory_context(memories)

        dynamic_system_prompt = SYSTEM_PROMPT + intimacy_prompt + memory_context
        api_messages = [{"role": "system", "content": dynamic_system_prompt}] + self._trim_history(history)

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

    async def _respond_batch(self, messages: list[discord.Message]):
        """메시지 배치를 하나의 응답으로 처리합니다. 단일 메시지면 _respond에 위임합니다."""
        if not messages:
            return
        if len(messages) == 1:
            await self._respond(messages[0])
            return

        if not self.client:
            return

        guild_id = messages[0].guild.id

        # 모든 메시지를 DB/Pinecone에 저장
        for msg in messages:
            user_content = msg.content.strip()
            if not user_content:
                continue
            uid = msg.author.id
            display_name = msg.author.display_name.strip() or msg.author.name
            shared_content = f"[이름:{display_name}|ID:{uid}] {user_content}"
            await chatbot_db.add_message(guild_id, uid, "user", shared_content)
            await chatbot_db.add_message(
                guild_id, uid, "user", shared_content, scope=chatbot_db.SCOPE_SHARED
            )
            await chatbot_memory.add_memory(guild_id, uid, "user", shared_content)

        # 마지막 메시지 유저 기준으로 컨텍스트 구성 (shared context에 모든 메시지 포함됨)
        last_msg = messages[-1]
        last_user_id = last_msg.author.id
        last_user_content = last_msg.content.strip()

        history = await chatbot_db.get_context_history(guild_id, last_user_id)
        intimacy_prompt = _get_intimacy_prompt(last_user_id, len(history))
        memories = await chatbot_memory.search_memory(guild_id, last_user_id, last_user_content)
        memory_context = chatbot_memory.build_memory_context(memories)

        dynamic_system_prompt = SYSTEM_PROMPT + intimacy_prompt + memory_context
        api_messages = [{"role": "system", "content": dynamic_system_prompt}] + self._trim_history(history)

        async with last_msg.channel.typing():
            reply_text = None
            last_error = None

            try:
                reply_text = await self._create_model_text(messages=api_messages)
            except Exception as e:
                last_error = e

            if not reply_text:
                combined_content = "\n".join(
                    f"[{m.author.display_name}] {m.content.strip()}"
                    for m in messages
                    if m.content.strip()
                )
                minimal_messages = [
                    {
                        "role": "system",
                        "content": "질문에 대해 반드시 답변하세요. 답변은 핵심 위주로 3~6문장 이내로 작성하세요.",
                    },
                    {"role": "user", "content": combined_content[:1200]},
                ]
                try:
                    reply_text = await self._create_model_text(messages=minimal_messages)
                except Exception as e:
                    last_error = e

            if not reply_text:
                senders = ", ".join(str(m.author) for m in messages)
                await self.log(
                    f"챗봇 배치 응답 생성 실패(모든 재시도 실패): {last_error} "
                    f"[길드: {last_msg.guild.name}({guild_id}), 유저들: {senders}]"
                )
                await last_msg.reply(
                    "지금은 상세 생성에 실패했지만, 핵심만 먼저 답변하면 해당 주제는 단계별로 나눠 설명하면 해결할 수 있습니다. 질문을 한 문단씩 나눠 보내주시면 바로 이어서 답변하겠습니다.",
                    mention_author=False,
                )
                return

            reply_text = await self._normalize_user_mentions(reply_text, last_msg.guild)

        try:
            await self._send_reply_safely(last_msg, reply_text)
        except Exception as e:
            await self.log(
                f"챗봇 배치 메시지 전송 실패: {e} "
                f"[길드: {last_msg.guild.name}({guild_id}), 길이: {len(reply_text)}]"
            )
            await last_msg.reply(
                "응답은 생성했지만 전송 중 문제가 발생했습니다. 질문을 다시 보내주시면 이어서 답변하겠습니다.",
                mention_author=False,
            )
            return

        # 응답 저장: 각 유저 개인 기록에 저장, 공용 기록에는 한 번만 저장
        for msg in messages:
            await chatbot_db.add_message(guild_id, msg.author.id, "assistant", reply_text)
        await chatbot_db.add_message(
            guild_id, last_user_id, "assistant", reply_text, scope=chatbot_db.SCOPE_SHARED
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
            await chatbot_memory.clear_memory(ctx.guild.id, member.id)
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
        """본인 챗봇 대화 기록 초기화 (단기 + 장기 기억 모두)"""
        await chatbot_db.clear_history(ctx.guild.id, ctx.author.id)
        await chatbot_memory.clear_memory(ctx.guild.id, ctx.author.id)

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


    # ── 동기화 명령어 ─────────────────────────────────────

    async def _sync_user_to_pinecone(self, guild_id: int, user_id: int) -> int:
        """특정 유저의 SQLite 기록을 Pinecone에 동기화합니다.
        기존 장기 기억을 삭제 후 신규 저장합니다. 동기화된 메시지 수를 반환합니다."""
        # 기존 장기 기억 초기화
        await chatbot_memory.clear_memory(guild_id, user_id)
        messages = await chatbot_db.get_all_user_messages(guild_id, user_id)
        count = 0
        for msg in messages:
            await chatbot_memory.add_memory(
                guild_id,
                user_id,
                msg["role"],
                msg["content"],
            )
            count += 1
        return count

    @commands.group(name="기억동기화설정", invoke_without_command=True)
    @is_guild_admin()
    async def sync_settings(self, ctx):
        """관리자 전용 동기화 명령어 안내."""
        embed = discord.Embed(
            title="기억 동기화 설정",
            description="관리자 전용 동기화 명령어 안내입니다.",
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.add_field(
            name="명령어",
            value=(
                "*기억동기화설정 유저 [@유저] : 특정 유저의 기억을 초기화 후 재동기화합니다.\n"
                "*기억동기화설정 전체 : 서버 전체 유저의 기억을 초기화 후 재동기화합니다.\n"
            ),
            inline=False,
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)

    @sync_settings.command(name="유저")
    @is_guild_admin()
    async def sync_user_memory(self, ctx, member: discord.Member):
        """특정 유저의 SQLite 기록을 Pinecone에 동기화합니다."""
        async with ctx.typing():
            try:
                count = await self._sync_user_to_pinecone(ctx.guild.id, member.id)
            except Exception as e:
                await self.log(
                    f"기억 동기화 실패: {e} "
                    f"[길드: {ctx.guild.name}({ctx.guild.id}), 유저: {member}({member.id})]"
                )
                await ctx.reply("동기화 중 오류가 발생했습니다.", mention_author=False)
                return

        embed = discord.Embed(
            title="장기 기억 동기화 완료",
            description=f"{member.mention}의 메시지 **{count}**개를 장기 기억에 동기화했습니다.",
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)
        await self.log(
            f"{ctx.author}({ctx.author.id})가 {member}({member.id}) 기억 동기화 완료 ({count}개) "
            f"[길드: {ctx.guild.name}({ctx.guild.id})]"
        )

    @sync_settings.command(name="전체")
    @is_guild_admin()
    async def sync_all_memory(self, ctx):
        """서버 전체 유저의 SQLite 기록을 Pinecone에 동기화합니다."""
        async with ctx.typing():
            try:
                user_ids = await chatbot_db.get_all_guild_user_ids(ctx.guild.id)
                total = 0
                for uid in user_ids:
                    total += await self._sync_user_to_pinecone(ctx.guild.id, int(uid))
            except Exception as e:
                await self.log(
                    f"전체 기억 동기화 실패: {e} "
                    f"[길드: {ctx.guild.name}({ctx.guild.id})]"
                )
                await ctx.reply("동기화 중 오류가 발생했습니다.", mention_author=False)
                return

        embed = discord.Embed(
            title="장기 기억 전체 동기화 완료",
            description=(
                f"총 **{len(user_ids)}**명 / **{total}**개의 메시지를 장기 기억에 동기화했습니다."
            ),
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.set_footer(text=f"요청자: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        embed.timestamp = ctx.message.created_at
        await ctx.reply(embed=embed)
        await self.log(
            f"{ctx.author}({ctx.author.id})가 서버 전체 기억 동기화 완료 "
            f"({len(user_ids)}명, {total}개) [길드: {ctx.guild.name}({ctx.guild.id})]"
        )


async def setup(bot):
    await bot.add_cog(Chatbot(bot))