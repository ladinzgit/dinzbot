import os
from datetime import datetime

import discord
from discord.ext import commands
from openai import AsyncOpenAI

from src.core import birthday_db
from src.core import fortune_db
from src.core.admin_utils import only_in_guild, is_guild_admin
import pytz
KST = pytz.timezone("Asia/Seoul")

from dotenv import load_dotenv
load_dotenv()

class FortuneCommand(commands.Cog):
    """*운세 명령어를 처리하는 Cog"""

    BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"

    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.environ.get("FACTCHAT_API_KEY")
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.BASE_URL) if self.api_key else None

    async def cog_load(self):
        print(f"✅ {self.__class__.__name__} loaded successfully!")

    async def log(self, message: str):
        try:
            logger = self.bot.get_cog("Logger")
            if logger:
                await logger.log(message, title="🍀 운세 시스템 로그", color=discord.Color.green())
        except Exception as e:
            print(f"❌ {self.__class__.__name__} 로그 전송 오류 발생: {e}")

    def _ensure_client(self):
        current_key = os.environ.get("FACTCHAT_API_KEY")
        if current_key != self.api_key:
            self.api_key = current_key
            self.client = None
        if not self.client and self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.BASE_URL)

    def _get_prompt_variant(self, user_id: int, today: datetime) -> str:
        """사용자/날짜 기반으로 프롬프트 변주를 고정해 운세 표현 다양성을 높입니다."""
        variants = [
            "오늘은 실행 우선형 톤으로 작성해. 문장마다 실천 가능한 행동을 1개 이상 포함해.",
            "오늘은 관찰 우선형 톤으로 작성해. 주변 신호와 타이밍을 읽는 조언을 중심으로 써.",
            "오늘은 균형 조정형 톤으로 작성해. 무리했을 때의 리스크와 회복 루틴을 구체적으로 제안해.",
            "오늘은 관계 전략형 톤으로 작성해. 말의 순서, 표현 강도, 거리 조절 팁을 분명하게 제시해.",
            "오늘은 집중/분산 관리형 톤으로 작성해. 해야 할 일의 우선순위와 미루기 방지 전략을 포함해.",
            "오늘은 기회 포착형 톤으로 작성해. 좋은 흐름을 잡는 조건과 놓치기 쉬운 함정을 함께 설명해.",
            "오늘은 감정 안정형 톤으로 작성해. 예민해질 수 있는 순간과 감정 조절 방법을 현실적으로 안내해.",
        ]
        idx = (user_id + today.toordinal()) % len(variants)
        return variants[idx]

    @commands.command(name="운세")
    @only_in_guild()
    async def tell_fortune(self, ctx):
        """오늘의 운세를 생성하여 전송합니다. 하루에 한 번 사용 가능합니다."""
        config = fortune_db.get_guild_config(ctx.guild.id)

        # 설정된 채널에서만 사용 가능
        channel_id = config.get("channel_id")
        if channel_id and ctx.channel.id != channel_id:
            return

        # 하루 1회 제한 확인
        today_str = datetime.now(KST).strftime("%Y-%m-%d")
        last_used = fortune_db.get_user_last_used(ctx.guild.id, ctx.author.id)
        if last_used == today_str:
            await ctx.reply("오늘의 운세는 이미 확인하셨습니다. 내일 다시 이용해 주세요.", mention_author=False)
            return

        self._ensure_client()
        if not self.api_key:
            await ctx.reply("`FACTCHAT_API_KEY` 환경 변수가 설정되어 있지 않습니다.")
            return

        birthday = await birthday_db.get_birthday(str(ctx.author.id))
        if not birthday:
            await ctx.reply("생일 정보가 없습니다. <#1483648067059191818>에서 먼저 생일을 등록해 주세요.")
            return

        birth_year = birthday.get("year")
        month = birthday.get("month")
        day = birthday.get("day")

        if not month or not day:
            await ctx.reply("생일 데이터를 불러오는 데 문제가 생겼습니다. 생일을 다시 등록해 주세요.")
            return

        today = datetime.now(KST)
        birth_text = f"{birth_year}년 {month}월 {day}일생" if birth_year else f"생년 미기재 {month}월 {day}일생"

        await self._generate_fortune(ctx, birth_text, today)
        fortune_db.set_user_last_used(ctx.guild.id, ctx.author.id, today_str)

        await self.log(
            f"{ctx.author}({ctx.author.id})가 운세를 조회함 "
            f"[길드: {ctx.guild.name}({ctx.guild.id})]"
        )

    @commands.command(name="강제운세")
    @is_guild_admin()
    async def force_fortune(self, ctx):
        """관리자 권한으로 제약 없이 운세를 생성합니다."""
        self._ensure_client()
        if not self.api_key:
            await ctx.reply("`FACTCHAT_API_KEY` 환경 변수가 설정되어 있지 않습니다.")
            return

        birthday = await birthday_db.get_birthday(str(ctx.author.id))
        if not birthday:
            await ctx.reply("강제 운세를 사용하려면 생일 정보가 필요합니다. <#1396829221741002796>에서 먼저 등록해 주세요.")
            return

        birth_year = birthday.get("year")
        month = birthday.get("month")
        day = birthday.get("day")

        if not month or not day:
            await ctx.reply("생일 데이터를 불러오는 데 문제가 생겼습니다.")
            return

        today = datetime.now(KST)
        birth_text = f"{birth_year}년 {month}월 {day}일생" if birth_year else f"생년 미기재 {month}월 {day}일생"

        await self._generate_fortune(ctx, birth_text, today)
        await self.log(f"{ctx.author}({ctx.author.id})가 관리자 권한으로 강제 운세를 조회함 [길드: {ctx.guild.name}({ctx.guild.id})]")

    async def _generate_fortune(self, ctx, birth_text, today):
        """공통 운세 생성 로직"""
        today_text = f"{today.year}년 {today.month}월 {today.day}일"
        prompt = f"{birth_text} {today_text} 오늘의 운세를 알려줘"
        variant_instruction = self._get_prompt_variant(ctx.author.id, today)
        waiting_message = None

        try:
            waiting_message = await ctx.reply("운세를 불러오는 중입니다. 잠시만 기다려 주세요.", mention_author=False)

            completion = await self.client.chat.completions.create(
                model="gpt-5.2",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "너는 오늘의 운세를 알려주는 AI야. 친절하고 따뜻한 말투를 사용해.\n\n"
                            "【말투 규칙】\n"
                            "- 표준 한국어 존댓말을 사용해 (예: ~입니다, ~해요, ~네요)\n"
                            "- 한국어 띄어쓰기를 정확하게 지켜\n"
                            "- 친근하고 따뜻한 톤은 유지하되, 현실적인 경고/주의 포인트는 반드시 포함해\n"
                            "- 공포를 유발하거나 단정적인 불행 예언은 금지하고, 주의사항에는 항상 대응 방법을 함께 제시해\n\n"
                            "【다양성 강화 규칙 - 반드시 준수】\n"
                            f"- {variant_instruction}\n"
                            "- 늘 쓰는 상투 표현(예: '작은 행운', '무난한 하루', '좋은 기운')을 반복하지 말고 매 응답마다 표현과 비유를 바꿔\n"
                            "- 문단별 초점이 겹치지 않게 작성하고, 구체적인 상황 예시를 최소 1개 이상 포함해\n"
                            "- 전체 톤은 긍정 70%, 경고 30% 정도로 균형을 맞춰\n\n"
                            "【출력 형식 - 반드시 준수】\n"
                            "서론, 인사말, 부연 설명 없이 운세 본문부터 바로 시작해.\n\n"
                            "첫 번째 문단 (4~5줄): 오늘의 전반적인 에너지 흐름을 구체적으로 묘사하고, 일·학업에서 어떤 상황이 펼쳐질지, 어떻게 행동하면 좋을지 실질적인 조언을 담아.\n"
                            "(빈 줄)\n"
                            "두 번째 문단 (4~5줄): 대인관계와 소통 운세를 구체적으로 서술해. 어떤 유형의 사람과의 교류가 이로운지, 어떤 상황에서 마찰/오해가 생기기 쉬운지, 이를 줄이는 대화법을 포함해.\n"
                            "(빈 줄)\n"
                            "세 번째 문단 (4~5줄): 컨디션·건강 상태, 금전·소비운, 오늘 하루를 잘 마무리하기 위한 구체적인 조언을 각각 담아. 특히 과소비/실수 가능성 같은 리스크 1~2개와 예방 행동을 포함해.\n"
                            "(빈 줄)\n"
                            "**요약:** (한 문장 요약).\n"
                            "**행운의 상징:** 아래 항목 목록에서 매번 다른 6가지를 골라 표시해. 고른 항목과 키워드 모두 매번 신선하고 다양하게 바꿔.\n"
                            "선택 가능 항목: 행동, 장소, 색깔, 음식, 숫자, 방향, 동물, 시간대, 날씨, 물건, 꽃, 감정\n"
                            "형식: 항목명-(키워드), 항목명-(키워드), 항목명-(키워드), 항목명-(키워드), 항목명-(키워드), 항목명-(키워드)\n\n"
                            "【금지 사항】\n"
                            "- 생년월일, 나이, 날짜 언급 절대 금지\n"
                            "- '운세를 전할게', '알려줄게', '일반 운세로 전해줄게' 같은 서론 금지\n"
                            "- 요약과 행운의 상징 줄에서도 띄어쓰기 철저히 지켜\n"
                            "- 행운의 상징은 매번 반드시 다른 항목 조합과 다른 키워드를 사용해"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=1.0,
                reasoning_effort="low",
                max_completion_tokens=3000,
            )
            fortune_text = completion.choices[0].message.content.strip()
        except Exception as e:
            error_msg = "운세를 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
            if waiting_message:
                try:
                    await waiting_message.edit(content=error_msg)
                except Exception:
                    await ctx.reply(error_msg, mention_author=False)
            else:
                await ctx.reply(error_msg, mention_author=False)
            await self.log(f"운세 생성 오류: {e} [길드: {ctx.guild.name}({ctx.guild.id}), 사용자: {ctx.author}({ctx.author.id})]")
            return

        try:
            if waiting_message:
                await waiting_message.edit(content=fortune_text)
            else:
                await ctx.reply(fortune_text, mention_author=False)
        except Exception:
            await ctx.reply(fortune_text, mention_author=False)


async def setup(bot):
    await bot.add_cog(FortuneCommand(bot))
