# Notki uses only the Python standard library, so a bare Alpine image is enough.
FROM alpine:3.20

RUN apk add --no-cache python3 \
 && adduser -D -H -s /sbin/nologin notki

WORKDIR /app

COPY server.py admin.html admin.js app.js i18n.js index.html setup.html setup.js styles.css theme.js ./

# Create the data directory before declaring the volume so a fresh named volume
# inherits the unprivileged ownership instead of ending up owned by root.
RUN mkdir -p /app/data && chown -R notki:notki /app

USER notki

ENV PYTHONUNBUFFERED=1 \
    NOTKI_HOST=0.0.0.0 \
    NOTKI_PORT=8000 \
    NOTKI_DB_PATH=/app/data/notki.sqlite3 \
    NOTKI_BACKUP_DIR=/app/data/backups

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8000/api/setup/status || exit 1

CMD ["python3", "server.py"]
