"""
database.py - SQLAlchemy models and database initialization
"""

import logging
import os

from datetime_utils import utc_now_naive
from levels_utils import apply_parent_levels, parse_parent_levels_json

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)

logger = logging.getLogger(__name__)
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
    levels = Column(Text, nullable=True)  # JSON array: ["표현력","초등기초",...]
    created_at = Column(DateTime, default=utc_now_naive)

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
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    parent = relationship("Parent", back_populates="submissions")


def get_db():
    """Dependency for FastAPI to get a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_parent_levels_column() -> None:
    inspector = inspect(engine)
    if "parents" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("parents")}
    if "levels" in columns:
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE parents ADD COLUMN levels TEXT"))
    logger.info("Added parents.levels column")

    db = SessionLocal()
    try:
        parents = db.query(Parent).all()
        for parent in parents:
            if parent.levels:
                continue
            levels = parse_parent_levels_json(None, parent.level)
            apply_parent_levels(parent, levels)
        db.commit()
    finally:
        db.close()


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    _migrate_parent_levels_column()
