import os
import random
import re
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
        """매 호출마다 문체/리듬이 달라지도록 다양성 지시문을 반환합니다."""
        variants = [
            "문장 길이를 짧은 문장과 긴 문장으로 교차하고, 문단 첫 문장은 각각 다른 방식(상황 제시/행동 제안/감각 묘사)으로 시작해",
            "각 문단에 서로 다른 리듬을 사용하고, 같은 어미 반복을 줄이며, 비유는 한 문단에 최대 1회만 사용해",
            "문단마다 시점을 다르게 운용해(관찰->행동->정리), 상투 표현 없이 구체 장면 중심으로 전개해",
            "첫 문단은 현실 장면, 둘째 문단은 대화 맥락, 셋째 문단은 체크리스트형 조언으로 구성하되 문장 흐름은 자연스럽게 이어가",
            "문단 시작어를 모두 다르게 하고, 연결어 남용을 피하며, 핵심 조언은 동사 중심으로 또렷하게 써",
        ]
        return random.choice(variants)

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

    def _calculate_life_path(self, birth_year, month: int, day: int) -> int | None:
        """생년월일 기반 라이프패스 수를 계산합니다."""
        if not birth_year:
            return None

        digits = f"{birth_year}{month:02d}{day:02d}"
        total = sum(int(ch) for ch in digits if ch.isdigit())

        while total > 9 and total not in (11, 22, 33):
            total = sum(int(ch) for ch in str(total))
        return total

    def _build_birth_profile(self, birth_year, month: int, day: int) -> dict:
        """운세 프롬프트 개인화에 사용하는 출생 프로필을 구성합니다."""
        zodiac, zodiac_key = self._get_zodiac_info(month, day)

        month_key_map = {
            1: "초반 정비와 목표 재설정", 2: "관계 온도와 감정 균형", 3: "새 시도와 속도감", 4: "실행력과 루틴 강화",
            5: "현실 점검과 안정 추구", 6: "협업과 조율", 7: "내면 정리와 집중", 8: "성과 의식과 자기표현",
            9: "정리와 품질 개선", 10: "균형 잡힌 선택", 11: "깊이 있는 몰입", 12: "마무리와 재충전",
        }

        relation_style_map = {
            "양자리": "직설적이고 빠른 소통", "황소자리": "신뢰 기반의 차분한 소통", "쌍둥이자리": "가볍고 재치 있는 소통",
            "게자리": "배려 중심의 정서적 소통", "사자자리": "명확하고 존재감 있는 소통", "처녀자리": "정확하고 실용적인 소통",
            "천칭자리": "균형과 합의를 중시하는 소통", "전갈자리": "깊이 있고 집중도 높은 소통", "사수자리": "열린 시야의 솔직한 소통",
            "염소자리": "책임과 약속을 중시하는 소통", "물병자리": "독립적이고 아이디어 중심 소통", "물고기자리": "공감과 맥락을 살리는 소통",
        }

        mistake_trigger_map = {
            "양자리": "성급한 결론", "황소자리": "변화 회피", "쌍둥이자리": "집중 분산", "게자리": "감정 과몰입",
            "사자자리": "체면 의식", "처녀자리": "과도한 완벽주의", "천칭자리": "결정 지연", "전갈자리": "과한 의심",
            "사수자리": "계획 없는 낙관", "염소자리": "무리한 책임", "물병자리": "거리 두기 과다", "물고기자리": "경계 흐림",
        }

        luck_anchor_map = {
            "양자리": "짧고 빠른 첫 행동", "황소자리": "루틴 한 가지 고정", "쌍둥이자리": "메모와 즉시 공유",
            "게자리": "감정 환기 산책", "사자자리": "핵심 한 문장 선언", "처녀자리": "체크리스트 3개",
            "천칭자리": "선택 기준 먼저 적기", "전갈자리": "중요 일 한 번에 몰입", "사수자리": "작은 탐색 시도",
            "염소자리": "우선순위 1개 고정", "물병자리": "새 관점 질문 1개", "물고기자리": "직관 기록 후 검증",
        }

        return {
            "zodiac": zodiac,
            "zodiac_key": zodiac_key,
            "month_key": month_key_map.get(month, "월별 성향 미정"),
            "relation_style": relation_style_map.get(zodiac, "상황 맞춤 소통"),
            "mistake_trigger": mistake_trigger_map.get(zodiac, "과한 단정"),
            "luck_anchor": luck_anchor_map.get(zodiac, "작은 실행 루틴"),
            "life_path": self._calculate_life_path(birth_year, month, day),
        }

    def _extract_avoid_phrases(self, recent_texts: list[str], max_items: int = 8) -> list[str]:
        """최근 운세에서 반복을 피할 상투 표현을 추출합니다."""
        if not recent_texts:
            return []

        candidates = [
            "좋은 기운", "무난한 하루", "작은 행운", "기회를 잡", "흐름을 타", "균형을 유지", "여유를 가져",
            "신중하게", "서두르지", "천천히", "타이밍", "소통이 중요", "컨디션 관리", "지출 관리",
        ]

        joined = "\n".join(recent_texts)
        found: list[str] = []
        for phrase in candidates:
            if re.search(re.escape(phrase), joined):
                found.append(phrase)
            if len(found) >= max_items:
                break
        return found

    def _extract_forbidden_openers(self, recent_texts: list[str], max_items: int = 24) -> list[str]:
        """최근 운세에서 문장 시작어(첫 어절)를 추출해 재사용을 금지합니다."""
        if not recent_texts:
            return []

        openers: list[str] = []
        seen = set()

        for text in recent_texts:
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("**행운의 상징:**"):
                    continue
                if "- (" in line:
                    continue

                first_word = re.split(r"\s+", line)[0]
                cleaned = re.sub(r"^[\-*•]+", "", first_word).strip()
                if not cleaned:
                    continue
                key = cleaned.lower()
                if key in seen:
                    continue

                seen.add(key)
                openers.append(cleaned)
                if len(openers) >= max_items:
                    return openers

        return openers

    def _extract_forbidden_scene_seeds(self, recent_texts: list[str], max_items: int = 16) -> list[str]:
        """최근 운세 본문의 장면/소재 시드를 추출해 반복을 억제합니다."""
        if not recent_texts:
            return []

        seeds: list[str] = []
        seen = set()

        for text in recent_texts:
            sections = re.split(r"\n\s*\n", text)
            for section in sections:
                s = section.strip()
                if not s:
                    continue
                if s.startswith("**요약:**") or s.startswith("**행운의 상징:**"):
                    continue

                sentence = re.split(r"[.!?\n]", s)[0].strip()
                sentence = re.sub(r"\s+", " ", sentence)
                if len(sentence) < 8:
                    continue

                seed = sentence[:42]
                if seed in seen:
                    continue

                seen.add(seed)
                seeds.append(seed)
                if len(seeds) >= max_items:
                    return seeds

        return seeds

    def _extract_forbidden_lucky_symbols(self, recent_texts: list[str], max_items: int = 24) -> list[str]:
        """최근 운세의 행운의 상징 키워드를 추출해 재사용을 금지합니다."""
        if not recent_texts:
            return []

        symbols: list[str] = []
        seen = set()

        for text in recent_texts:
            for category, keyword in re.findall(r"([^,\n]+?)-\(([^\)]+)\)", text):
                c = re.sub(r"\s+", " ", category).strip()
                k = re.sub(r"\s+", " ", keyword).strip()
                if not c or not k:
                    continue

                pair = f"{c}-{k}"
                key = pair.lower()
                if key in seen:
                    continue

                seen.add(key)
                symbols.append(pair)
                if len(symbols) >= max_items:
                    return symbols

        return symbols

    def _build_recent_fortune_context(self, recent_texts: list[str], max_chars_per_item: int = 1400) -> str:
        """최근 7일 운세 원문을 프롬프트에 전달하기 위한 텍스트를 구성합니다."""
        if not recent_texts:
            return "- 최근 7일 기록 없음"

        blocks = []
        for idx, text in enumerate(recent_texts, start=1):
            normalized = re.sub(r"\s+", " ", text).strip()
            clipped = normalized[:max_chars_per_item]
            blocks.append(f"[{idx}] {clipped}")
        return "\n".join(blocks)

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

        await self._generate_fortune(ctx, birth_text, today, birth_year, month, day)
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

        await self._generate_fortune(ctx, birth_text, today, birth_year, month, day)
        await self.log(f"{ctx.author}({ctx.author.id})가 관리자 권한으로 강제 운세를 조회함 [길드: {ctx.guild.name}({ctx.guild.id})]")

    async def _generate_fortune(self, ctx, birth_text, today, birth_year, month: int, day: int):
        """공통 운세 생성 로직"""
        today_text = f"{today.year}년 {today.month}월 {today.day}일"
        birth_profile = self._build_birth_profile(birth_year, month, day)
        life_path_text = str(birth_profile["life_path"]) if birth_profile["life_path"] is not None else "미제공"

        recent_texts = fortune_db.get_recent_fortune_texts(ctx.guild.id, ctx.author.id, days=7)
        avoid_phrases = self._extract_avoid_phrases(recent_texts)
        forbidden_openers = self._extract_forbidden_openers(recent_texts)
        forbidden_scene_seeds = self._extract_forbidden_scene_seeds(recent_texts)
        forbidden_lucky_symbols = self._extract_forbidden_lucky_symbols(recent_texts)
        recent_archive_text = self._build_recent_fortune_context(recent_texts)

        avoid_phrases_text = "\n".join([f"- {p}" for p in avoid_phrases]) if avoid_phrases else "- 없음"
        forbidden_openers_text = "\n".join([f"- {p}" for p in forbidden_openers]) if forbidden_openers else "- 없음"
        forbidden_scene_seeds_text = "\n".join([f"- {p}" for p in forbidden_scene_seeds]) if forbidden_scene_seeds else "- 없음"
        forbidden_lucky_symbols_text = "\n".join([f"- {p}" for p in forbidden_lucky_symbols]) if forbidden_lucky_symbols else "- 없음"

        prompt = (
            f"{birth_text} {today_text} 오늘의 운세를 알려줘.\n"
            "아래 개인화 입력을 반드시 반영해.\n"
            f"- 별자리: {birth_profile['zodiac']}\n"
            f"- 월별 핵심 성향: {birth_profile['month_key']}\n" 
            f"- 별자리 핵심 성향: {birth_profile['zodiac_key']}\n"
            f"- 관계 소통 스타일: {birth_profile['relation_style']}\n"
            f"- 오늘 실수 트리거: {birth_profile['mistake_trigger']}\n"
            f"- 행운 루틴 키워드: {birth_profile['luck_anchor']}\n"
            f"- 라이프패스 숫자: {life_path_text}\n\n"
            "최근 7일 운세 원문 아카이브(본문 + 요약 + 행운의 상징):\n"
            f"{recent_archive_text}\n\n"
            "최근 7일 운세에서 반복 회피할 표현 목록:\n"
            f"{avoid_phrases_text}\n\n"
            "최근 7일 대비 금지할 본문 첫 시작어 목록(절대 재사용 금지):\n"
            f"{forbidden_openers_text}\n\n"
            "최근 7일 대비 금지할 본문 소재 시드 목록(절대 재사용 금지):\n"
            f"{forbidden_scene_seeds_text}\n\n"
            "최근 7일 대비 금지할 행운의 상징 목록(절대 재사용 금지):\n"
            f"{forbidden_lucky_symbols_text}"
        )
        variant_instruction = self._get_prompt_variant(ctx.author.id, today)
        waiting_message = None

        try:
            waiting_message = await ctx.reply("운세를 불러오는 중입니다. 잠시만 기다려 주세요.", mention_author=False)

            completion = await self.client.chat.completions.create(
                model="gpt-5.4-nano",
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

                            "【생일 기반 개인화 규칙 - 최우선】\n"
                            "- 사용자 입력의 별자리/월별 성향/관계 스타일/실수 트리거/행운 루틴을 반드시 본문에 녹여 써\n"
                            "- 세 문단 이상 모두 개인화 요소를 각각 1개 이상 반영해\n"
                            "- 생일이 다르면 핵심 상황, 조언, 경고 포인트가 명확히 달라지게 작성해\n"
                            "- 개인화 키워드는 직접 나열하지 말고 자연스러운 문장 안에 녹여 써\n"
                            "- 생년월일 자체 언급은 금지하되, 개인화 해석 결과는 적극 반영해\n\n"

                            "【다양성 강화 규칙 - 매우 중요】\n"
                            f"- {variant_instruction}\n"
                            "- 사용자 프롬프트에 제공된 최근 7일 원문을 반드시 참조해, 본문 소재와 행운의 상징을 엄격히 비중복으로 작성해\n"
                            "- 같은 표현, 문장 구조, 시작 방식 반복을 금지해\n"
                            "- '좋은 기운', '무난한 하루', '작은 행운' 같은 상투 표현은 쓰지 마\n"
                            "- 사용자 프롬프트에 제공된 '반복 회피 표현 목록'과 동일/유사한 문장을 다시 쓰지 마\n"
                            "- 사용자 프롬프트의 '금지할 본문 소재 시드 목록'과 의미가 겹치는 상황/장면을 재사용하지 마\n"
                            "- 사용자 프롬프트의 '금지할 행운의 상징 목록'에 있는 항목-키워드 조합 및 유사 키워드를 재사용하지 마\n"
                            "- 특히 문단 첫 문장과 요약 문장은 과거 7일과 겹치지 않게 새롭게 작성해\n"
                            "- 문단 시작 방식은 매번 다르게 구성해 (상황 제시 / 감각 묘사 / 행동 제안 등)\n"
                            "- 본문 각 문단의 첫 문장 시작어는 서로 달라야 하며, 금지 시작어 목록과도 절대 겹치면 안 돼\n"
                            "- 비유를 쓰더라도 뻔한 비유(cliche)는 피해\n\n"

                            "【출력 형식 - 반드시 준수】\n"
                            "서론 없이 바로 시작해\n\n"

                            "본문 문단 규칙:\n"
                            "- 문단 수는 3~4개\n"
                            "- 각 문단은 3~5줄\n"
                            "- 문단별 주제는 모델이 직접 정하되, 문단끼리 주제와 표현이 겹치지 않게 구성\n"
                            "- 최소 1개 문단에는 일/학업/할 일 진행 관련 장면을, 최소 1개 문단에는 관계/소통 장면을 포함해\n"
                            "- 남은 문단 주제는 컨디션, 소비 습관, 감정 관리, 시간 운영, 공간/환경, 루틴 등에서 자유롭게 선택해\n"
                            "- 각 문단에는 반드시 1개 이상의 구체적 상황과 1개 이상의 행동 가능한 조언을 포함해\n\n"

                            "(빈 줄)\n\n"

                            "**요약:** 한 문장으로 핵심 정리 (자연스럽게).\n\n"

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
                            "- 입력된 개인화 정보를 무시한 일반론 운세 작성 금지\n"
                            "- 요약/행운의 상징에서도 띄어쓰기 철저히 준수\n\n"

                            "【중요】\n"
                            "- 형식은 반드시 지키되, 문장은 매번 새롭게 만들어\n"
                            "- '사람이 쓴 글처럼 자연스러운 흐름'을 최우선으로 해"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=1
            )
            fortune_text = completion.choices[0].message.content.strip()
            today_str = today.strftime("%Y-%m-%d")
            fortune_db.save_fortune_text(ctx.guild.id, ctx.author.id, today_str, fortune_text)
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
