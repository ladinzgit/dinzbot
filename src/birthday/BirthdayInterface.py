"""
생일 표시 인터페이스 Cog
특정 채널에 생일 정보를 임베드로 표시하고 매일 자정마다 자동 업데이트합니다.
"""

import discord
from discord.ext import commands, tasks
from src.core import birthday_db
from datetime import datetime, timedelta
import json
from pathlib import Path
import pytz
import aiohttp
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
from src.core.admin_utils import GUILD_IDS, only_in_guild, is_guild_admin
from src.chatbot.Chatbot import SYSTEM_PROMPT, Chatbot as ChatbotCog

CONFIG_PATH = Path("config/birthday_config.json")
KST = pytz.timezone("Asia/Seoul")

load_dotenv()


def load_config() -> dict:
    """설정 파일 로드"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    """설정 파일 저장"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


class BirthdayInterface(commands.Cog):
    """생일 표시 인터페이스 Cog"""

    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.environ.get("FACTCHAT_API_KEY")
        self.client = (
            AsyncOpenAI(api_key=self.api_key, base_url=ChatbotCog.BASE_URL)
            if self.api_key
            else None
        )

    @commands.Cog.listener()
    async def on_ready(self):
        pass

    def cog_unload(self):
        """Cog 언로드 시 태스크 종료"""
        pass

    async def cog_load(self):
        """Cog 로드 시 실행"""
        # JSON 파일이 없으면 생성
        if not CONFIG_PATH.exists():
            save_config({})
            print(f"✅ Birthday Interface config initialized at {CONFIG_PATH}")
        print(f"✅ {self.__class__.__name__} loaded successfully!")

        # 스케줄러 cog 가져오기
        scheduler = self.bot.get_cog("Scheduler")
        if scheduler:
            scheduler.schedule_daily(self.midnight_update, 0, 0)
        else:
            print("⚠️ Scheduler cog not found! BirthdayInterface task validation failed.")

    async def log(self, message):
        """Logger cog를 통해 로그 메시지 전송"""
        try:
            logger = self.bot.get_cog('Logger')
            if logger:
                await logger.log(message, title="🎂 생일 시스템 로그", color=discord.Color.purple())
        except Exception as e:
            print(f"❌ {self.__class__.__name__} 로그 전송 중 오류 발생: {e}")

    def get_channel_config(self, guild_id: int):
        """특정 길드의 생일 채널 설정 조회"""
        config = load_config()
        guild_key = str(guild_id)

        if guild_key in config:
            return config[guild_key]
        return None

    def get_celebration_channel_id(self, guild_id: int):
        """특정 길드의 생일 축하 채널 설정 조회"""
        config = load_config()
        guild_key = str(guild_id)
        return config.get(guild_key, {}).get("celebration_channel_id")

    def set_celebration_channel_id(self, guild_id: int, channel_id: int | None):
        """특정 길드의 생일 축하 채널 설정 저장"""
        config = load_config()
        guild_key = str(guild_id)
        config.setdefault(guild_key, {})["celebration_channel_id"] = channel_id
        config[guild_key]["last_updated"] = datetime.now(KST).isoformat()
        save_config(config)

    def set_channel_config(self, guild_id: int, channel_id: int, message_id: int = None):
        """생일 채널 설정 저장"""
        config = load_config()
        guild_key = str(guild_id)

        if guild_key not in config:
            config[guild_key] = {}

        config[guild_key]["guild_id"] = guild_id
        config[guild_key]["channel_id"] = channel_id
        config[guild_key]["message_id"] = message_id
        config[guild_key]["last_updated"] = datetime.now(KST).isoformat()

        save_config(config)

    def set_last_congrats_date(self, guild_id: int, date_str: str):
        """생일 축하 메시지를 보낸 날짜 저장"""
        config = load_config()
        guild_key = str(guild_id)
        config.setdefault(guild_key, {})["last_congrats_date"] = date_str
        config[guild_key]["last_updated"] = datetime.now(KST).isoformat()
        save_config(config)

    def get_last_congrats_date(self, guild_id: int) -> str | None:
        """생일 축하 메시지를 마지막으로 보낸 날짜 조회"""
        config = load_config()
        guild_key = str(guild_id)
        return config.get(guild_key, {}).get("last_congrats_date")

    async def clean_invalid_users(self, guild: discord.Guild):
        """서버에 없는 유저의 생일 정보 삭제"""
        all_birthdays = await birthday_db.get_all_birthdays()
        member_ids = {str(member.id) for member in guild.members}

        deleted_users = []
        for birthday in all_birthdays:
            if birthday["user_id"] not in member_ids:
                await birthday_db.delete_birthday(birthday["user_id"])
                deleted_users.append({
                    "user_id": birthday["user_id"],
                    "month": birthday["month"],
                    "day": birthday["day"]
                })

        return deleted_users

    def calculate_days_until(self, month: int, day: int) -> int:
        """다음 생일까지 남은 일수 계산"""
        now = datetime.now(KST)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        current_year = today.year

        # 올해 생일
        birthday_this_year = KST.localize(datetime(current_year, month, day))

        # 생일이 이미 지났으면 내년 생일로 계산
        if birthday_this_year < today:
            birthday_next = KST.localize(datetime(current_year + 1, month, day))
        else:
            birthday_next = birthday_this_year

        delta = birthday_next - today
        return delta.days

    async def get_today_birthdays(self, guild: discord.Guild) -> list[discord.Member]:
        """오늘 생일인 서버 멤버 목록 조회"""
        now = datetime.now(KST)
        all_birthdays = await birthday_db.get_all_birthdays()
        member_ids = {str(member.id) for member in guild.members}

        today_birthdays = [
            b for b in all_birthdays
            if b["user_id"] in member_ids and b["month"] == now.month and b["day"] == now.day
        ]

        members = []
        for b in today_birthdays:
            member = guild.get_member(int(b["user_id"]))
            if member:
                members.append(member)

        return members

    async def get_weather_summary(self) -> tuple[str, str]:
        """서울 기준 오늘 날씨 요약과 주의 문구를 반환"""
        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=37.5665&longitude=126.9780"
            "&current=temperature_2m&timezone=Asia%2FSeoul"
        )

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        temp = data.get("current", {}).get("temperature_2m")
                        if temp is not None:
                            if temp >= 28:
                                return (
                                    f"오늘 기온은 약 {temp:.1f}도 정도로 더운 편입니다.",
                                    "더위에 지치지 않도록 수분 섭취를 자주 하고, 야외 활동 시 더위 조심하세요.",
                                )
                            if temp <= 5:
                                return (
                                    f"오늘 기온은 약 {temp:.1f}도 정도로 추운 편입니다.",
                                    "체온이 떨어지지 않게 따뜻하게 입고, 감기 조심하세요.",
                                )
                            return (
                                f"오늘 기온은 약 {temp:.1f}도로 무난한 편입니다.",
                                "일교차가 있을 수 있으니 겉옷을 챙겨 컨디션 관리하세요.",
                            )
        except Exception:
            pass

        # 날씨 API 실패 시 계절 기반 안내
        month = datetime.now(KST).month
        if month in (6, 7, 8):
            return (
                "오늘은 여름 날씨로 체감이 더울 수 있습니다.",
                "수분 섭취를 자주 하고, 외출 시 더위 조심하세요.",
            )
        if month in (12, 1, 2):
            return (
                "오늘은 겨울 날씨로 기온이 낮을 수 있습니다.",
                "보온에 신경 쓰고 감기 조심하세요.",
            )
        return (
            "오늘은 계절 특성상 기온 변화가 있을 수 있습니다.",
            "아침저녁 기온 차이를 고려해 건강 관리에 유의하세요.",
        )

    def get_season_song(self) -> str:
        """현재 계절에 어울리는 추천곡 반환"""
        month = datetime.now(KST).month
        if month in (3, 4, 5):
            return "Busker Busker - 벚꽃 엔딩"
        if month in (6, 7, 8):
            return "Dua Lipa - Levitating"
        if month in (9, 10, 11):
            return "AKMU - 어떻게 이별까지 사랑하겠어, 널 사랑하는 거지"
        return "Mariah Carey - All I Want for Christmas Is You"

    async def generate_birthday_letter(
        self,
        guild: discord.Guild,
        birthday_members: list[discord.Member],
        weather_line: str,
        caution_line: str,
        song: str,
    ) -> str:
        """챗봇 페르소나/모델로 생일 축하 본문을 생성"""
        member_names = ", ".join(member.display_name for member in birthday_members)
        today = datetime.now(KST)

        user_prompt = (
            "[작업]\n"
            "오늘 생일인 유저들을 위한 디스코드 축하 메시지 본문을 작성해.\n"
            "메시지는 자연스럽고 따뜻하게 작성하되, 캐릭터 말투 규칙은 시스템 프롬프트를 따르세요.\n\n"
            "[출력 규칙]\n"
            "- 본문만 출력하고 불필요한 설명/머리말/코드블록은 금지\n"
            "- 8~14문장으로 작성\n"
            "- @everyone, 멘션 태그(<@...>)를 직접 출력하지 말 것\n"
            "- 날씨 정보/주의 문구/추천곡을 자연스럽게 녹여 넣을 것\n"
            "- 마지막 문장은 생일 축하 마무리로 끝낼 것\n\n"
            "[상황 정보]\n"
            f"- 길드명: {guild.name}\n"
            f"- 오늘 날짜: {today.year}년 {today.month}월 {today.day}일\n"
            f"- 생일 대상 표시명: {member_names}\n"
            f"- 날씨 요약: {weather_line}\n"
            f"- 건강 주의 문구: {caution_line}\n"
            f"- 계절 추천곡: {song}\n"
        )

        fallback = (
            f"오늘은 {today.year}년 {today.month}월 {today.day}일이야. "
            f"{member_names} 생일 진심으로 축하해. "
            "새로운 한 해를 시작하는 오늘이 기분 좋은 하루가 되었으면 좋겠어. "
            f"{weather_line} {caution_line} "
            f"오늘 추천곡은 {song}이야. "
            "좋은 사람들과 즐겁게 보내고, 앞으로의 한 해도 건강하고 안전하게 잘 보내길 바랄게."
        )

        if not self.client:
            return fallback

        try:
            completion = await self.client.chat.completions.create(
                model=ChatbotCog.MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                extra_body={"thinking_level": "low"},
            )
            if completion.choices:
                content = completion.choices[0].message.content
                if isinstance(content, str) and content.strip():
                    return content.strip()
        except Exception as e:
            await self.log(
                f"생일 축하문 LLM 생성 실패: {e} "
                f"[길드: {guild.name}({guild.id}), 대상: {', '.join(str(m.id) for m in birthday_members)}]"
            )

        return fallback

    async def send_birthday_congratulation(self, guild: discord.Guild, force: bool = False):
        """오늘 생일인 유저에게 장문 축하 메시지를 전송"""
        birthday_members = await self.get_today_birthdays(guild)
        if not birthday_members:
            return

        today_str = datetime.now(KST).strftime("%Y-%m-%d")
        if not force and self.get_last_congrats_date(guild.id) == today_str:
            return

        channel_id = self.get_celebration_channel_id(guild.id)
        if not channel_id:
            await self.log(
                f"생일 축하채널이 설정되지 않아 축하 메시지를 전송하지 못함 "
                f"[길드: {guild.name}({guild.id})]"
            )
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            await self.log(
                f"생일 축하채널을 찾을 수 없음 "
                f"[길드: {guild.name}({guild.id}), 채널 ID: {channel_id}]"
            )
            return

        weather_line, caution_line = await self.get_weather_summary()
        song = self.get_season_song()
        member_mentions = " ".join(member.mention for member in birthday_members)
        letter_body = await self.generate_birthday_letter(
            guild=guild,
            birthday_members=birthday_members,
            weather_line=weather_line,
            caution_line=caution_line,
            song=song,
        )
        message_content = f"@everyone {member_mentions}\n{letter_body}".strip()

        try:
            await channel.send(
                message_content,
                allowed_mentions=discord.AllowedMentions(everyone=True, users=True, roles=False),
            )
            self.set_last_congrats_date(guild.id, today_str)
            await self.log(
                f"생일 축하 메시지 전송 완료 [길드: {guild.name}({guild.id}), 채널: {channel.name}({channel.id}), 대상: {', '.join(str(m.id) for m in birthday_members)}]"
            )
        except Exception as e:
            await self.log(
                f"생일 축하 메시지 전송 실패: {e} "
                f"[길드: {guild.name}({guild.id}), 채널 ID: {channel_id}]"
            )

    async def create_birthday_message(self, guild: discord.Guild) -> str:
        """생일 정보 메시지 생성 (Markdown 형식)"""
        now = datetime.now(KST)
        today_month = now.month
        today_day = now.day

        # 모든 생일 정보 조회
        all_birthdays = await birthday_db.get_all_birthdays()

        # 서버 멤버만 필터링
        member_ids = {str(member.id) for member in guild.members}
        valid_birthdays = [b for b in all_birthdays if b["user_id"] in member_ids]

        # 오늘 생일인 사람들
        today_birthdays = [b for b in valid_birthdays if b["month"] == today_month and b["day"] == today_day]

        # 가장 가까운 생일과 D-Day 계산 (같은 D-Day면 모두 포함)
        min_days = float('inf')
        for birthday in valid_birthdays:
            days = self.calculate_days_until(birthday["month"], birthday["day"])
            if 0 < days < min_days:  # 오늘은 제외
                min_days = days

        closest_birthdays = []
        if min_days != float('inf'):
            for birthday in valid_birthdays:
                days = self.calculate_days_until(birthday["month"], birthday["day"])
                if days == min_days and days > 0:
                    closest_birthdays.append(birthday)

        # 마지막으로 지나간 생일 (가장 최근에 생일이 지난 사람) - 같은 날짜면 모두 포함
        min_days_passed = float('inf')
        for birthday in valid_birthdays:
            days_until = self.calculate_days_until(birthday["month"], birthday["day"])
            # days_until이 0이면 오늘 생일이므로 제외
            if days_until == 0:
                continue

            # 지나간 생일까지의 일수 계산 (365 - days_until)
            days_passed = 365 - days_until

            if days_passed < min_days_passed:
                min_days_passed = days_passed

        last_birthdays = []
        if min_days_passed != float('inf'):
            for birthday in valid_birthdays:
                days_until = self.calculate_days_until(birthday["month"], birthday["day"])
                if days_until == 0:
                    continue
                days_passed = 365 - days_until
                if days_passed == min_days_passed:
                    last_birthdays.append(birthday)

        # 이번 달 생일 리스트
        this_month_birthdays = sorted(
            [b for b in valid_birthdays if b["month"] == today_month],
            key=lambda x: x["day"]
        )

        # 메시지 생성 (Markdown 형식)
        message_parts = []

        # 제목 및 날짜
        message_parts.append("**🎂 생일 달력**")
        message_parts.append(f"-# {now.year}년 {now.month}월 {now.day}일\n")

        # 오늘 생일 (있을 경우에만 표시)
        if today_birthdays:
            message_parts.append(f"## 🎉 오늘의 생일")
            message_parts.append(f"> -# **{today_month}월 {today_day}일**")
            for b in today_birthdays:
                member = guild.get_member(int(b["user_id"]))
                if member:
                    message_parts.append(f"> {member.mention}")
            message_parts.append("")
            message_parts.append("──────────────────\n")

        # 다가오는 생일
        message_parts.append("## 📅 다가오는 생일")
        if closest_birthdays:
            cb = closest_birthdays[0]
            message_parts.append(f"> -# **{cb['month']}월 {cb['day']}일** (D-{min_days})")
            for b in closest_birthdays:
                member = guild.get_member(int(b["user_id"]))
                if member:
                    message_parts.append(f"> {member.mention}")
            message_parts.append("")
        else:
            message_parts.append("> 예정된 생일이 없습니다.\n")

        # 이번 달 생일 리스트
        message_parts.append(f"## 📋 {today_month}월 생일")
        if this_month_birthdays:
            month_list = []
            last_day = 0
            for birthday in this_month_birthdays:
                member = guild.get_member(int(birthday["user_id"]))

                if member:
                    if birthday['day'] != last_day:  # 중복일 경우 날짜는 한 번만 표시
                        is_today = "🎂" if birthday["day"] == today_day else "·"
                        message_parts.append(f"> -# {is_today} **{birthday['month']}월 {birthday['day']}일**")
                        last_day = birthday['day']

                    month_list.append(f"> {member.mention}")

                if month_list:
                    message_parts.append("\n".join(month_list))
                    month_list = []
                else:
                    message_parts.append("> 이번 달 생일이 없습니다.\n")
        else:
            message_parts.append("> 이번 달 생일이 없습니다.\n")

        # 푸터
        message_parts.append("\n-# 매일 자정에 자동으로 업데이트됩니다.")

        return "\n".join(message_parts)

    async def update_birthday_message(self, guild: discord.Guild):
        """생일 메시지 업데이트"""
        config = self.get_channel_config(guild.id)
        if not config:
            return

        channel = guild.get_channel(config["channel_id"])
        if not channel:
            await self.log(f"생일 채널을 찾을 수 없음 [길드: {guild.name}({guild.id}), 채널 ID: {config['channel_id']}]")
            return

        # 서버에 없는 유저 정리
        deleted_users = await self.clean_invalid_users(guild)

        # 메시지 생성
        message_content = await self.create_birthday_message(guild)

        try:
            message = None      # 메시지 객체
            resend = False      # 새롭게 전송 여부

            # 기존 메시지가 있는 경우 수정
            if config.get("message_id"):
                try:
                    message = await channel.fetch_message(config["message_id"])
                    await message.edit(content=message_content)
                except discord.NotFound:
                    # 메시지가 삭제된 경우, 새로 전송
                    resend = True
                except Exception as e:
                    # 그 외 오류 (권한 문제 등), 로그 남기고 새로 전송
                    await self.log(f"메시지 수정 실패 ({e}), 새로 전송 [길드: {guild.name}({guild.id})]")
                    resend = True
            else:
                resend = True

            # 메시지를 새로 보내야 하는 경우 (신규, 수정실패, 삭제)
            if resend:
                # 기존 메시지 ID가 있다면 삭제 시도
                if config.get("message_id"):
                    try:
                        old_msg = await channel.fetch_message(config["message_id"])
                        await old_msg.delete()
                    except:
                        pass

                message = await channel.send(message_content)
                self.set_channel_config(guild.id, channel.id, message.id)

            # 로그 메시지 생성
            log_msg = f"생일 메시지 갱신 완료 [길드: {guild.name}({guild.id}), 채널: {channel.name}({channel.id})]"

            # 삭제된 유저 정보 추가
            if deleted_users:
                deleted_info = ", ".join([f"{u['user_id']}({u['month']}/{u['day']})" for u in deleted_users])
                log_msg += f" | 서버를 떠난 {len(deleted_users)}명의 생일 정보 삭제: {deleted_info}"

            await self.log(log_msg)

        except Exception as e:
            await self.log(f"생일 메시지 갱신 실패: {e} [길드: {guild.name}({guild.id})]")

    async def midnight_update(self):
        """매일 자정에 모든 길드의 생일 메시지 업데이트"""
        # 스케줄러에 의해 호출됨
        for guild_id in GUILD_IDS:
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self.update_birthday_message(guild)
                await self.send_birthday_congratulation(guild)

    @commands.group(name="생일설정", invoke_without_command=True)
    @only_in_guild()
    @commands.has_permissions(administrator=True)
    async def birthday_setup(self, ctx):
        """생일 표시 설정 명령어 그룹"""
        embed = discord.Embed(
            title="🎂 생일 표시 설정",
            colour=discord.Colour.from_rgb(151, 214, 181)
        )
        embed.add_field(
            name="관리자 전용 명령어",
            value=(
                "`?!생일설정 채널등록 [채널]` : 생일 표시 채널을 설정합니다. (채널 미입력 시 현재 채널)\n"
                "`?!생일설정 축하채널 [채널]` : 생일 축하 메시지를 전송할 채널을 설정합니다. (채널 미입력 시 현재 채널)\n"
                "`?!생일설정 강제갱신` : 서버 멤버 검증 및 생일 메시지를 강제로 갱신합니다.\n"
            ),
            inline=False
        )
        embed.set_footer(
            text=f"요청자: {ctx.author}",
            icon_url=ctx.author.display_avatar.url
        )
        embed.timestamp = ctx.message.created_at

        await ctx.reply(embed=embed)

    @birthday_setup.command(name="채널등록")
    @only_in_guild()
    @commands.has_permissions(administrator=True)
    async def register_channel(self, ctx, channel: discord.TextChannel = None):
        """생일 표시 채널 등록"""
        target_channel = channel or ctx.channel

        # 기존 메시지 확인 및 삭제
        config = self.get_channel_config(ctx.guild.id)
        if config and config.get("message_id"):
            try:
                old_channel = ctx.guild.get_channel(config["channel_id"])
                if old_channel:
                    old_message = await old_channel.fetch_message(config["message_id"])
                    await old_message.delete()
            except:
                pass

        # 새 채널 설정
        self.set_channel_config(ctx.guild.id, target_channel.id)

        # 서버에 없는 유저 정리
        deleted_users = await self.clean_invalid_users(ctx.guild)

        # 생일 메시지 생성
        message_content = await self.create_birthday_message(ctx.guild)
        message = await target_channel.send(message_content)
        self.set_channel_config(ctx.guild.id, target_channel.id, message.id)

        embed = discord.Embed(
            title="🎂 생일 채널 등록 완료",
            description=f"{target_channel.mention}에 생일 달력을 게시했습니다.\n매일 자정마다 자동으로 업데이트됩니다.",
            colour=discord.Colour.from_rgb(151, 214, 181)
        )
        embed.set_footer(
            text=f"요청자: {ctx.author}",
            icon_url=ctx.author.display_avatar.url
        )
        embed.timestamp = ctx.message.created_at

        await ctx.reply(embed=embed)

        # 로그 메시지 생성
        log_msg = f"{ctx.author}({ctx.author.id})이 생일 채널을 {target_channel.name}({target_channel.id})로 등록함. [길드: {ctx.guild.name}({ctx.guild.id})]]"
        if deleted_users:
            deleted_info = ", ".join([f"{u['user_id']}({u['month']}/{u['day']})" for u in deleted_users])
            log_msg += f" | 서버를 떠난 {len(deleted_users)}명의 생일 정보 삭제: {deleted_info}"

        await self.log(log_msg)

    @birthday_setup.command(name="축하채널")
    @only_in_guild()
    @commands.has_permissions(administrator=True)
    async def set_celebration_channel(self, ctx, channel: discord.TextChannel = None):
        """생일 축하 채널 등록"""
        target_channel = channel or ctx.channel
        self.set_celebration_channel_id(ctx.guild.id, target_channel.id)

        embed = discord.Embed(
            title="생일 축하채널 설정 완료",
            description=(
                f"{target_channel.mention} 채널을 생일 축하채널로 설정했습니다.\n"
                "자정 또는 강제갱신 시 오늘 생일인 유저가 있으면 @everyone과 함께 축하 메시지를 전송합니다."
            ),
            colour=discord.Colour.from_rgb(151, 214, 181),
        )
        embed.set_footer(
            text=f"요청자: {ctx.author}",
            icon_url=ctx.author.display_avatar.url
        )
        embed.timestamp = ctx.message.created_at

        await ctx.reply(embed=embed)
        await self.log(
            f"{ctx.author}({ctx.author.id})이 생일 축하채널을 {target_channel.name}({target_channel.id})로 설정함 "
            f"[길드: {ctx.guild.name}({ctx.guild.id})]"
        )

    @birthday_setup.command(name="강제갱신")
    @only_in_guild()
    @commands.has_permissions(administrator=True)
    async def force_refresh(self, ctx):
        """서버 멤버 검증 및 생일 메시지 강제 갱신"""
        config = self.get_channel_config(ctx.guild.id)
        if not config:
            embed = discord.Embed(
                title="🎂 강제갱신 실패",
                description="`*생일설정 채널등록` 명령어로 채널을 먼저 등록해 주세요.",
                colour=discord.Colour.from_rgb(151, 214, 181)
            )
            embed.set_footer(
                text=f"요청자: {ctx.author}",
                icon_url=ctx.author.display_avatar.url
            )
            embed.timestamp = ctx.message.created_at

            await ctx.reply(embed=embed)
            return

        # 서버에 없는 유저 정리
        deleted_users = await self.clean_invalid_users(ctx.guild)

        # 생일 메시지 업데이트
        await self.update_birthday_message(ctx.guild)
        await self.send_birthday_congratulation(ctx.guild, force=True)

        description = "서버 멤버 검증 및 생일 달력 갱신을 완료했습니다."
        if deleted_users:
            description += f"\n서버를 떠난 멤버 {len(deleted_users)}명의 생일 정보를 삭제했습니다."
        description += "\n오늘 생일인 유저가 있고 축하채널이 설정되어 있으면 축하 메시지를 전송했습니다."

        embed = discord.Embed(
            title="🎂 강제갱신 완료",
            description=description,
            colour=discord.Colour.from_rgb(151, 214, 181)
        )
        embed.set_footer(
            text=f"요청자: {ctx.author}",
            icon_url=ctx.author.display_avatar.url
        )
        embed.timestamp = ctx.message.created_at

        await ctx.reply(embed=embed)

        # 로그 메시지 생성
        log_msg = f"{ctx.author}({ctx.author.id})이 생일 메시지를 강제갱신함. [길드: {ctx.guild.name}({ctx.guild.id})]]"
        if deleted_users:
            deleted_info = ", ".join([f"{u['user_id']}({u['month']}/{u['day']})" for u in deleted_users])
            log_msg += f" | 삭제된 유저 {len(deleted_users)}명: {deleted_info}"

        await self.log(log_msg)


async def setup(bot):
    """Cog 설정"""
    await bot.add_cog(BirthdayInterface(bot))
