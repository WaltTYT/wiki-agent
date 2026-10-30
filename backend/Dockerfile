# 可选交付物（plan §4.2）：本机不装 Docker，镜像未在本机构建验证，交给 CI 或具备 Docker 的环境。
# 容器内不装 conda：python:3.13-slim + pip 装 requirements.txt，保持镜像精简。
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# compose 会把 ./data 挂到 /data，路径见 docker-compose.yml 的 environment
ENV CHROMA_PATH=/data/chroma \
    PDF_DIR=/data/pdfs \
    WIKI_DIR=/data/wiki

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
