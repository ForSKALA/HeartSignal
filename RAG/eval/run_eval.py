# HeartSignal P2 — /rag-query 평가 스크립트
# 사용: python eval/run_eval.py --label baseline [--url http://localhost:8001] [--token <ACCESS_TOKEN>]
#
# 지표 (기획서 7.2, 명세서 6.2)
# - 정확성: 핵심 질문의 keywords가 답변에 모두 들어 있는 비율
# - 근거성: 핵심 질문의 expected_sources 중 하나가 응답 sources에 있는 비율 (문서 단위)
# - 절 일치율: expected_sections 중 하나가 응답 sources 의 section 에 있는 비율 (엄격, 9행부터)
# - 무근거 답변률(환각률 대용): 거절하지 않고 답했는데 기대 출처가 응답 sources에 없는 비율
# - handoff 적중률: handoff 질문에서 handoff=true 이거나 거절 문구로 답한 비율
# - needs_review 표시율: 오답(틀림·근거 없음)에서의 표시율은 높아야, 정답에서는 낮아야 한다 (14행부터)

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import httpx

EVAL_DIR = Path(__file__).resolve().parent
REFUSAL_PHRASES = ("찾을 수 없", "확인된 자료가 없", "N/A")


def load_questions(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_refusal(body: dict) -> bool:
    return bool(body.get("handoff")) or any(p in body.get("response", "") for p in REFUSAL_PHRASES)


def source_text(body: dict) -> str:
    return " ".join(f"{s.get('source', '')} {s.get('section', '')}" for s in body.get("sources") or [])


def score(q: dict, body: dict) -> dict:
    answer = body.get("response", "")
    refused = is_refusal(body)
    if q["type"] == "handoff":
        return {"handoff_hit": refused}
    hits = [k for k in q["keywords"] if k in answer]
    grounded = any(s in source_text(body) for s in q["expected_sources"])
    sections = " ".join(s.get("section", "") for s in body.get("sources") or [])
    section_match = any(sec in sections for sec in q.get("expected_sections", []))
    return {
        "correct": len(hits) == len(q["keywords"]),
        "keyword_recall": round(len(hits) / len(q["keywords"]), 2),
        "grounded": grounded,
        "section_match": section_match,
        "ungrounded_answer": not refused and not grounded,
        "needs_review": bool(body.get("needs_review")),
    }


def summarize(rows: list[dict]) -> dict:
    core = [r for r in rows if r["type"] != "handoff" and "error" not in r]
    handoff = [r for r in rows if r["type"] == "handoff" and "error" not in r]
    pct = lambda items, key: round(100 * sum(r[key] for r in items) / len(items), 1) if items else None
    return {
        "core_n": len(core),
        "accuracy_pct": pct(core, "correct"),
        "keyword_recall_avg": round(sum(r["keyword_recall"] for r in core) / len(core), 2) if core else None,
        "grounded_pct": pct(core, "grounded"),
        "section_match_pct": pct(core, "section_match"),
        "ungrounded_answer_pct": pct(core, "ungrounded_answer"),
        # needs_review 품질: 오답(틀렸거나 근거 없음)에서는 높고, 정답에서는 낮아야 한다
        "review_flag_on_wrong_pct": pct([r for r in core if not (r["correct"] and r["grounded"])], "needs_review"),
        "review_flag_on_right_pct": pct([r for r in core if r["correct"] and r["grounded"]], "needs_review"),
        "handoff_n": len(handoff),
        "handoff_hit_pct": pct(handoff, "handoff_hit"),
        "errors": sum("error" in r for r in rows),
        "latency_ms_avg": round(sum(r["latency_ms"] for r in rows) / len(rows)) if rows else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="결과 파일 이름에 붙일 변경 이름 (예: baseline, handoff-d0.45)")
    ap.add_argument("--url", default=os.getenv("RAG_URL", "http://localhost:8001"))
    ap.add_argument("--token", default=os.getenv("ACCESS_TOKEN"), help="로그인 쿠키 ACCESS_TOKEN (인증 적용 후 필요)")
    ap.add_argument("--questions", default=str(EVAL_DIR / "questions.jsonl"))
    ap.add_argument("--source", default="pdf")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--repeat", type=int, default=1, help="질문당 반복 횟수. 2 이상이면 지표는 반복 평균, 행은 마지막 실행")
    args = ap.parse_args()

    cookies = {"ACCESS_TOKEN": args.token} if args.token else None
    rows, runs = [], []
    with httpx.Client(base_url=args.url, cookies=cookies, timeout=60) as client:
      for rep in range(args.repeat):
        rows = []
        for q in load_questions(Path(args.questions)):
            started = time.perf_counter()
            row = {"id": q["id"], "type": q["type"]}
            try:
                res = client.post("/rag-query", json={"prompt": q["question"], "source": args.source, "top_k": args.top_k})
                row["latency_ms"] = int((time.perf_counter() - started) * 1000)
                row["status"] = res.status_code
                body = res.json()
                if res.status_code != 200:
                    row["error"] = body.get("error", body)
                else:
                    row.update(score(q, body), response=body.get("response", ""), sources=body.get("sources", []))
            except Exception as exc:  # 서버 미기동 등
                row["latency_ms"] = int((time.perf_counter() - started) * 1000)
                row["error"] = type(exc).__name__
            rows.append(row)
            print(f"{'r'+str(rep+1) if args.repeat > 1 else '':>3}{q['id']:>4} {row.get('status', '-'):>4} "
                  + ("ERR " + str(row["error"])[:60] if "error" in row else
                     ("handoff " + str(row["handoff_hit"]) if q["type"] == "handoff"
                      else f"correct={row['correct']} recall={row['keyword_recall']} grounded={row['grounded']} section={row['section_match']}")))

        runs.append(summarize(rows))

    summary = runs[-1]
    if args.repeat > 1:  # 반복 평균 (측정 편차 완화) + 실행별 값
        keys = [k for k, v in runs[0].items() if isinstance(v, (int, float)) and k not in ("core_n", "handoff_n", "errors")]
        summary = {**summary, **{k: round(sum(r[k] for r in runs if r[k] is not None) / len(runs), 1) for k in keys},
                   "errors": sum(r["errors"] for r in runs), "repeat": args.repeat,
                   "per_run": {k: [r[k] for r in runs] for k in ("accuracy_pct", "grounded_pct", "section_match_pct", "handoff_hit_pct", "review_flag_on_wrong_pct", "review_flag_on_right_pct")}}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M}-{args.label}.json"
    out.write_text(json.dumps({"label": args.label, "url": args.url, "source": args.source,
                               "top_k": args.top_k, "summary": summary, "rows": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out.relative_to(EVAL_DIR.parent)}")


if __name__ == "__main__":
    main()
