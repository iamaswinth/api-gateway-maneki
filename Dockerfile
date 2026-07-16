FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8080
# WEB_CONCURRENCY controls worker count in prod; safe to raise per-replica —
# rate limiting and active-session counting are both Redis-backed with
# atomic pipeline/EX operations (app/ratelimit/), so there's no in-process
# state that a second worker or replica could race.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers ${WEB_CONCURRENCY:-2}
