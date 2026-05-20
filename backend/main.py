"""
main.py - FastAPI application entry point for YejinSaem
Korean edtech feedback automation service
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Import database initialization
from database import init_db

# Import routers
from routers import admin, kakao, parents

# Initialize FastAPI app
app = FastAPI(
    title="YejinSaem - 글쓰기 피드백 서비스",
    description="카카오 채널을 통한 아이 글쓰기 피드백 자동화 서비스",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware - allow all origins for admin dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(kakao.router)
app.include_router(admin.router)
app.include_router(parents.router)

# Serve uploaded images as static files
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


@app.on_event("startup")
def on_startup():
    """Initialize database tables on startup."""
    logger.info("Starting YejinSaem backend...")
    init_db()
    logger.info("Database initialized successfully.")
    logger.info(f"Upload directory: {UPLOAD_DIR.resolve()}")


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "YejinSaem"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    reload = os.getenv("RELOAD", "true").lower() == "true"

    logger.info(f"Starting server on {host}:{port} (reload={reload})")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
