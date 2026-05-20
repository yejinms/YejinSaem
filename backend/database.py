"""
database.py - SQLAlchemy models and database initialization
"""

import os
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

# Database URL - defaults to SQLite, can be replaced with Supabase/PostgreSQL later
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./yejinsaem.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Parent(Base):
    __tablename__ = "parents"

    id = Column(Integer, primary_key=True, index=True)
    kakao_user_id = Column(String, unique=True, index=True, nullable=False)
    phone_number = Column(String, nullable=True)  # 솔라피 친구톡 발송용
    child_name = Column(String, nullable=False)
    child_age = Column(Integer, nullable=True)
    level = Column(
        Enum("표현력", "초등기초", "초등심화", name="level_enum"),
        nullable=False,
        default="표현력",
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    submissions = relationship("Submission", back_populates="parent")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("parents.id"), nullable=False)
    photo_path = Column(String, nullable=True)
    level = Column(String, nullable=True)
    stage = Column(Integer, nullable=True)
    extra_instruction = Column(Text, nullable=True)
    feedback_draft = Column(Text, nullable=True)
    status = Column(
        Enum("pending", "generated", "approved", "sent", name="status_enum"),
        nullable=False,
        default="pending",
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("Parent", back_populates="submissions")


def get_db():
    """Dependency for FastAPI to get a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
