FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs data model_store

ENV PORT=8080
EXPOSE 8080

CMD exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --workers 1 \
    --threads 8 \
    --timeout 300 \
    --graceful-timeout 300 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    "app:create_app()"
