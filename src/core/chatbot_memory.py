"""
챗봇 장기 기억 모듈 (Pinecone 벡터 DB + Pinecone Inference API)

유저별 과거 대화에서 현재 메시지와 의미적으로 유사한 기억을 검색합니다.
임베딩은 Pinecone 자체 Inference API(multilingual-e5-large)를 사용합니다.
별도 임베딩 API 키 불필요 — PINECONE_API_KEY 하나로 임베딩 + 저장 + 검색 모두 처리합니다.

필요한 환경 변수:
    PINECONE_API_KEY  : Pinecone API 키

필요한 패키지:
    pip install pinecone
"""

import os
import math
import hashlib
from datetime import datetime, timezone

from pinecone import Pinecone, ServerlessSpec
from dotenv import load_dotenv

load_dotenv()

# ── 설정 상수 ────────────────────────────────────────────
PINECONE_INDEX_NAME = "haruka-memory"   # Pinecone 인덱스 이름 (최초 1회 자동 생성)
PINECONE_CLOUD = "aws"                  # 클라우드 프로바이더
PINECONE_REGION = "us-east-1"          # 리전 (Pinecone 무료 플랜 기준)
EMBEDDING_MODEL = "multilingual-e5-large"  # Pinecone 자체 다국어 임베딩 모델
EMBEDDING_DIM = 1024                    # multilingual-e5-large 출력 차원
MAX_MEMORY_RESULTS = 3                  # 검색 시 가져올 최대 기억 수
MIN_RELEVANCE_SCORE = 0.75             # 이 유사도 이하는 무시 (0~1, 감쇠 적용 후 기준)
DECAY_LAMBDA = 0.05                    # 시간 감쇠 계수 (반감기 약 14일)

_pinecone_client: Pinecone | None = None
_pinecone_index = None


# ── 클라이언트 초기화 ─────────────────────────────────────

def _get_pinecone_client() -> Pinecone:
    global _pinecone_client
    if _pinecone_client is None:
        api_key = os.environ.get("PINECONE_API_KEY")
        if not api_key:
            raise RuntimeError("PINECONE_API_KEY 환경 변수가 설정되지 않았습니다.")
        _pinecone_client = Pinecone(api_key=api_key)
    return _pinecone_client


def _get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index

    pc = _get_pinecone_client()

    # 인덱스가 없으면 자동 생성
    existing = [idx.name for idx in pc.list_indexes()]
    if PINECONE_INDEX_NAME not in existing:
        pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=EMBEDDING_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
        )

    _pinecone_index = pc.Index(PINECONE_INDEX_NAME)
    return _pinecone_index


# ── 헬퍼 ─────────────────────────────────────────────────

def _namespace(guild_id: int | str, user_id: int | str) -> str:
    """Pinecone 네임스페이스: 길드+유저 조합으로 기억을 격리합니다."""
    return f"{guild_id}_{user_id}"


def _vector_id(guild_id: int | str, user_id: int | str) -> str:
    """벡터 고유 ID: 타임스탬프 기반으로 생성합니다."""
    ts = datetime.now(timezone.utc).isoformat()
    raw = f"{guild_id}_{user_id}_{ts}"
    return hashlib.md5(raw.encode()).hexdigest()


def _embed_passage(text: str) -> list[float]:
    """저장용 임베딩 (input_type=passage)."""
    pc = _get_pinecone_client()
    result = pc.inference.embed(
        model=EMBEDDING_MODEL,
        inputs=[text],
        parameters={"input_type": "passage", "truncate": "END"},
    )
    return result[0].values


def _embed_query(text: str) -> list[float]:
    """검색용 임베딩 (input_type=query)."""
    pc = _get_pinecone_client()
    result = pc.inference.embed(
        model=EMBEDDING_MODEL,
        inputs=[text],
        parameters={"input_type": "query", "truncate": "END"},
    )
    return result[0].values


def _strip_prefix(content: str) -> str:
    """'[이름:...|ID:...] 내용' 형식에서 순수 내용만 추출합니다."""
    if content.startswith("[") and "]" in content:
        return content.split("]", 1)[-1].strip()
    return content


# ── 공개 API ─────────────────────────────────────────────

async def add_memory(
    guild_id: int | str,
    user_id: int | str,
    role: str,
    content: str,
) -> None:
    """
    유저 메시지를 Pinecone에 장기 기억으로 저장합니다.
    - assistant 응답은 저장하지 않습니다 (유저 발화만 기억).
    - 10자 미만의 짧은 메시지는 저장 가치가 없으므로 건너뜁니다.
    """
    if role != "user":
        return

    content_clean = _strip_prefix(content)
    if len(content_clean) < 10:
        return

    try:
        embedding = _embed_passage(content_clean)
        index = _get_pinecone_index()
        vec_id = _vector_id(guild_id, user_id)

        index.upsert(
            vectors=[{
                "id": vec_id,
                "values": embedding,
                "metadata": {
                    "guild_id": str(guild_id),
                    "user_id": str(user_id),
                    "content": content_clean,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            }],
            namespace=_namespace(guild_id, user_id),
        )
    except Exception as e:
        print(f"[chatbot_memory] add_memory 실패: {e}")


async def search_memory(
    guild_id: int | str,
    user_id: int | str,
    query: str,
    n_results: int = MAX_MEMORY_RESULTS,
) -> list[str]:
    """
    현재 메시지(query)와 의미적으로 유사한 과거 기억을 검색합니다.
    MIN_RELEVANCE_SCORE 미만의 결과는 필터링하여 반환합니다.
    """
    try:
        query_embedding = _embed_query(query)
        index = _get_pinecone_index()

        results = index.query(
            vector=query_embedding,
            top_k=n_results,
            namespace=_namespace(guild_id, user_id),
            include_metadata=True,
        )

        now = datetime.now(timezone.utc)
        scored = []
        for match in results.get("matches", []):
            raw_score = match.get("score", 0.0)
            metadata = match.get("metadata", {})

            # 시간 감쇠 적용: 유효 점수 = 유사도 × e^(-λ × 경과일수)
            created_at_str = metadata.get("created_at", "")
            try:
                created_at = datetime.fromisoformat(created_at_str)
                days_elapsed = (now - created_at).total_seconds() / 86400
            except (ValueError, TypeError):
                days_elapsed = 0.0
            decayed_score = raw_score * math.exp(-DECAY_LAMBDA * days_elapsed)

            if decayed_score >= MIN_RELEVANCE_SCORE:
                mem_content = metadata.get("content", "")
                if mem_content:
                    scored.append((decayed_score, mem_content))

        # 유효 점수 내림차순 정렬 후 내용만 반환
        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored]

    except Exception as e:
        print(f"[chatbot_memory] search_memory 실패: {e}")
        return []


async def clear_memory(
    guild_id: int | str,
    user_id: int | str,
) -> None:
    """특정 유저의 장기 기억 전체를 삭제합니다 (네임스페이스 삭제)."""
    try:
        index = _get_pinecone_index()
        index.delete(
            delete_all=True,
            namespace=_namespace(guild_id, user_id),
        )
    except Exception as e:
        print(f"[chatbot_memory] clear_memory 실패: {e}")


def build_memory_context(memories: list[str]) -> str:
    """
    검색된 기억 목록을 시스템 프롬프트에 삽입할 텍스트로 포맷합니다.
    현재 대화 흐름보다 우선하지 않음을 명시하여 환각을 방지합니다.
    """
    if not memories:
        return ""
    joined = "\n".join(f"- {m}" for m in memories)
    return (
        "\n[장기 기억 — 이 사용자와의 과거 대화에서 현재 맥락과 관련된 내용]\n"
        f"{joined}\n"
        "위 기억은 참고용이며, 현재 대화 흐름보다 우선하지 않는다.\n"
    )