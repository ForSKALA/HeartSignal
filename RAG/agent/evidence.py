# HeartSignal P2 에이전트 — 근거 조회 (임베딩·LLM 없이 메타데이터로 직접 찾는다)
# P1 인덱스의 안전지침 청크는 substance + section("누출 시 대처요령>초기이격거리" 등)이 규칙적이라
# 벡터 검색보다 메타데이터 조회가 정확하고 결정적이다. 안전지침에 항목이 없는 물질(프로판 등)은
# KOSHA MSDS 보완 원문의 대응 항목으로 대체한다. 구역별 절차 근거는 기획서 시나리오 S1~S3 기준.

import re

_DOCS: list = []          # configure() 로 채움. 비어 있으면 모든 조회가 빈 결과 → 도구는 템플릿(fallback)
_CONFIGURED = False

# 용도 → (안전지침 section 접두어들, MSDS section 접두어들)
PURPOSE_SECTIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "isolation": (("누출 시 대처요령>초기이격거리",), ()),
    "protective_distance": (("누출 시 대처요령>방호활동거리",), ()),
    "leak_response": (("누출 시 대처요령>일반적 대처요령", "누출 시 대처요령>방제약품 및 장비"),
                      ("6. 누출사고시 대처방법>가.", "6. 누출사고시 대처방법>다.")),
    "ppe": (("누출 시 대처요령>누출 방지 및 개인보호구",), ("8. 노출방지 및 개인보호구>다.",)),
    "first_aid_inhalation": (("응급조치>흡입",), ("4. 응급조치요령>다.",)),
    "first_aid_skin": (("응급조치>경피",), ("4. 응급조치요령>나.",)),
    "name": (("기본 물질 정보>물질명",), ()),
    "cas": (("기본 물질 정보>CAS번호",), ()),
    "un": (("기본 물질 정보>UN번호",), ()),
    "ghs_signal": (("GHS정보>신호어",), ()),
    "ghs_hazard": (("GHS정보>유해위험문구",), ("2. 유해성·위험성>가.",)),
    "fire": (("폭발 및 화재위험성>소화방법",), ("5. 폭발·화재시 대처방법>가.",)),
}

# 구역 → 단계별 절차 근거 (문서 식별 문자열, 절). 기획서 9장 S1(출하장 프로판)·S2(증류탑 황화철)·S3(밀폐공간)
ZONE_GUIDES: dict[str, dict[str, list[tuple[str, str]]]] = {
    "loading_bay": {
        "respond": [("G-78", "10.2(13)")],          # 출하 중단·시동 정지·점화원 제거
        "resume": [("G-78", "10.2(14)")],           # 가스 감지기 측정 후 작업 진행
    },
    "distillation": {
        "respond": [("P-64", "5.3.2(6)"), ("P-64", "5.2.1(2)")],   # 모니터링 가스, 살수
        "resume": [("P-64", "5.3.2(6)")],
    },
    "confined_tank": {
        "respond": [("E-G-18", "9.1(1)"), ("산업안전보건기준", "제618조(정의)")],   # 진입 금지·적정공기
        "resume": [("산업안전보건기준", "제618조(정의)")],
    },
}


def configure(*stores) -> None:
    """메인 파일이 벡터 저장소(FAISS)를 넘기면 docstore 의 청크 전체를 조회용으로 보관한다."""
    global _DOCS, _CONFIGURED
    docs = []
    for store in stores:
        docstore = getattr(store, "docstore", None)
        docs += list(getattr(docstore, "_dict", {}).values()) if docstore is not None else []
    _DOCS, _CONFIGURED = docs, bool(docs)


def is_configured() -> bool:
    return _CONFIGURED


def _meta(doc) -> dict:
    return getattr(doc, "metadata", None) or {}


def _body(doc) -> str:
    """청크 본문에서 '물질명 | 섹션' 접두어와 섹션 라벨 반복을 제거한다."""
    text = (getattr(doc, "page_content", "") or "").strip()
    head, _, rest = text.partition("\n")
    if "|" in head and rest:          # "제목 | 10.2(13)\n본문" (지침)
        text = rest
    elif "|" in head:                 # "염소 | 기본 물질 정보>CAS번호 7782-50-5" (안전지침 한 줄)
        text = head.split("|", 1)[1]
    text = text.strip()
    section = str(_meta(doc).get("section", ""))
    if section and text.startswith(section):
        text = text[len(section):]
    return re.sub(r"\s+", " ", text).strip()


def source_of(doc) -> dict:
    m = _meta(doc)
    return {"source": str(m.get("source", "")), "section": str(m.get("section", ""))}


def find(substance: str, purpose: str) -> list:
    """물질의 용도별 청크. 안전지침 항목 → 없으면 MSDS 항목. 반환: [(본문, 출처)]"""
    guide_prefixes, msds_prefixes = PURPOSE_SECTIONS[purpose]
    hits = []
    for prefixes, want_msds in ((guide_prefixes, False), (msds_prefixes, True)):
        for doc in _DOCS:
            m = _meta(doc)
            if m.get("substance") != substance:
                continue
            is_msds = "MSDS" in str(m.get("source", ""))
            if is_msds != want_msds:
                continue
            if any(str(m.get("section", "")).startswith(p) for p in prefixes):
                body = _body(doc)
                if body and body != "자료없음":
                    hits.append((body, source_of(doc)))
        if hits:
            break
    return hits


def find_guides(zone: str, phase: str) -> list:
    """구역별 절차 근거 [(본문, 출처)]. phase: respond | resume"""
    wanted = ZONE_GUIDES.get(zone, {}).get(phase, [])
    hits = []
    for doc_key, section in wanted:
        for doc in _DOCS:
            m = _meta(doc)
            if doc_key in str(m.get("source", "")) and str(m.get("section", "")) == section:
                hits.append((_body(doc), source_of(doc)))
                break
    return hits


def first(substance: str, purpose: str) -> tuple[str, dict | None]:
    hits = find(substance, purpose)
    return hits[0] if hits else ("", None)


_DIST = re.compile(r"(소규모|대규모)\s*[:：]?\s*반경\s*(\d+)\s*m")


def isolation_distances(text: str) -> dict:
    """'초기이격거리 • 소규모: 반경 30m • 대규모: 반경 150m' → {'소규모': '30m', '대규모': '150m'}"""
    return {k: f"{v}m" for k, v in _DIST.findall(text)}
