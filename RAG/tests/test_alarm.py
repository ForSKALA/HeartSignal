# [P3] 경보 API 테스트: 발령 admin 전용, 보류된 신고 미발송, 자동 해제 없음, 에이전트 경계
import time

import pytest
from fastapi.testclient import TestClient

from conftest import make_token

S1 = {"zone": "loading_bay", "substance": "propane", "stage": 3, "note": "3번 출하대"}


@pytest.fixture
def ac(rag_module, monkeypatch):
    """경보 테스트용 클라이언트. with 블록 안에서 백그라운드 작업(타이머·에이전트)이 계속 돈다."""
    from alarm import agent_bridge, store

    store.reset()
    monkeypatch.setattr(store, "REPORT_HOLD_S", 0.4)
    monkeypatch.setattr(agent_bridge, "run_agent", None)
    with TestClient(rag_module.app) as c:
        yield c
    store.reset()


def as_role(c, role, sub=None):
    c.cookies.set("ACCESS_TOKEN", make_token(role, sub=sub or {"admin": "1", "foreman": "2", "worker": "3"}[role]))
    return c


def wait_until(fn, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


def issue(c, **overrides):
    res = as_role(c, "admin").post("/alarm", json={**S1, **overrides})
    assert res.status_code == 201, res.text
    return res.json()


# ---------- 권한 ----------

def test_issue_requires_login(ac):
    res = ac.post("/alarm", json=S1)
    assert res.status_code == 401 and res.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("role", ["worker", "foreman"])
def test_issue_non_admin_403(ac, role):
    res = as_role(ac, role).post("/alarm", json=S1)
    assert res.status_code == 403 and res.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("body", [
    {**S1, "zone": "office"},
    {**S1, "stage": 0},
    {**S1, "stage": 4},
    {**S1, "substance": "Propane!"},
    {"zone": "loading_bay", "stage": 3},
])
def test_issue_validation_422(ac, body):
    res = as_role(ac, "admin").post("/alarm", json=body)
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_headcount_only_foreman(ac):
    alarm = issue(ac)
    for role in ["worker", "admin"]:
        res = as_role(ac, role).post(f"/alarm/{alarm['alarm_id']}/headcount", json={"checked": 1, "total": 1})
        assert res.status_code == 403
    res = as_role(ac, "foreman").post(f"/alarm/{alarm['alarm_id']}/headcount", json={"checked": 3, "total": 2})
    assert res.status_code == 422


@pytest.mark.parametrize("path", ["hold-report", "clear"])
def test_hold_and_clear_only_admin(ac, path):
    alarm = issue(ac)
    for role in ["worker", "foreman"]:
        assert as_role(ac, role).post(f"/alarm/{alarm['alarm_id']}/{path}").status_code == 403


# ---------- 발령·조회 ----------

def test_issue_s1_creates_alarm_with_template_board(ac):
    alarm = issue(ac)
    assert alarm["alarm_id"].startswith("al-")
    assert alarm["status"] == "active" and alarm["stage"] == 3 and alarm["issued_by"] == "1"
    # 에이전트 결과 전에도 전광판·체크리스트가 비어 있지 않다 (LLM 없이 동작)
    assert len(alarm["board"]["lines"]) >= 3
    assert alarm["checklist"]
    assert alarm["report"]["status"] == "pending" and alarm["report"]["send_at"]


def test_status_and_detail_for_any_logged_in_user(ac):
    alarm = issue(ac)
    res = as_role(ac, "worker").get("/alarm/status")
    assert res.status_code == 200
    assert [a["alarm_id"] for a in res.json()["alarms"]] == [alarm["alarm_id"]]
    assert as_role(ac, "worker").get(f"/alarm/{alarm['alarm_id']}").json()["alarm_id"] == alarm["alarm_id"]
    res = as_role(ac, "worker").get("/alarm/al-nope")
    assert res.status_code == 404 and res.json()["error"]["code"] == "NOT_FOUND"


def test_stage_below_3_has_no_119_report(ac):
    alarm = issue(ac, stage=2)
    assert alarm["report"] is None
    res = as_role(ac, "admin").post(f"/alarm/{alarm['alarm_id']}/hold-report")
    assert res.status_code == 409 and res.json()["error"]["code"] == "CONFLICT"


# ---------- 119 보류 ----------

def test_report_sent_after_hold_window(ac):
    alarm = issue(ac)
    aid = alarm["alarm_id"]
    assert wait_until(lambda: as_role(ac, "admin").get(f"/alarm/{aid}").json()["report"]["status"] == "sent")
    res = as_role(ac, "admin").post(f"/alarm/{aid}/hold-report")
    assert res.status_code == 409


def test_held_report_is_never_sent(ac):
    alarm = issue(ac)
    aid = alarm["alarm_id"]
    res = as_role(ac, "admin").post(f"/alarm/{aid}/hold-report")
    assert res.status_code == 200 and res.json()["report"]["status"] == "held"
    time.sleep(0.8)  # 보류 시간(0.4초)의 2배
    assert as_role(ac, "admin").get(f"/alarm/{aid}").json()["report"]["status"] == "held"
    # 다시 보류해도 그대로
    assert as_role(ac, "admin").post(f"/alarm/{aid}/hold-report").json()["report"]["status"] == "held"


def test_headcount_reflected_in_report_and_followup(ac):
    aid = issue(ac)["alarm_id"]
    res = as_role(ac, "foreman").post(f"/alarm/{aid}/headcount", json={"checked": 11, "total": 12})
    assert res.json()["headcount"] == {"checked": 11, "total": 12}
    assert res.json()["report"]["headcount"] == "11/12"
    assert wait_until(lambda: as_role(ac, "admin").get(f"/alarm/{aid}").json()["report"]["status"] == "sent")
    res = as_role(ac, "foreman").post(f"/alarm/{aid}/headcount", json={"checked": 12, "total": 12})
    assert res.json()["report"]["followups"][-1]["headcount"] == "12/12"


# ---------- 해제 ----------

def test_no_auto_clear(ac):
    aid = issue(ac)["alarm_id"]
    time.sleep(0.8)
    assert as_role(ac, "worker").get(f"/alarm/{aid}").json()["status"] == "active"


def test_clear_by_admin(ac):
    aid = issue(ac)["alarm_id"]
    res = as_role(ac, "admin").post(f"/alarm/{aid}/clear", json={"note": "오경보"})
    body = res.json()
    assert res.status_code == 200 and body["status"] == "cleared" and body["cleared_by"] == "1"
    # 해제 전 발송되지 않은 신고는 보내지 않는다
    assert body["report"]["status"] == "held"
    time.sleep(0.8)
    assert as_role(ac, "admin").get(f"/alarm/{aid}").json()["report"]["status"] == "held"
    assert as_role(ac, "worker").get("/alarm/status").json()["alarms"] == []
    assert as_role(ac, "admin").post(f"/alarm/{aid}/clear").status_code == 409
    assert as_role(ac, "foreman").post(f"/alarm/{aid}/headcount", json={"checked": 1, "total": 1}).status_code == 409


# ---------- 전광판 ----------

def test_board_no_login_and_empty_when_no_alarm(ac):
    ac.cookies.clear()
    res = ac.get("/board/current")
    assert res.status_code == 200 and res.json()["lines"] == []


def test_board_shows_highest_stage_and_filters_zone(ac):
    issue(ac, stage=1, zone="distillation", substance="sulfur_dioxide")
    s1 = issue(ac)
    ac.cookies.clear()
    whole = ac.get("/board/current").json()
    assert whole["alarm_id"] == s1["alarm_id"] and whole["stage"] == 3 and whole["lines"]
    dist = ac.get("/board/current", params={"zone": "distillation"}).json()
    assert dist["stage"] == 1 and dist["zone"] == "distillation"
    assert ac.get("/board/current", params={"zone": "office"}).status_code == 422


def test_board_shows_clear_message_after_clear(ac):
    aid = issue(ac)["alarm_id"]
    as_role(ac, "admin").post(f"/alarm/{aid}/clear")
    ac.cookies.clear()
    board = ac.get("/board/current", params={"zone": "loading_bay"}).json()
    assert board["status"] == "cleared" and "해제" in board["lines"][0]


# ---------- 에이전트 경계 ----------

def test_agent_not_installed_records_fallback(ac):
    aid = issue(ac)["alarm_id"]
    assert wait_until(lambda: as_role(ac, "admin").get(f"/alarm/{aid}").json()["actions"])
    action = as_role(ac, "admin").get(f"/alarm/{aid}").json()["actions"][0]
    assert action["fallback"] is True and action["reason"] == "agent_not_installed"


def test_agent_cannot_change_stage_status_or_report_status(ac, monkeypatch):
    from alarm import agent_bridge

    async def evil_agent(alarm):
        # 사본을 고쳐도 저장소에는 반영되지 않아야 한다
        alarm["stage"] = 1
        alarm["status"] = "cleared"
        return [
            {"tool": "display_board", "ok": True, "fallback": False, "ts": "t",
             "output": {"lines": ["근거 문구"], "source": {"source": "KOSHA GUIDE G-78-2021", "section": "10.2(13)"},
                        "stage": 1}},
            {"tool": "report_119", "ok": True, "fallback": False, "ts": "t",
             "output": {"text": "신고문", "sources": [], "status": "sent"}},
        ]

    monkeypatch.setattr(agent_bridge, "run_agent", evil_agent)
    aid = issue(ac)["alarm_id"]
    assert wait_until(lambda: len(as_role(ac, "admin").get(f"/alarm/{aid}").json()["actions"]) == 2)
    alarm = as_role(ac, "admin").get(f"/alarm/{aid}").json()
    assert alarm["stage"] == 3 and alarm["status"] == "active"
    assert alarm["report"]["status"] == "pending" and alarm["report"]["text"] == "신고문"
    assert alarm["board"]["lines"] == ["근거 문구"]
    assert all("output" not in a for a in alarm["actions"])


def test_agent_failure_keeps_template(ac, monkeypatch):
    from alarm import agent_bridge

    async def broken_agent(alarm):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(agent_bridge, "run_agent", broken_agent)
    alarm = issue(ac)
    aid = alarm["alarm_id"]
    assert wait_until(lambda: as_role(ac, "admin").get(f"/alarm/{aid}").json()["actions"])
    after = as_role(ac, "admin").get(f"/alarm/{aid}").json()
    assert after["actions"][0]["fallback"] is True and after["actions"][0]["reason"] == "RuntimeError"
    assert after["board"] == alarm["board"]


def test_late_issue_result_after_clear_is_discarded(ac, monkeypatch):
    import asyncio

    from alarm import agent_bridge

    async def slow_agent(alarm):
        if alarm["status"] == "active":
            await asyncio.sleep(0.3)
            return [{"tool": "display_board", "ok": True, "fallback": False, "ts": "t",
                     "output": {"lines": ["늦은 발령 문구"], "source": None}}]
        return []

    monkeypatch.setattr(agent_bridge, "run_agent", slow_agent)
    aid = issue(ac)["alarm_id"]
    as_role(ac, "admin").post(f"/alarm/{aid}/clear")
    time.sleep(0.6)
    alarm = as_role(ac, "admin").get(f"/alarm/{aid}").json()
    assert alarm["status"] == "cleared" and "해제" in alarm["board"]["lines"][0]


# ---------- 리뷰 반영 (PR #10): 출력 형태 검사, import 오류 구분 ----------

def _run_with_agent(ac, monkeypatch, actions):
    from alarm import agent_bridge

    async def fake_agent(alarm):
        return actions

    monkeypatch.setattr(agent_bridge, "run_agent", fake_agent)
    alarm = issue(ac)
    aid = alarm["alarm_id"]
    assert wait_until(lambda: len(as_role(ac, "admin").get(f"/alarm/{aid}").json()["actions"]) == len(actions))
    return alarm, as_role(ac, "admin").get(f"/alarm/{aid}").json()


@pytest.mark.parametrize("tool,output", [
    ("display_board", "프로판 누출"),
    ("display_board", {"lines": "한 줄 문자열"}),
    ("display_board", {"lines": []}),
    ("display_board", {"lines": ["a", 3]}),
    ("display_board", {"lines": ["a"], "source": "KOSHA"}),
    ("notify_foreman", [{"item": "x"}]),
    ("notify_foreman", {"checklist": [{"no_item": 1}]}),
    ("notify_manager", ["not", "dict"]),
    ("report_119", {"sources": []}),
    ("build_briefing", "text"),
])
def test_bad_agent_output_keeps_template_and_board_alive(ac, monkeypatch, tool, output):
    before, after = _run_with_agent(ac, monkeypatch, [{"tool": tool, "ok": True, "fallback": False, "ts": "t", "output": output}])
    action = after["actions"][0]
    assert action["ok"] is False and action["fallback"] is True and action["reason"] == "bad_output"
    for field in ["board", "guide_card", "checklist", "briefing"]:
        assert after[field] == before[field]
    assert after["report"]["text"] == before["report"]["text"]
    ac.cookies.clear()
    res = ac.get("/board/current")
    assert res.status_code == 200 and isinstance(res.json()["lines"], list) and res.json()["lines"]


def test_p2_output_format_is_applied(ac, monkeypatch):
    src = {"source": "KOSHA GUIDE G-78-2021", "section": "10.2(13)"}
    actions = [
        {"tool": "display_board", "ok": True, "fallback": False, "ts": "t", "sources": [src],
         "output": {"lines": ["1", "2", "3", "4", "5"], "source": src}},
        {"tool": "notify_foreman", "ok": True, "fallback": False, "ts": "t",
         "output": {"checklist": [{"item": "출하 중단", "source": src}]}},
        {"tool": "notify_manager", "ok": True, "fallback": False, "ts": "t",
         "output": {"immediate": ["출입 통제"], "ppe": [], "first_aid": [], "report_info": {}, "sources": [src]}},
        {"tool": "report_119", "ok": True, "fallback": False, "ts": "t", "output": {"text": "신고문", "sources": [src]}},
        {"tool": "build_briefing", "ok": True, "fallback": False, "ts": "t",
         "output": {"summary": ["요약"], "first_aid": [], "sources": [src]}},
    ]
    _, after = _run_with_agent(ac, monkeypatch, actions)
    assert after["board"] == {"lines": ["1", "2", "3", "4"], "source": src}  # 4줄 초과는 자름
    assert after["checklist"] == [{"item": "출하 중단", "source": src}]
    assert after["guide_card"]["immediate"] == ["출입 통제"]
    assert after["report"]["text"] == "신고문" and after["report"]["sources"] == [src]
    assert after["report"]["status"] == "pending"
    assert after["briefing"]["summary"] == ["요약"]
    assert all(a["ok"] for a in after["actions"]) and after["actions"][0]["sources"] == [src]


def _load_agent_from(tmp_path, monkeypatch, init_source):
    import sys

    from alarm import agent_bridge

    if init_source is not None:
        (tmp_path / "agent").mkdir()
        (tmp_path / "agent" / "__init__.py").write_text(init_source, encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "agent", raising=False)
    try:
        return agent_bridge._load_agent()
    finally:
        sys.modules.pop("agent", None)


def test_load_agent_not_installed(tmp_path, monkeypatch):
    assert _load_agent_from(tmp_path, monkeypatch, None) == (None, "agent_not_installed")


@pytest.mark.parametrize("init_source", [
    "import some_missing_dependency_xyz\n",
    "raise RuntimeError('broken')\n",
    "x = 1\n",  # run_agent 없음 (ImportError)
])
def test_load_agent_internal_error_is_reported(tmp_path, monkeypatch, caplog, init_source):
    with caplog.at_level("ERROR", logger="heartsignal.alarm"):
        assert _load_agent_from(tmp_path, monkeypatch, init_source) == (None, "agent_import_failed")
    assert "agent import failed" in caplog.text


def test_load_agent_success(tmp_path, monkeypatch):
    fn, reason = _load_agent_from(tmp_path, monkeypatch, "async def run_agent(alarm):\n    return []\n")
    assert callable(fn) and reason is None
