FROM python:3.12-slim-bookworm

ENV TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config.example.yaml ./config.example.yaml

ENV WSS_DATA_DIR=/data \
    WSS_CONFIG=/data/config.yaml \
    WSS_CONSOLE_PASSWORD=changeme \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

RUN mkdir -p /data/recordings

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
