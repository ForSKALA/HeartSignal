# P1 데이터 파이프라인

## 로컬 미리보기

프로젝트 루트에서 실행합니다. 기본 실행은 자료를 외부로 전송하지 않으며 API 키도 필요하지 않습니다.

```bash
.venv/bin/python RAG/scripts/ingest.py
.venv/bin/python -m unittest discover -s RAG/tests -v
```

- 입력 목록: `RAG/data/sources.json`
- 정제·청킹 결과: `RAG/data/preview/chunks.jsonl`
- 문서별 원본 해시·적재 항목·제외 항목: `RAG/data/preview/ingest_report.json`
- 팀 공유 출처표: `docs/data_sources.md`

같은 파일·목록·추출기로 실행하면 청크 순서·ID·수가 동일합니다. ID는 내용과 메타데이터의 SHA-256입니다. 추출기 버전이 달라지면 텍스트나 ID가 달라질 수 있습니다. 미리보기와 출처표는 실행할 때 재생성됩니다.

PDF 추출은 설치된 `pdftotext -layout`을 우선 사용합니다. 없으면 `pypdf`의 layout 모드를 사용합니다. 최종 40개 문서·2,836개 청크는 Poppler 결과이며 재현 시 같은 추출기를 사용합니다. 원본 표의 이미지 행은 자동 추출된 것으로 취급하지 않습니다. 화면으로 확인한 황화수소 노출기준 1행과 키인포가이드의 선택 페이지는 `sources.json`의 `sections`에 명시했습니다.

## 자료 추가

자동 크롤링은 하지 않습니다. 공개 원문을 수동 확보한 뒤 `RAG/data/` 아래에 저장하고 `sources.json`의 `documents` 배열에 항목을 추가합니다. 공식 보완 원문 18개는 `안전지침/supplemental/`에 있습니다. 아래는 추가 등록 형식 예시입니다.

```json
{
  "path": "RAG/data/manual/law_618.md",
  "source": "산업안전보건기준에 관한 규칙",
  "doc_type": "law",
  "collection": "web",
  "url": "확인한 원문 URL",
  "published": "확인한 개정일"
}
```

- `doc_type`: `emergency`는 보유 안전지침 표 형식, `guide`는 지침, `law`는 법령입니다.
- 물질 문서는 `substance`에 프로젝트 공통 영문 snake_case 키를 넣습니다. 보유 안전지침의 CAS는 원문에서 추출합니다. 지침·법령이 특정 물질용이면 `cas`도 직접 기록합니다.
- 안전지침은 표의 항목 단위, 지침·법령은 `5.2.1 ...`, `제618조(...)` 또는 Markdown 제목 단위로 나눕니다. 지침의 인쇄 목차·반복 머리말은 수동 정리 후 Markdown으로 입력하는 것이 좋습니다. 원문에서 절을 정확하게 추출했는지 미리보기를 반드시 검토합니다.
- Markdown 변환본은 페이지를 추정하지 않습니다. `section`이 원문 조·절을 가리키며, `page=1`은 변환 파일의 페이지입니다. PDF는 물리 페이지를 1부터 기록합니다.
- `자료없음`인 항목·빈 그림 항목은 제외합니다. 표 안의 숫자·문장 의미를 자동 수정하지 않습니다.
- `url`, `published`는 확인된 값만 기록합니다. 기존 22개 자료는 원문 URL·공표일 미확인 상태입니다. 인쇄 날짜를 공표일로 사용하지 않습니다.
- `collection`은 `pdf` 또는 `web`입니다. 생략하면 PDF 파일은 `pdf`, TXT·Markdown은 `web`에 들어갑니다.

## FAISS 생성

유료 OpenAI 호출 전에 생성된 청크를 검토합니다. 2026-10-23 사용자 승인으로 필요한 패키지를 프로젝트 `.venv`(Python 3.11)에 설치하고 실제 임베딩을 실행했습니다. 키는 기존 실행 환경 또는 `RAG/.env`에서 읽으며 문서나 명령에 직접 넣지 않습니다. 환경변수 값 앞뒤의 공백·줄바꿈은 API 호출 시에만 제거하며 설정 파일은 수정하지 않습니다.

```bash
.venv/bin/python RAG/scripts/ingest.py --embed --index-output RAG/faiss_db/p1-build-next
```

새 경로에만 생성하며 기존 인덱스 경로는 거부합니다. 현재 최종 결과는 `RAG/faiss_db/p1-complete/pdf/`, `RAG/faiss_db/p1-complete/web/`의 `index.faiss`, `index.pkl`과 빌드 정보 `p1-complete/ingest_manifest.json`입니다. `p1-build/`는 기존 22개 자료만 적재한 이전 결과입니다. 위 명령은 다음 빌드를 별도 경로에 만드는 예시입니다. `web` 자료가 있으면 `web/`도 별도로 만듭니다. 전체 빌드 성공 후에만 결과 경로를 확정합니다.

임베딩은 기존 서버의 `OpenAIEmbeddings()` 기본값에 맞춰 `text-embedding-ada-002`로 고정했습니다. 모델 변경은 P2와 합의하고 인덱스를 재생성해야 합니다. 근거: [LangChain OpenAIEmbeddings 모델 참조](https://reference.langchain.com/python/langchain-openai/embeddings/base/OpenAIEmbeddings/model).

현재 서버는 `RAG` 디렉터리에서 실행할 때 `faiss_db/pdf`, `faiss_db/web`을 읽습니다. 신규 결과는 별도 경로에 생성했으며 서버 적용·라우터 연결·통합 실행은 사용자가 제외한 공동 작업 범위입니다. 기존 `/upload-paper`는 한 파일로 인덱스를 다시 만드는 구조이므로 일괄 적재 결과 적용 이후 호출 시 교체될 수 있습니다.

## P2 인계 계약

`chunks.jsonl` 각 줄은 다음 구조입니다.

```json
{
  "id": "내용과 메타데이터의 SHA-256",
  "page_content": "염소 | 응급조치>흡입\n원문 내용",
  "metadata": {
    "source": "안전지침/염소.pdf",
    "section": "응급조치>흡입",
    "doc_type": "emergency",
    "substance": "chlorine",
    "cas": "7782-50-5",
    "page": 3,
    "page_end": 3,
    "input_path": "안전지침/염소.pdf",
    "collection": "pdf"
  }
}
```

`source`·`section`은 그대로 응답의 출처 객체로 넘깁니다. `substance`·`doc_type`은 검색 필터로 사용할 수 있습니다. 긴 항목만 최대 1,000자, 중첩 100자의 보조 분할을 적용하며 제목 접두사는 이 길이에 별도로 더해집니다. 한 항목이 여러 페이지에 걸치면 청크는 항목 전체의 페이지 범위를 가집니다.

## 검증 기록

2026-10-23, 프로젝트 `.venv`의 Python 3.11과 설치된 Poppler로 확인했습니다.

- 기존 22개 PDF + 공식 보완 PDF 18개 = 40개 문서, 2,836개 청크. `guide` 1,553개, `emergency` 1,278개, `law` 5개입니다.
- 단위·회귀 테스트 13개 통과. 전체 입력의 필수 메타데이터, CAS, 누락값 제거, 항목·법령 경계, GHS 코드, 다중행·페이지, 긴 항목 분할, 동일 입력 재실행 일치, 기존 인덱스 보호, MSDS 8종 응급조치·화재·누출, 주요 보완 조항을 검증했습니다.
- 실제 OpenAI `text-embedding-ada-002` 임베딩 완료. PDF 인덱스 2,831개 + web 인덱스 5개, 모두 1,536차원입니다. 실제 청구 금액은 조회하지 않았습니다.
- 최종 인덱스 재로드 성공. 핵심 질문 10개 모두 근거가 있고, collection만 선택한 검색에서 9개는 기대 항목 1위, 염소 흡입 응급조치는 2위였습니다. 근거 위치 및 전체 검색 순위는 `preview/coverage_validation.json`에 기록합니다. collection만 선택한 상위 10개 검색으로, 물질 필터·문서 필터·재정렬은 적용하지 않습니다. 근거 확보 여부와 검색 순위는 구분해서 해석합니다.
- `preview/search_validation.json`은 이전 22개 자료 인덱스에서 물질 필터를 적용한 3개 질문의 과거 기록입니다. 최종 40개 자료의 검색 평가와 혼동하지 않습니다.
- 원문과 기획의 수치·기준 차이, 활용 범위와 제외한 공급자 PDF 6개는 `안전지침/supplemental/README.md`에 기록했습니다. 원문에 없는 값을 보충하거나 기존 수치를 덮어쓰지 않았습니다.
- `.venv`에 P1 패키지를 설치했고 기존 버전 지정에 맞춰 `langchain-community==0.4.1`, `langchain-openai==1.1.7`, `openai==1.109.1`을 사용했습니다. 전체 서버 실행은 검증 범위에서 제외했습니다.
- 기존 서버 인덱스는 교체하지 않았습니다. 코드 커밋·푸시와 타 파트 코드 수정도 수행하지 않았습니다.
