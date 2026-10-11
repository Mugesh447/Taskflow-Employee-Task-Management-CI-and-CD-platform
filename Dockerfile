FROM python:3.12-slim

WORKDIR /app
COPY backend/ ./
COPY frontend/ /frontend/
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system --gid 10001 taskflow \
    && useradd --system --uid 10001 --gid taskflow --home-dir /app --no-create-home taskflow \
    && mkdir -p /app/instance/uploads \
    && chown -R 10001:10001 /app/instance

USER 10001:10001

EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--access-logfile", "-", "app:app"]
