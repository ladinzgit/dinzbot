# DinzBot (딘즈봇)

DinzBot은 한국어 기반의 다기능 디스코드 봇입니다. **Cog 기반의 모듈형 아키텍처**로 설계되어 있으며, 사용자 친화적인 관리 기능과 AI 연동을 제공합니다

## 🌟 주요 기능

- **🎂 생일 관리 (`Birthday`)**: 사용자의 생일을 등록하고 채널에 자동으로 목록을 업데이트합니다.
- **🔮 오늘의 운세 (`Fortune`)**: FactChat API를 연동하여 하루 한 번 AI 기반 운세를 제공합니다. 관리자 전용 명령어(`?!운세설정`)로 채널 및 알림 시간을 설정할 수 있습니다.
- **🤖 AI 챗봇 (`Chatbot`)**: `gemini-2.5-pro` 모델을 사용하는 AI 챗봇입니다. 사용자별 대화 기억(단기 및 장기)을 통해 친밀도에 따른 다양한 응답을 제공합니다. (지정된 채널에서 자동 응답)
- **🎵 음악 플레이어 (`Music`)**: Lavalink 서버를 활용한 음악 재생 기능입니다. 명령어 없이 지정된 채널에 텍스트를 입력하면 음악을 검색하고 재생합니다. (고정형 단일 Embed 플레이어 UI 제공)

## 🏗️ 아키텍처 및 기술 스택

- **언어 및 프레임워크**: Python 3.10+, `discord.py`
- **데이터 저장소**:
  - `aiosqlite` (비동기 SQLite): 생일, 챗봇 대화 기록
  - JSON 파일: 상태 및 환경 설정
- **AI 연동**: [FactChat (MindLogic)](https://factchat-cloud.mindlogic.ai) - OpenAI 호환 게이트웨이 사용

## ⚙️ 설치 및 실행

### 1. 요구 사항

- Python 3.10 이상
- [Poetry](https://python-poetry.org/) (패키지 관리 및 가상 환경)
- Lavalink 서버 (음악 기능 사용 시 필요, 기본 포트: 2333)

### 2. 의존성 설치

```bash
# Poetry를 이용한 패키지 설치
poetry install
```

### 3. 환경 변수 설정

프로젝트 루트에 `.env` 파일을 생성하고 다음 항목을 작성합니다. (`.env.example` 파일 참고)

```env
DISCORD_BOT_TOKEN=your_bot_token_here
APPLICATION_ID=your_application_id_here
FACTCHAT_API_KEY=your_factchat_api_key_here
GUILD_IDS=123456789012345678,987654321098765432
```

### 4. 봇 실행

```bash
# DinzBot 실행
python main.py
```

## 🛠️ 주요 명령어

봇의 기본 접두사는 `?!` 입니다. (슬래시 명령어 통합 지원)

- **공통**
  - `?!운세` : 오늘의 운세를 확인합니다. (하루 1회)
  - `?!챗봇초기화` : 본인의 챗봇 대화 기록(단기/장기)을 초기화합니다.
- **관리자 전용 (Owner / Guild Admin)**
  - `?!sync` : 슬래시 명령어를 디스코드에 동기화합니다. (봇 소유자 전용)
  - `?!로그채널설정` : 봇의 시스템 로그 채널을 지정합니다.
  - `?!운세설정` : 운세 카테고리 설정 메뉴를 호출합니다.
  - `?!챗봇설정 [채널|채널해제|기록초기화]` : 챗봇 채널 지정 및 기록 관리를 수행합니다.
  - `?!음악설정` : 음악 명령어 채널 지정 및 비활성화를 설정합니다.

## 📂 프로젝트 구조

```text
├── .env                # 환경 변수 화일
├── CLAUDE.md           # 봇 구조 및 AI 어시스턴트용 가이드
├── README.md           # 프로젝트 안내 문서 (현재 파일)
├── main.py             # 봇 실행 진입점 (Entry point)
├── config/             # 기능별 설정(json) 파일 저장소
├── data/               # DB (SQLite) 및 JSON 데이터 파일 저장소
└── src/                # Cog 및 핵심 로직 모듈
    ├── core/           # DB, 인증, 공통 유틸리티
    ├── birthday/       # 생일 알림 기능
    ├── chatbot/        # AI 챗봇 기능
    ├── fortune/        # 운세 기능 
    ├── music/          # Lavalink 연동 음악 기능
    └── utils/          # 시스템 로거, 스케줄러 처리
```
