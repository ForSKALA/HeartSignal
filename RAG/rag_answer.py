# HeartSignal P2 — /rag-query 답변 조립: 검색 → 근거 블록 → LLM → 출처
# - 메인 파일은 벡터 저장소·LLM을 고르고 이 함수를 호출만 한다 (AGENTS.md 4장)
# - 질문 원문·검색 본문·LLM 답변은 로그에 남기지 않는다 (AGENTS.md 2장 7번)
# - sources 는 답변에 실제로 넣은 청크의 metadata(source, section) 만, 중복 제거

import json
import logging
import os
import re
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


def _searcher(store, query: str, vector):
    """질의 1개당 임베딩 1회: 벡터가 있고 저장소가 지원하면 by_vector 로 검색 (두 저장소에 재사용, 평가 8행)."""
    if vector is not None and hasattr(store, "similarity_search_with_score_by_vector"):
        return lambda **kw: store.similarity_search_with_score_by_vector(vector, **kw)
    return lambda **kw: store.similarity_search_with_score(query, **kw)


def _search_one(store, query: str, top_k: int, key: str | None, vector=None) -> list:
    """저장소 하나에서 검색. 물질이 있으면 그 물질 청크(top_k) + 물질 표시 없는 일반 문서(top_k),
    다른 물질의 청크는 뺀다 — 염소 질문에 염산·부타디엔의 '응급조치'가 끼는 문제(평가 1·2행).
    물질 필터는 LangChain FAISS 가 fetch_k 개를 먼저 뽑은 뒤 거르므로 fetch_k 를 인덱스 전체로 준다."""
    search = _searcher(store, query, vector)
    if key is None:
        return search(k=top_k)
    total = getattr(getattr(store, "index", None), "ntotal", None) or 10_000
    focused = search(k=top_k, filter={"substance": key}, fetch_k=total)
    broad = [(d, s) for d, s in search(k=4 * top_k)
             if (d.metadata or {}).get("substance") in (None, "", key)][:top_k]
    return focused + broad


def _embed(store, query: str):
    fn = getattr(store, "embedding_function", None)
    return fn.embed_query(query) if fn is not None and hasattr(fn, "embed_query") else None


def retrieve(vectorstore, prompt: str, top_k: int, extra_stores=(), rewrites=()) -> tuple[list, str | None]:
    """원문 + 재작성 검색어로 주 저장소 + 보조 저장소(P1 법령 web 인덱스 등)를 모두 검색해 거리순으로 합친다 (중복 제거).
    청크가 짧아(중앙값 84자) 질의 수에 비례해 상한을 늘려도 컨텍스트 비용은 작다."""
    key = detect_substance(prompt)
    queries = [prompt, *rewrites]
    stores = [s for s in (vectorstore, *extra_stores) if s is not None]
    pairs = []
    for query in queries:
        vector = _embed(stores[0], query) if stores else None   # 임베딩 모델은 저장소 공통(OpenAIEmbeddings)
        for store in stores:
            pairs += _search_one(store, query, top_k, key, vector)
    seen, merged = set(), []
    for doc, score in sorted(pairs, key=lambda pair: pair[1]):
        if doc.page_content in seen:
            continue
        seen.add(doc.page_content)
        merged.append((doc, score))
    return merged[: 2 * top_k * len(queries)], key

# 답변 프롬프트 (평가 6행). 베이스 문구에 세 가지를 더했다:
#  - 범위 밖 질문(의료 판단·실시간 측정값·안전보건 외)은 근거가 있어도 'N/A' → handoff (기획서 5.3, 평가 5행 H2 회귀)
#  - 수치·단위는 근거 원문 그대로, 근거 밖 지식 금지
#  - 문장 끝 [문서 n] 표기 → 응답 sources 를 실제 인용한 청크로 좁힌다 (표기는 응답 본문에서 지움)
PROMPT = (
    "아래는 안전보건 문서(KOSHA 기술지침·법령·물질안전지침)에서 검색한 근거 블록입니다. 근거 블록 내용에만 근거해 한국어로 답하세요.\n"
    "규칙:\n"
    "1. 근거에 없는 사실·수치는 쓰지 마세요. 수치와 단위는 근거 원문 그대로 옮기세요.\n"
    "2. 사용한 근거 블록 번호를 문장 끝에 [문서 n] 형식으로 붙이세요.\n"
    "3. 다음 질문에는 근거가 있어도 답하지 말고 'N/A'만 출력하세요: 증상·질병·중독 여부 등 의료적 판단을 구하는 질문, "
    "현재 농도·압력·설비 상태 등 실시간 측정값을 묻는 질문, 산업안전보건과 무관한 질문.\n"
    "4. 근거가 질문에 직접 답하지 못하면 'N/A'만 출력하세요.\n\n"
    "근거 블록:\n{context}\n\n"
    "질문: {question}\n\n"
    "답변:"
)
_CITATION = re.compile(r"\s*\[문서\s*(\d+)\]")


def source_of(doc) -> dict:
    meta = getattr(doc, "metadata", None) or {}
    return {"source": str(meta.get("source", "")), "section": str(meta.get("section", ""))}


# 검색어 재작성: 현장 말투 질문을 지침·MSDS 문체의 검색어로 바꾼다 (평가 4행: 원문 >60위 → 문서 문체 1위).
# 이 호출은 사용자에게 보이는 문장을 만들지 않는다. 답변 생성은 아래 answer_with_sources 에서 근거가 있을 때만 한다.
REWRITE_PROMPT = (
    "다음 현장 질문을 한국 산업안전 기술지침(KOSHA GUIDE)·법령·물질안전지침(MSDS)에서 검색하기 위한 검색어 2개로 바꾸세요. "
    "문서 문체(명사형, 전문용어: 누출, 인화성 물질, 출하작업, 가스 감지기 농도 측정, 응급조치, 노출기준 등)로 쓰고, "
    "물질명이 있으면 유지하세요. 한 줄에 하나씩, 번호·설명 없이 검색어만 쓰세요.\n질문: {question}"
)
MAX_REWRITES = 2


def rewrite_queries(prompt: str, llm) -> list[str]:  # llm: 재작성용(가벼운 모델 권장)
    """재작성 검색어 목록. 실패하면 빈 목록 — 검색은 항상 원문으로는 진행된다."""
    try:
        raw = llm.invoke([HumanMessage(content=REWRITE_PROMPT.format(question=prompt))]).content
    except Exception as exc:  # 재작성 실패가 질의를 막지 않게 한다
        logger.warning("query rewrite failed: %s", type(exc).__name__)
        return []
    lines = [line.strip().lstrip("-•0123456789. )").strip() for line in str(raw).splitlines()]
    return [line for line in lines if line and line != prompt][:MAX_REWRITES]


def _handoff(hits: int, top_score, substance):
    log_extra(hits=hits, top_score=top_score, substance=substance, handoff=True, needs_review=False)
    return {"response": NO_EVIDENCE, "sources": [], "needs_review": False, "handoff": True}


def answer_with_sources(prompt: str, vectorstore, llm, top_k: int, extra_stores=(), rewrite_llm=None) -> dict:
    """응답 필드(response·sources·needs_review·handoff)를 돌려준다. 로그 필드는 log_extra 로 남긴다.
    handoff=True: 검색 0건 또는 LLM 이 근거 없음(N/A)으로 답한 경우. 이때 sources 는 비운다."""
    rewrites = rewrite_queries(prompt, rewrite_llm or llm)
    docs_scores, substance = retrieve(vectorstore, prompt, top_k, extra_stores, rewrites)
    log_extra(rewrites=len(rewrites))
    # top_score 는 FAISS L2 거리 — 낮을수록 유사 (AGENTS.md 7.5 필드 이름 유지)
    top_score = round(float(docs_scores[0][1]), 4) if docs_scores else None
    if not docs_scores:
        return _handoff(0, top_score, substance)

    blocks, sources, by_number, total = [], [], {}, 0
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
        by_number[i] = src
        if src not in sources:
            sources.append(src)
    if not blocks:
        return _handoff(len(docs_scores), top_score, substance)

    try:
        msg = llm.invoke([HumanMessage(content=PROMPT.format(context="\n\n".join(blocks), question=prompt))])
    except APITimeoutError:
        raise ApiError(503, "LLM_TIMEOUT", "LLM 응답이 지연되고 있습니다.")

    raw = msg.content
    text = (raw if isinstance(raw, str) else str(raw)).strip()
    usage = getattr(msg, "usage_metadata", None) or {}
    cited = [by_number[int(n)] for n in _CITATION.findall(text) if int(n) in by_number]
    final = _CITATION.sub("", text).strip()
    handoff = not final or final.upper() == "N/A"
    if handoff:
        final, sources = NO_EVIDENCE, []
    elif cited:  # 인용 표기가 있으면 실제로 쓴 청크의 출처만 (없으면 검색 청크 전체 유지)
        sources = [src for src in sources if src in cited]

    log_extra(hits=len(docs_scores), top_score=top_score, substance=substance, handoff=handoff, needs_review=False,
              tokens_in=usage.get("input_tokens"), tokens_out=usage.get("output_tokens"))
    logger.debug("rag sources=%s distances=%s", sources, [round(float(s), 4) for _, s in docs_scores])
    return {"response": final, "sources": sources, "needs_review": False, "handoff": handoff}
