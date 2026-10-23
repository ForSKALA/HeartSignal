# 경보 API 라우터 (명세서 4.2). 라우터는 얇게: 권한 확인 → store 호출 → 에이전트 백그라운드 실행

from fastapi import APIRouter, Depends, Query

from auth import CurrentUser, get_current_user, require_role
from . import store
from .agent_bridge import run_for
from .models import AlarmCreate, ClearIn, HeadcountIn, Zone

router = APIRouter(tags=["경보"])


@router.post("/alarm", status_code=201, summary="경보 발령 (안전관리자)")
async def issue_alarm(body: AlarmCreate, user: CurrentUser = Depends(require_role("admin"))):
    alarm = store.create(body.zone, body.substance, body.stage, body.note, actor=user.sub)
    store.spawn(run_for(alarm["alarm_id"], "issue"))
    return store.snapshot(alarm)


@router.get("/alarm/status", summary="진행 중인 경보 목록")
async def alarm_status(user: CurrentUser = Depends(get_current_user)):
    return {"alarms": [store.snapshot(a) for a in store.list_active()]}


@router.get("/alarm/{alarm_id}", summary="경보 상세 (에이전트 실행 기록 포함)")
async def get_alarm(alarm_id: str, user: CurrentUser = Depends(get_current_user)):
    return store.snapshot(store.get(alarm_id))


@router.post("/alarm/{alarm_id}/headcount", summary="인원 점검 결과 입력 (작업반장)")
async def headcount(alarm_id: str, body: HeadcountIn, user: CurrentUser = Depends(require_role("foreman"))):
    return store.snapshot(store.set_headcount(alarm_id, body.checked, body.total, actor=user.sub))


@router.post("/alarm/{alarm_id}/hold-report", summary="119 신고 보류 (안전관리자, 발령 후 30초 내)")
async def hold_report(alarm_id: str, user: CurrentUser = Depends(require_role("admin"))):
    return store.snapshot(store.hold_report(alarm_id, actor=user.sub))


@router.post("/alarm/{alarm_id}/clear", summary="경보 해제 (안전관리자)")
async def clear_alarm(alarm_id: str, body: ClearIn | None = None,
                      user: CurrentUser = Depends(require_role("admin"))):
    alarm = store.clear(alarm_id, body.note if body else None, actor=user.sub)
    store.spawn(run_for(alarm_id, "clear"))
    return store.snapshot(alarm)


@router.get("/board/current", summary="전광판 현재 문구 (로그인 불필요)")
async def board_current(zone: Zone | None = Query(default=None)):
    return store.board_for(zone)
