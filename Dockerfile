FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# One-shot: run the daily job once, then exit 0.
# The scheduler (cron / platform) is what repeats this daily.
ENTRYPOINT ["python", "main.py"]
