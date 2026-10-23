# HeartSignal RAG FastAPI (:8001)
FROM python:3.11-slim

# pip 경고 억제, 로그 즉시 출력
ENV PIP_ROOT_USER_ACTION=ignore \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 먼저 설치 (캐시 활용)
COPY requirements-e.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements-e.txt

# 애플리케이션 소스 + 기본 인덱스
COPY . /app

# 기본 인덱스 사본: k8s에서 PVC가 비어 있을 때 initContainer가 여기서 복사한다
RUN cp -r faiss_db faiss_db_seed

EXPOSE 8001

CMD ["uvicorn", "rag_external-web_pdf_closed_llm:app", "--host", "0.0.0.0", "--port", "8001"]
