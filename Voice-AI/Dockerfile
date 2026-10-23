FROM python:3.11-slim

# System packages
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependencies first to leverage cache
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# 빌드할 때 모델을 포함하여 파드 시작 시 외부 다운로드를 하지 않는다.
RUN python -c "from faster_whisper.utils import download_model; download_model('small', output_dir='/opt/whisper-model')"

# stt_service.py는 기존 WHISPER_MODEL 설정으로 로컬 모델 경로도 읽는다.
# /app 밖에 두어 로컬 개발용 소스 볼륨을 마운트해도 모델을 유지한다.
ENV WHISPER_MODEL=/opt/whisper-model

# Application source
COPY . /app

# (Optional) It is recommended to remove --reload in production
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8008","--reload"]
