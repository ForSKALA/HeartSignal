"""수동 확보한 공개 자료를 정제·청킹한다. 기본 실행은 외부 호출 없는 미리보기다."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HEADINGS = (
    "기본 물질 정보", "폭발 및 화재위험성", "누출 시 대처요령", "물리화학적 특성",
    "응급조치", "취급시 주의사항", "GHS정보",
)
FIELDS = (
    "영문명", "물질명", "CAS번호", "위험물안전관리법", "EC번호", "RTDG Class",
    "ICSC번호", "RTECS번호", "CHRIS code", "DOT정보", "UN번호", "사용용도",
    "구조식", "유사명", "화학식", "화재 및 폭발위험", "소화방법", "소화제 및 장비",
    "연소생성물", "대기와의 반응성", "NFPA코드", "일반적 대처요령", "방제약품 및 장비",
    "초기이격거리", "방호활동거리", "누출 방지 및 개인보호구", "Breakthrough time",
    "분자량", "물리적 상태", "색상", "냄새", "냄새역치", "어는점", "녹는점", "끓는점",
    "증기압", "증기밀도", "비중", "인화점", "발화점", "폭발하한범위", "폭발상한범위",
    "분자식", "맛", "수용해도", "용해도", "PH", "옥탄올 물분배계수", "헨리상수", "점도",
    "응급조치", "경구", "경피", "흡입", "안구", "취급 및 저장방법", "폐기 시 주의사항",
    "운송정보", "유해위험성 분류 결과", "그림문자", "신호어", "유해위험문구", "예방조치문구",
)
FIELD_RE = re.compile(r"^\s*(" + "|".join(map(re.escape, sorted(FIELDS, key=len, reverse=True))) + r")(?:\s{2,}(.*)|\s*)$")


def extract_pages(path: Path) -> list[str]:
    """표의 열 위치를 보존한다. Poppler가 없으면 기존 의존성 pypdf를 쓴다."""
    if shutil.which("pdftotext"):
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"], check=True,
            capture_output=True, text=True, encoding="utf-8",
        )
        return result.stdout.rstrip("\f").split("\f")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF 추출에는 pdftotext 또는 requirements-e.txt의 pypdf가 필요합니다.") from exc
    return [page.extract_text(extraction_mode="layout") or "" for page in PdfReader(path).pages]


def clean_page(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if ("about:blank" in line or re.match(r"^\d{2,4}\.\s*\d+\.\s*\d+\.", stripped)
                or re.fullmatch(r"\d+\s*/\s*\d+", stripped)
                or stripped in {"목록", "비상대응지침", "(ERG)"}
                or "바로가기" in line or "※ GHS" in line):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines)


def first_column(line: str) -> str:
    """본문 오른쪽의 인용기관 열을 제외하고 내용은 원문 그대로 보존한다."""
    value = re.split(r"\s{2,}", line.strip(), maxsplit=1)[0].strip()
    if re.match(r"^(?:사고대비물질\(|한국산업안전보건공단|제조회사에서 제공한|guidechem|ICSC$)", value):
        return ""
    return value


def parse_emergency(pages: list[str]) -> tuple[list[dict], list[str]]:
    """행 가운데 정렬된 항목명 앞·뒤의 본문을 같은 항목에 묶는다."""
    records: list[dict] = []
    missing: set[str] = set()
    section = ""
    active = None
    for page_number, page in enumerate(pages, 1):
        for block in re.split(r"\n\s*\n", clean_page(page)):
            lines = [line for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            if len(lines) == 1 and lines[0].strip() in HEADINGS:
                section = lines[0].strip()
                active = None
                continue
            matches = [(i, FIELD_RE.match(line)) for i, line in enumerate(lines)]
            matches = [(i, match) for i, match in matches if match]
            if not matches:
                # 페이지 상단에 분류 행이 반복돼도 P/H 문구는 본래 항목에 이어 붙인다.
                if section == "GHS정보":
                    joined = "\n".join(lines)
                    field = "예방조치문구" if re.search(r"\bP\d{3}\b", joined) else (
                        "유해위험문구" if re.search(r"\bH\d{3}\b", joined) else None)
                    if field:
                        name = f"{section}>{field}"
                        active = next((r for r in reversed(records) if r["section"] == name), None)
                        if active is None:
                            active = {"section": name, "text": "", "page": page_number, "page_end": page_number}
                            records.append(active)
                # 페이지 경계 뒤의 문구는 이전 항목에 계속 속한다.
                if active is not None and section:
                    values = [first_column(line) for line in lines]
                    active["text"] += "\n" + "\n".join(value for value in values if value)
                    active["page_end"] = page_number
                continue
            if len(matches) != 1:
                raise ValueError(f"{page_number}쪽에서 표 행 경계를 구분하지 못했습니다: {block[:80]}")
            index, match = matches[0]
            field = match.group(1)
            values = [first_column(line) for line in lines[:index]]
            if match.group(2):
                values.append(first_column(match.group(2)))
            values.extend(first_column(line) for line in lines[index + 1:])
            value = "\n".join(v for v in values if v).strip()
            name = f"{section}>{field}"
            if not value or "자료없음" in value:
                missing.add(name)
                active = None
                continue
            active = {"section": name, "text": value, "page": page_number, "page_end": page_number}
            records.append(active)
    # 인쇄 과정에서 페이지 상단에 반복된 동일 행만 제거한다.
    unique = {}
    for record in records:
        key = (record["section"], record["text"])
        if key not in unique:
            unique[key] = record
    return list(unique.values()), sorted(missing)


def parse_structured(pages: list[str], doc_type: str) -> list[dict]:
    """수동 확보한 법령·지침의 조/절 또는 Markdown 제목을 경계로 삼는다."""
    heading = re.compile(r"^(\d+(?:\.\d+)*\.?)[ \t]+(.+)$")
    article = re.compile(r"^(제\s*\d+\s*조(?:의\s*\d+)?(?:\([^)]*\))?)(.*)$")
    records = []
    active = None
    parent = ""
    appendix = ""
    for number, page in enumerate(pages, 1):
        # 표지·개요·목차는 본문이 아니며, 목차의 절 번호를 검색 근거로 쓰지 않는다.
        if "목 차" in page or "목차" in page or "기술지원규정의 개요" in page or "기술지침의 개요" in page:
            continue
        for line in clean_page(page).splitlines():
            line = line.strip()
            if (not line or "자료없음" in line or "KOSHA GUIDE" in line or "국가법령정보센터" in line
                    or re.fullmatch(r"[A-Z](?:\s*[–—-]\s*[A-Z])?\s*[–—-]\s*\d+\s*-\s*\d{4}", line)
                    or re.fullmatch(r"[-－]?\s*\d+\s*[-－]?", line) or re.search(r"[·.]{5,}", line)):
                continue
            if re.match(r"^[<〈\[]\s*(?:부록|별표|붙임)", line):
                appendix = line
                parent = ""
            law = article.match(line) if doc_type == "law" else None
            title = heading.match(line) if doc_type == "guide" else None
            paragraph = re.match(r"^\((\d+)\)\s*(.*)", line) if doc_type == "guide" and parent else None
            if line.startswith("#") or law or title or paragraph:
                if law:
                    section, text = law.group(1), law.group(2).strip()
                elif title:
                    parent = title.group(1).rstrip(".")
                    section, text = parent, title.group(2)
                    if appendix:
                        section = f"{appendix}>{section}"
                elif paragraph:
                    section, text = f"{parent}({paragraph.group(1)})", paragraph.group(2)
                    if appendix:
                        section = f"{appendix}>{section}"
                else:
                    section, text = re.sub(r"^#+\s*", "", line), ""
                active = {"section": section, "text": text + "\n", "page": number, "page_end": number}
                records.append(active)
            elif active is not None:
                active["text"] += line + "\n"
                active["page_end"] = number
    if not records:
        raise ValueError(f"{doc_type} 문서에서 조/절을 찾지 못했습니다. 원문을 검토하고 Markdown 제목으로 구분하세요.")
    return [record for record in records if record["text"].strip()]


def parse_msds(pages: list[str]) -> tuple[list[dict], list[str]]:
    """공단 MSDS의 16개 항목을 보존하고 빈 세부 항목만 제외한다."""
    records = []
    active = None
    section = ""
    missing = set()
    for number, page in enumerate(pages, 1):
        for raw in page.splitlines():
            line = raw.strip()
            if not line or line.startswith(("◎", "Copyright", "- 주소", "- 전화")):
                continue
            title = re.match(r"^(\d{1,2})\.\s+(.+)$", line)
            if title and 1 <= int(title.group(1)) <= 16:
                section = f"{title.group(1)}. {title.group(2)}"
                active = None
                continue
            if not section or section.startswith("16."):
                continue
            field = re.match(r"^([가-하])\.\s*(.*)", line)
            columns = re.split(r"\s{2,}", field.group(2), maxsplit=1) if field else []
            if field:
                name = f"{section}>{field.group(1)}. {columns[0]}"
                value = columns[1] if len(columns) == 2 else ""
                if "자료없음" in value:
                    missing.add(name)
                    active = None
                    continue
                # 페이지 상단에 반복된 같은 행은 기존 항목에 연결한다.
                if active is None or active["section"] != name:
                    active = {"section": name, "text": "", "page": number, "page_end": number}
                    records.append(active)
                line = value
            elif active is None:
                active = {"section": section, "text": "", "page": number, "page_end": number}
                records.append(active)
            if "자료없음" in line:
                label = re.split(r"\s{2,}", line)[0]
                missing.add(f"{section}>{label}")
                continue
            active["text"] += line + "\n"
            active["page_end"] = number
    return [r for r in records if r["text"].strip()], sorted(missing)


def split_text(text: str, size: int = 1000, overlap: int = 100) -> list[str]:
    """긴 항목만 줄·문장 경계에 가깝게 나누고 일부 문맥을 중첩한다."""
    parts = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + size // 2, end), text.rfind(". ", start + size // 2, end))
            if boundary >= 0:
                end = boundary + 1
        parts.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - overlap
    return [part for part in parts if part]


def build_chunks(entries: list[dict], root: Path = ROOT) -> tuple[list[dict], list[dict]]:
    chunks = []
    report = []
    ids = set()
    for entry in sorted(entries, key=lambda item: item["path"]):
        if entry["doc_type"] not in {"emergency", "guide", "law"}:
            raise ValueError(f"알 수 없는 doc_type: {entry['doc_type']}")
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("입력 경로는 프로젝트 내부여야 합니다.")
        if path.suffix.lower() == ".pdf":
            pages = extract_pages(path)
        elif path.suffix.lower() in {".txt", ".md"}:
            pages = [path.read_text(encoding="utf-8")]
        else:
            raise ValueError(f"지원하지 않는 파일 형식: {path.suffix}")
        if not any(page.strip() for page in pages):
            raise ValueError(f"텍스트가 없습니다. 수동 OCR이 필요합니다: {entry['path']}")
        missing = []
        if entry.get("parser") == "msds":
            records, missing = parse_msds(pages)
            cas = entry["cas"]
            if cas not in "\n".join(pages[:2]):
                raise ValueError(f"원문 CAS 불일치: {entry['path']}")
        elif entry.get("sections"):
            records = entry["sections"]
            cas = entry.get("cas", "")
        elif entry["doc_type"] == "emergency":
            records, missing = parse_emergency(pages)
            if not entry.get("substance"):
                raise ValueError(f"물질 키가 필요합니다: {entry['path']}")
            cas = next((r["text"] for r in records if r["section"].endswith(">CAS번호")), "")
            if not re.fullmatch(r"\d{2,7}-\d{2}-\d", cas):
                raise ValueError(f"CAS 번호를 확인하세요: {entry['path']}")
        else:
            records = parse_structured(pages, entry["doc_type"])
            cas = entry.get("cas", "")
        before = len(chunks)
        for record in records:
            metadata = {key: entry[key] for key in ("source", "doc_type", "substance", "published", "url", "license", "effective", "scope") if entry.get(key)}
            metadata.update(section=record["section"], page=record["page"], page_end=record["page_end"], input_path=entry["path"])
            metadata.update({key: record[key] for key in ("substance", "cas") if record.get(key)})
            metadata["collection"] = entry.get("collection", "pdf" if path.suffix.lower() == ".pdf" else "web")
            if metadata["collection"] not in {"pdf", "web"}:
                raise ValueError("collection은 pdf 또는 web이어야 합니다.")
            if cas and not metadata.get("cas"):
                metadata["cas"] = cas
            # 항목 단위의 문맥을 검색 대상에도 포함한다.
            prefix = f"{entry.get('title', path.stem)} | {record['section']}\n"
            for part in split_text(record["text"].strip()):
                text = prefix + part
                payload = json.dumps([metadata, text], ensure_ascii=False, sort_keys=True)
                chunk_id = hashlib.sha256(payload.encode()).hexdigest()
                if chunk_id in ids:
                    continue
                ids.add(chunk_id)
                chunks.append({"id": chunk_id, "page_content": text, "metadata": metadata})
        if len(chunks) == before:
            raise ValueError(f"유효한 항목이 없습니다: {entry['path']}")
        report.append({**entry, "cas": cas, "pages": len(pages), "chunks": len(chunks) - before,
                       "sections": sorted({r["section"] for r in records}), "missing_sections": missing,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if not chunks:
        raise ValueError("적재할 청크가 없습니다.")
    return chunks, report


def write_preview(chunks: list[dict], report: list[dict], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "chunks.jsonl").write_text(
        "".join(json.dumps(chunk, ensure_ascii=False, sort_keys=True) + "\n" for chunk in chunks), encoding="utf-8")
    (output / "ingest_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_sources(report: list[dict], target: Path) -> None:
    lines = ["# 데이터 출처표", "", "`RAG/data/sources.json`과 원본 파일을 기준으로 적재 스크립트가 생성합니다.",
             "원문 URL·공표일이 확인되지 않은 값은 추정하지 않습니다. 페이지는 PDF의 1부터 시작하는 물리 페이지입니다.", "",
             "| 자료 | 물질 키 | CAS | 페이지 | 청크 | 원문 URL | 공표일 |", "|---|---|---|---:|---:|---|---|"]
    for item in report:
        lines.append(f"| {item['source']} | {item.get('substance', '-')} | {item.get('cas') or '-'} | {item['pages']} | {item['chunks']} | {item.get('url') or '확인 필요'} | {item.get('published') or '확인 필요'} |")
    lines += ["", "## 보완 자료와 검토 기록", "", "보완 원문은 `안전지침/supplemental/`에 있습니다. 다운로드 경위·개편 번호·제외 자료·확인된 차이는 같은 폴더의 `README.md`를 확인합니다.", "",
              "## 물질별 적재 범위", "", "‘제외’는 텍스트 값이 없거나 `자료없음`인 항목입니다. 그림만 있는 항목은 텍스트 적재 대상이 아닙니다.",
              "원본에 서로 다른 기관의 상충하는 서술이 있을 수 있습니다. 적재는 원문 보존이며 내용의 정확성·최신성을 보증하지 않습니다."]
    for item in report:
        lines += ["", f"### {item['source']}", "", f"- 원본 SHA-256: `{item['sha256']}`",
                  "- 적재: " + "; ".join(item["sections"]), "- 제외: " + ("; ".join(item["missing_sections"]) or "없음")]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def embed_chunks(chunks: list[dict], target: Path) -> None:
    """명시적 --embed 실행에서만 외부 API를 호출한다. 기존 인덱스는 덮어쓰지 않는다."""
    if target.exists():
        raise ValueError(f"인덱스 대상이 이미 존재합니다. 새 경로를 지정하세요: {target}")
    try:
        from dotenv import load_dotenv
        from langchain_community.vectorstores import FAISS
        from langchain_openai import OpenAIEmbeddings
    except ImportError as exc:
        raise RuntimeError("임베딩에는 RAG/requirements-e.txt의 패키지가 필요합니다.") from exc
    load_dotenv(ROOT / "RAG" / ".env")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY가 필요합니다.")
    # 베이스 서버의 OpenAIEmbeddings() 기본 모델과 동일하게 고정한다.
    model = "text-embedding-ada-002"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ingest-", dir=target.parent) as temporary:
        staging = Path(temporary) / "index"
        staging.mkdir()
        for collection in sorted({c["metadata"]["collection"] for c in chunks}):
            selected = [c for c in chunks if c["metadata"]["collection"] == collection]
            store = FAISS.from_texts(
                [c["page_content"] for c in selected],
                OpenAIEmbeddings(model=model, api_key=api_key, request_timeout=60),
                metadatas=[c["metadata"] for c in selected], ids=[c["id"] for c in selected],
            )
            store.save_local(str(staging / collection))
        (staging / "ingest_manifest.json").write_text(json.dumps({"embedding_model": model, "chunks": len(chunks), "ids": [c["id"] for c in chunks]}, indent=2) + "\n")
        staging.rename(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "RAG/data/sources.json")
    parser.add_argument("--output", type=Path, default=ROOT / "RAG/data/preview")
    parser.add_argument("--sources", type=Path, default=ROOT / "docs/data_sources.md")
    parser.add_argument("--embed", action="store_true", help="OpenAI API로 자료 전송 및 유료 임베딩 실행")
    parser.add_argument("--index-output", type=Path, help="새 FAISS 인덱스 경로 (기존 경로는 거부)")
    args = parser.parse_args()
    if args.embed and not args.index_output:
        parser.error("--embed에는 --index-output으로 새 경로를 지정해야 합니다.")
    try:
        entries = json.loads(args.manifest.read_text(encoding="utf-8"))["documents"]
        chunks, report = build_chunks(entries)
        write_preview(chunks, report, args.output)
        write_sources(report, args.sources)
        if args.embed:
            embed_chunks(chunks, args.index_output.resolve())
        print(json.dumps({"documents": len(report), "chunks": len(chunks),
                          "by_type": dict(Counter(c["metadata"]["doc_type"] for c in chunks)),
                          "embedded": args.embed}, ensure_ascii=False))
    except Exception as exc:
        # 외부 SDK 오류에는 요청·비밀값이 포함될 수 있어 그대로 출력하지 않는다.
        parser.exit(1, f"적재 실패: {exc}\n" if not args.embed else
                    f"적재 실패 ({type(exc).__name__}): 패키지·키·대상 경로·API 연결을 확인하세요.\n")


if __name__ == "__main__":
    main()
