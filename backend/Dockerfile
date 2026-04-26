FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p generated_images generated_audio generated_videos uploads

EXPOSE 8000

CMD sh -c "celery -A app.celery_app worker --loglevel=info --concurrency=2 & uvicorn app.main:app --host 0.0.0.0 --port 8000"

