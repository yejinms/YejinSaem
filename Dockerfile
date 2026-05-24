FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (backend + admin frontend)
COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend

ENV HOST=0.0.0.0

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
