# HeartSignal P2 에이전트 — 지침 카드 상세 섹션 (확장).
# 발령된 물질·구역으로 prompts/guide_sections.json 의 7개 질문을 만들어 RAG 답변(출처 포함)으로 채운다.
# LLM 이 없거나 실패하면 빈 목록 — 전광판·방송·신고는 템플릿으로 이미 나갔으므로 경보는 멈추지 않는다 (AGENTS.md 2장 4번).
# 단계·상태를 바꾸는 코드는 없다. 섹션은 "정리·안내" 결과일 뿐이다.

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger("heartsignal.agent")

SECTION_FILE = Path(__file__).resolve().parent.parent / "prompts" / "guide_sections.json"
_llm = None
_rewrite_llm = None
_stores: tuple = ()
_top_k = 5


def configure_llm(llm, stores, rewrite_llm=None, top_k: int = 5) -> None:
    """메인 파일이 LLM 과 FAISS 저장소(pdf, web …)를 넘긴다. 호출하지 않으면 섹션은 항상 빈 목록."""
    global _llm, _rewrite_llm, _stores, _top_k
    _llm, _rewrite_llm, _stores, _top_k = llm, rewrite_llm, tuple(stores), top_k


def is_llm_configured() -> bool:
    return _llm is not None


def questions(substance: str, zone: str) -> list[dict]:
    spec = json.loads(SECTION_FILE.read_text(encoding="utf-8"))["sections"]
    return [{"id": s["id"], "title": s["title"], "question": s["question"].format(substance=substance, zone=zone)}
            for s in spec]


async def build_sections(substance: str, zone: str) -> list[dict]:
    """7개 질문을 동시에 RAG 에 묻는다. 각 섹션: id·title·question·answer·sources·handoff·needs_review"""
    if _llm is None or not _stores:
        return []
    from rag_answer import answer_with_sources  # RAG 루트 모듈 (서버·테스트 모두 RAG/ 를 경로에 둔다)
    pdf, *web = _stores

    async def one(q: dict) -> dict:
        try:
            r = await asyncio.to_thread(answer_with_sources, q["question"], pdf, _llm, _top_k,
                                        extra_stores=tuple(web), rewrite_llm=_rewrite_llm)
        except Exception as exc:  # 한 섹션 실패가 나머지를 막지 않는다
            logger.warning("guide section %s failed: %s", q["id"], type(exc).__name__)
            return {**q, "answer": None, "sources": [], "handoff": True, "needs_review": False, "error": type(exc).__name__}
        return {**q, "answer": r["response"], "sources": r["sources"], "handoff": r["handoff"], "needs_review": r["needs_review"]}

    return list(await asyncio.gather(*(one(q) for q in questions(substance, zone))))
