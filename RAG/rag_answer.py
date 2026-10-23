# HeartSignal P2 — /rag-query 답변 조립: 검색 → 근거 블록 → LLM → 출처
# - 메인 파일은 벡터 저장소·LLM을 고르고 이 함수를 호출만 한다 (AGENTS.md 4장)
# - 질문 원문·검색 본문·LLM 답변은 로그에 남기지 않는다 (AGENTS.md 2장 7번)
# - sources 는 답변에 실제로 넣은 청크의 metadata(source, section) 만, 중복 제거

import json
import logging
import os
from pathlib import Path

from langchain_core.messages import HumanMessage
from openai import APITimeoutError

from middleware import ApiError, log_extra

logger = logging.getLogger("heartsignal.rag")

MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "12000"))
NO_EVIDENCE = "확인된 자료가 없습니다. 안전관리자에게 문의하세요."

# 물질 사전: 영문 키(P1 인덱스 metadata.substance) → 한글 이름·화학식·약어 (RAG/prompts/substances.json)
SUBSTANCES = json.loads((Path(__file__).resolve().parent / "prompts" / "substances.json").read_text(encoding="utf-8"))
# 긴 이름부터 맞춰야 '황화수소'가 '수소'로, '메탄올'이 '메탄'으로 잡히지 않는다
_ALIASES = sorted(((alias.lower(), key) for key, v in SUBSTANCES.items() for alias in v["names"]),
                  key=lambda a: -len(a[0]))


def detect_substance(prompt: str) -> str | None:
    lowered = prompt.lower()
    return next((key for alias, key in _ALIASES if alias in lowered), None)


def retrieve(vectorstore, prompt: str, top_k: int) -> tuple[list, str | None]:
    """질문에 물질이 있으면 그 물질 청크(top_k) + 물질 표시 없는 일반 문서(top_k)를 거리순으로 합친다.
    다른 물질의 청크는 뺀다 — 염소 질문에 염산·부타디엔의 '응급조치'가 끼는 문제(평가 1·2행).
    물질 필터는 LangChain FAISS 가 fetch_k 개를 먼저 뽑은 뒤 거르므로 fetch_k 를 인덱스 전체로 준다."""
    key = detect_substance(prompt)
    if key is None:
        return vectorstore.similarity_search_with_score(prompt, k=top_k), None
    total = getattr(getattr(vectorstore, "index", None), "ntotal", None) or 10_000
    focused = vectorstore.similarity_search_with_score(prompt, k=top_k, filter={"substance": key}, fetch_k=total)
    broad = [(d, s) for d, s in vectorstore.similarity_search_with_score(prompt, k=4 * top_k)
             if (d.metadata or {}).get("substance") in (None, "", key)][:top_k]
    seen, merged = set(), []
    for doc, score in sorted(focused + broad, key=lambda pair: pair[1]):
        if doc.page_content in seen:
            continue
        seen.add(doc.page_content)
        merged.append((doc, score))
    return merged[: 2 * top_k], key

# 베이스 프롬프트 그대로 (문구 개선은 평가 1회를 끼워 별도 변경으로 진행)
PROMPT = (
    "아래는 업로드된 PDF에서 검색한 내용입니다. PDF 내용에 근거해 한국어로 답변하세요. "
    "질문이 한 단어 또는 주제명이라면 그 주제를 PDF에 근거해 설명하세요. "
    "PDF에 없는 사실을 만들어 내지 마세요. 근거가 정말 없다면 'N/A'라고 답하세요.\n\n"
    "PDF 검색 내용:\n{context}\n\n"
    "질문: {question}\n\n"
    "답변:"
)


def source_of(doc) -> dict:
    meta = getattr(doc, "metadata", None) or {}
    return {"source": str(meta.get("source", "")), "section": str(meta.get("section", ""))}


def _handoff(hits: int, top_score, substance):
    log_extra(hits=hits, top_score=top_score, substance=substance, handoff=True, needs_review=False)
    return {"response": NO_EVIDENCE, "sources": [], "needs_review": False, "handoff": True}


def answer_with_sources(prompt: str, vectorstore, llm, top_k: int) -> dict:
    """응답 필드(response·sources·needs_review·handoff)를 돌려준다. 로그 필드는 log_extra 로 남긴다.
    handoff=True: 검색 0건 또는 LLM 이 근거 없음(N/A)으로 답한 경우. 이때 sources 는 비운다."""
    docs_scores, substance = retrieve(vectorstore, prompt, top_k)
    # top_score 는 FAISS L2 거리 — 낮을수록 유사 (AGENTS.md 7.5 필드 이름 유지)
    top_score = round(float(docs_scores[0][1]), 4) if docs_scores else None
    if not docs_scores:
        return _handoff(0, top_score, substance)

    blocks, sources, total = [], [], 0
    for i, (doc, _) in enumerate(docs_scores, start=1):
        content = (doc.page_content or "").strip()
        if not content:
            continue
        remaining = MAX_CONTEXT_CHARS - total
        if remaining <= 0:
            break
        excerpt = content[:remaining]
        blocks.append(f"[문서 {i}]\n{excerpt}")
        total += len(excerpt)
        src = source_of(doc)
        if src not in sources:
            sources.append(src)
    if not blocks:
        return _handoff(len(docs_scores), top_score, substance)

    try:
        msg = llm.invoke([HumanMessage(content=PROMPT.format(context="\n\n".join(blocks), question=prompt))])
    except APITimeoutError:
        raise ApiError(503, "LLM_TIMEOUT", "LLM 응답이 지연되고 있습니다.")

    raw = msg.content
    final = (raw if isinstance(raw, str) else str(raw)).strip()
    usage = getattr(msg, "usage_metadata", None) or {}
    handoff = not final or final.upper() == "N/A"
    if handoff:
        final, sources = NO_EVIDENCE, []

    log_extra(hits=len(docs_scores), top_score=top_score, substance=substance, handoff=handoff, needs_review=False,
              tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"))
    logger.debug("rag sources=%s distances=%s", sources, [round(float(s), 4) for _, s in docs_scores])
    return {"response": final, "sources": sources, "needs_review": False, "handoff": handoff}
