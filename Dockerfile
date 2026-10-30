FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/barbearia.db

WORKDIR /app

RUN groupadd --system barberflow \
    && useradd --system --gid barberflow --home-dir /app barberflow \
    && mkdir -p /data \
    && chown barberflow:barberflow /data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py auth.py database.py security_routes.py smtp_settings.py ./
COPY static ./static
COPY templates ./templates

USER barberflow
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
