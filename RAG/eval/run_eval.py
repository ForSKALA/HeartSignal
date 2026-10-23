# HeartSignal P2 — /rag-query 평가 스크립트
# 사용: python eval/run_eval.py --label baseline [--url http://localhost:8001] [--token <ACCESS_TOKEN>]
#
# 지표 (기획서 7.2, 명세서 6.2)
# - 정확성: 핵심 질문의 keywords가 답변에 모두 들어 있는 비율
# - 근거성: 핵심 질문의 expected_sources 중 하나가 응답 sources에 있는 비율
# - 무근거 답변률(환각률 대용): 거절하지 않고 답했는데 기대 출처가 응답 sources에 없는 비율
# - handoff 적중률: handoff 질문에서 handoff=true 이거나 거절 문구로 답한 비율

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
    return {
        "correct": len(hits) == len(q["keywords"]),
        "keyword_recall": round(len(hits) / len(q["keywords"]), 2),
        "grounded": grounded,
        "ungrounded_answer": not refused and not grounded,
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
        "ungrounded_answer_pct": pct(core, "ungrounded_answer"),
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
    args = ap.parse_args()

    cookies = {"ACCESS_TOKEN": args.token} if args.token else None
    rows = []
    with httpx.Client(base_url=args.url, cookies=cookies, timeout=60) as client:
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
            print(f"{q['id']:>4} {row.get('status', '-'):>4} "
                  + ("ERR " + str(row["error"])[:60] if "error" in row else
                     ("handoff " + str(row["handoff_hit"]) if q["type"] == "handoff"
                      else f"correct={row['correct']} recall={row['keyword_recall']} grounded={row['grounded']}")))

    summary = summarize(rows)
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
