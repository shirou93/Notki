FROM python:3.12.7-alpine3.20

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NOTKI_HOST=0.0.0.0 \
    NOTKI_PORT=8000 \
    NOTKI_DB_PATH=/data/notki.sqlite3 \
    NOTKI_BACKUP_DIR=/data/backups

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

COPY . ./
RUN addgroup -S notki \
    && adduser -S -G notki -h /app notki \
    && mkdir -p /data/backups /keys \
    && chown -R notki:notki /app /data /keys

USER notki

EXPOSE 8000

CMD ["python3", "server.py"]
