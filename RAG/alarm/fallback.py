# 에이전트(LLM)가 없거나 실패해도 경보가 멈추지 않도록 쓰는 고정 문구 (AGENTS.md 2장 4번)
# 문서 근거가 없으므로 출처는 비워 두고 "근거 확인 필요"로 표시한다.
# 문서 근거가 있는 문구는 P2 에이전트(RAG/prompts/templates/)가 채운다.

from .models import SUBSTANCE_NAMES, ZONE_NAMES

NEEDS_SOURCE = "근거 확인 필요"


def _names(alarm: dict) -> tuple[str, str]:
    zone = ZONE_NAMES.get(alarm["zone"], alarm["zone"])
    substance = SUBSTANCE_NAMES.get(alarm["substance"], alarm["substance"])
    return zone, substance


def board_lines(alarm: dict) -> list[str]:
    zone, substance = _names(alarm)
    if alarm["status"] == "cleared":
        return [f"{zone} 경보 해제", "작업 재개는 안전관리자 승인 후", "작업반장 안내에 따르세요"]
    return {
        1: [f"{zone} {substance} 주의", "작업반장 지시에 따라 점검 중", "이상 냄새·소리는 즉시 보고"],
        2: [f"{zone} {substance} 경고", "작업을 중지하고 점화원을 제거하세요", "대피 준비 — 작업반장 지시 대기"],
        3: [f"{substance} 누출 — {zone} 접근 금지", "즉시 바람 반대 방향으로 대피", "집결지에서 인원 점검을 받으세요"],
    }[alarm["stage"]]


def checklist(alarm: dict) -> list[dict]:
    items = {
        1: ["휴대용 검지기로 재측정", "주변 점화원 확인", "작업 계속/일시중지 판단 보고"],
        2: ["작업 중지 지시", "보호구 착용 확인", "대피 경로·집결지 확인", "인원 명단 준비"],
        3: ["대피 유도", "집결지 인원 점검 후 결과 입력", "부상자 확인 후 관리자 보고"],
    }[alarm["stage"]]
    return [{"item": item, "source": None} for item in items]


def guide_card(alarm: dict) -> dict:
    zone, substance = _names(alarm)
    return {
        "immediate": [f"{zone} 출입 통제", "비상조치계획 확인"],
        "ppe": [],
        "first_aid": [],
        "report_info": {"substance": substance, "zone": zone},
        "sources": [],
        "note": NEEDS_SOURCE,
    }


def report_text(alarm: dict) -> str:
    zone, substance = _names(alarm)
    return f"[모의 119 신고] {zone}에서 {substance} 누출 의심, 경보 {alarm['stage']}단계 발령 ({alarm['issued_at']})"
