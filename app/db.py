"""
Database setup, utilities, and password hashing.
Split from __init__.py to avoid circular imports.
"""
import os, bcrypt
from datetime import datetime, timezone
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base

DB_PATH = os.environ.get("DB_PATH", "/data/rss_notify.db")
_db_dir = os.path.dirname(DB_PATH) or "."
try:
    os.makedirs(_db_dir, exist_ok=True)
except OSError:
    # Fallback: try parent then current directory
    try:
        _parent = os.path.dirname(_db_dir)
        os.makedirs(_parent, exist_ok=True)
    except OSError:
        _db_dir = "."
        DB_PATH = os.path.join(".", os.path.basename(DB_PATH))

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)
db_session = scoped_session(SessionLocal)
Base = declarative_base()


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_schema()


def _migrate_schema():
    """Apply tiny SQLite-compatible migrations for existing deployments."""
    inspector = inspect(engine)
    if "feed_items" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("feed_items")}
    with engine.begin() as conn:
        if "matched_keywords" not in columns:
            conn.execute(text("ALTER TABLE feed_items ADD COLUMN matched_keywords TEXT DEFAULT ''"))


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, h: str) -> bool:
    return bcrypt.checkpw(pw.encode(), h.encode())
