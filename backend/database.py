"""
database.py - SQLAlchemy models and database initialization
"""

import logging
import os

from datetime_utils import utc_now_naive
from levels_utils import apply_parent_levels, parse_parent_levels_json

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Boolean,
    String,
    Text,
    UniqueConstraint,
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
    weekly_words_enabled = Column(Boolean, nullable=False, default=True)
    level = Column(
        Enum("표현력", "초등기초", "초등심화", name="level_enum"),
        nullable=False,
        default="표현력",
    )
    levels = Column(Text, nullable=True)  # JSON array: ["표현력","초등기초",...]
    created_at = Column(DateTime, default=utc_now_naive)

    submissions = relationship("Submission", back_populates="parent")
    workbook_purchases = relationship("WorkbookPurchase", back_populates="parent")


class WorkbookPurchase(Base):
    __tablename__ = "workbook_purchases"

    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("parents.id"), nullable=False, index=True)
    buyer_name = Column(String, nullable=False)
    workbook_level = Column(String, nullable=False)
    channel = Column(String, nullable=False)
    pass_type = Column(String, nullable=False)
    purchase_date = Column(Date, nullable=False)
    expires_on = Column(Date, nullable=False)
    total_uses = Column(Integer, nullable=False)
    opening_used = Column(Integer, nullable=False, default=0)
    onboarding_requested = Column(Boolean, nullable=False, default=False)
    onboarding_sent = Column(Boolean, nullable=False, default=False)
    d14_sent = Column(Boolean, nullable=False, default=False)
    d7_sent = Column(Boolean, nullable=False, default=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)

    parent = relationship("Parent", back_populates="workbook_purchases")
    uses = relationship("WorkbookUse", back_populates="purchase")


class WorkbookUse(Base):
    __tablename__ = "workbook_uses"
    __table_args__ = (UniqueConstraint("submission_id", name="uq_workbook_use_submission"),)

    id = Column(Integer, primary_key=True)
    purchase_id = Column(Integer, ForeignKey("workbook_purchases.id"), nullable=False, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now_naive)

    purchase = relationship("WorkbookPurchase", back_populates="uses")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("parents.id"), nullable=False)
    product_type = Column(String, nullable=False, default="weekly_words")
    workbook_level = Column(String, nullable=True)
    rework_of_submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=True)
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
    _migrate_parent_product_column()
    _migrate_parent_levels_column()
    _migrate_submission_product_columns()


def _migrate_submission_product_columns() -> None:
    columns = {col["name"] for col in inspect(engine).get_columns("submissions")}
    with engine.begin() as conn:
        if "product_type" not in columns:
            conn.execute(text("ALTER TABLE submissions ADD COLUMN product_type VARCHAR DEFAULT 'weekly_words' NOT NULL"))
        if "workbook_level" not in columns:
            conn.execute(text("ALTER TABLE submissions ADD COLUMN workbook_level VARCHAR"))
        if "rework_of_submission_id" not in columns:
            conn.execute(text("ALTER TABLE submissions ADD COLUMN rework_of_submission_id INTEGER"))


def _migrate_parent_product_column() -> None:
    columns = {col["name"] for col in inspect(engine).get_columns("parents")}
    if "weekly_words_enabled" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE parents ADD COLUMN weekly_words_enabled BOOLEAN DEFAULT 1 NOT NULL"))
