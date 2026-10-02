FROM python:3.12-slim

WORKDIR /app
COPY backend/ ./
COPY frontend/ /frontend/
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--access-logfile", "-", "app:app"]
