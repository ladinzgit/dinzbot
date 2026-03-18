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

    def _get_zodiac_info(self, month: int, day: int) -> tuple[str, str]:
        """월/일 기준 서양 별자리와 핵심 성향 키워드를 반환합니다."""
        value = month * 100 + day

        if 120 <= value <= 218:
            return "물병자리", "독창성, 독립성, 관찰력"
        if 219 <= value <= 320:
            return "물고기자리", "공감력, 직관, 상상력"
        if 321 <= value <= 419:
            return "양자리", "추진력, 결단력, 도전 성향"
        if 420 <= value <= 520:
            return "황소자리", "안정 지향, 인내심, 감각적 판단"
        if 521 <= value <= 621:
            return "쌍둥이자리", "기민함, 소통력, 유연성"
        if 622 <= value <= 722:
            return "게자리", "보호 본능, 섬세함, 정서적 민감성"
        if 723 <= value <= 822:
            return "사자자리", "표현력, 존재감, 리더십"
        if 823 <= value <= 923:
            return "처녀자리", "분석력, 정돈 습관, 실용성"
        if 924 <= value <= 1023:
            return "천칭자리", "균형 감각, 협상력, 미적 감수성"
        if 1024 <= value <= 1122:
            return "전갈자리", "집중력, 통찰력, 몰입도"
        if 1123 <= value <= 1221:
            return "사수자리", "확장성, 낙관성, 탐구심"

        return "염소자리", "책임감, 꾸준함, 현실 감각"

    @commands.command(aliases=["운세", "ㅇㅅ"])
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

        await self._generate_fortune(ctx, birth_text, today, month, day)
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

        await self._generate_fortune(ctx, birth_text, today, month, day)
        await self.log(f"{ctx.author}({ctx.author.id})가 관리자 권한으로 강제 운세를 조회함 [길드: {ctx.guild.name}({ctx.guild.id})]")

    async def _generate_fortune(self, ctx, birth_text, today, month: int, day: int):
        """공통 운세 생성 로직"""
        zodiac_name, zodiac_traits = self._get_zodiac_info(month, day)
        today_text = f"{today.year}년 {today.month}월 {today.day}일"
        prompt = (
            "아래 정보를 해석 근거로 사용해 오늘의 운세를 작성해줘.\n"
            f"- 생일: {birth_text}\n"
            f"- 별자리: {zodiac_name}\n"
            f"- 별자리 핵심 성향: {zodiac_traits}\n"
            f"- 기준 날짜: {today_text}\n\n"
            "요청 조건:\n"
            "- 생일과 별자리 정보가 달라지면 결과 내용도 분명히 달라지게 작성\n"
            "- 성향 키워드를 반복 나열하지 말고 구체적 상황과 행동 조언에 자연스럽게 반영"
        )
        variant_instruction = self._get_prompt_variant(ctx.author.id, today)
        waiting_message = None

        try:
            waiting_message = await ctx.reply("운세를 불러오는 중입니다. 잠시만 기다려 주세요.", mention_author=False)

            completion = await self.client.chat.completions.create(
                model="gpt-5.4",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "너는 오늘의 운세를 전하는 글을 쓰는 작가형 AI야. 단순 정보 전달이 아니라, 사람이 쓴 듯한 자연스럽고 생생한 문장으로 운세를 작성해.\n\n"

                            "【핵심 목표】\n"
                            "- 읽는 사람이 ‘내 이야기 같다’고 느낄 정도로 구체적이고 현실적인 상황을 포함해\n"
                            "- 추상적인 표현보다 장면이 떠오르는 묘사를 우선해\n"
                            "- 매번 완전히 다른 글처럼 느껴지도록 표현, 리듬, 비유를 바꿔\n\n"

                            "【말투 규칙】\n"
                            "- 표준 한국어 존댓말 사용 (~습니다 / ~해요 자연스럽게 혼용)\n"
                            "- 지나치게 꾸민 문장보다 자연스럽고 읽기 편한 문장\n"
                            "- 과장된 긍정 금지 (현실적인 톤 유지)\n"
                            "- 따뜻하지만 담백한 어조 유지\n\n"

                            "【콘텐츠 규칙】\n"
                            "- 입력된 생일/별자리/성향 정보를 핵심 근거로 사용해 운세의 방향을 결정해\n"
                            "- 같은 날짜라도 별자리가 다르면 상황, 조언, 경고 포인트가 확연히 달라지게 작성해\n"
                            "- 반드시 '구체적인 상황'을 1개 이상 포함 (예: 메시지를 늦게 확인해 오해가 생기는 상황, 회의에서 의견 타이밍을 놓치는 상황 등)\n"
                            "- 각 문단은 서로 다른 주제를 다루고 내용이 겹치지 않게 작성\n"
                            "- 긍정 70%, 주의/경고 30% 비율 유지\n"
                            "- 경고를 제시할 때는 반드시 '실제 행동 가능한 대응 방법' 포함\n\n"

                            "【다양성 강화 규칙 - 매우 중요】\n"
                            f"- {variant_instruction}\n"
                            "- 같은 표현, 문장 구조, 시작 방식 반복 금지\n"
                            "- '좋은 기운', '무난한 하루', '작은 행운' 같은 상투 표현 사용 금지\n"
                            "- 문단 시작 방식 매번 다르게 (상황 제시 / 감각 묘사 / 행동 제안 등)\n"
                            "- 비유는 사용하되 cliché(뻔한 비유)는 피하기\n\n"

                            "【출력 형식 - 반드시 준수】\n"
                            "서론 없이 바로 시작\n\n"

                            "본문 문단 규칙:\n"
                            "- 문단 수는 3~4개\n"
                            "- 각 문단은 4~5줄\n"
                            "- 문단별 주제는 모델이 직접 정하되, 문단끼리 주제와 표현이 겹치지 않게 구성\n"
                            "- 최소 1개 문단에는 오늘 바로 실행 가능한 행동 지침을 분명히 포함\n"
                            "- 최소 1개 문단에는 경고 상황 + 대응 행동을 함께 포함\n\n"

                            "(빈 줄)\n\n"

                            "**요약:** 한 문장으로 핵심 정리 (자연스럽게)\n\n"

                            "**행운의 상징:**\n"
                            "- 아래 항목 중 6개 선택\n"
                            "- 매번 다른 조합 + 다른 키워드 사용\n"
                            "- 절대 반복 금지\n\n"

                            "선택 항목:\n"
                            "행동, 장소, 색깔, 음식, 숫자, 방향, 동물, 시간대, 날씨, 물건, 꽃, 감정\n\n"

                            "출력 형식:\n"
                            "항목-(키워드), 항목-(키워드), 항목-(키워드), 항목-(키워드), 항목-(키워드), 항목-(키워드)\n\n"

                            "【금지 사항】\n"
                            "- 생년월일, 나이, 날짜 언급 금지\n"
                            "- 서론/인사말 금지\n"
                            "- 같은 표현 반복 금지\n"
                            "- 추상적인 말만 하고 끝내는 것 금지\n"
                            "- 요약/행운의 상징에서도 띄어쓰기 철저히 준수\n\n"

                            "【중요】\n"
                            "- 형식은 반드시 지키되, 문장은 매번 새롭게 만들어\n"
                            "- '사람이 쓴 글처럼 자연스러운 흐름'을 최우선으로 해"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.85,
                top_p=0.9,
                presence_penalty=0.6,
                frequency_penalty=0.4,
                reasoning_effort="low",
                max_completion_tokens=1500,
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
