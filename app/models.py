"""
SQLAlchemy ORM models.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base, now


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)


class Feed(Base):
    __tablename__ = "feeds"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    url = Column(String(500), nullable=False)
    description = Column(Text, default="")
    enabled = Column(Boolean, default=True)
    poll_interval = Column(Integer, default=60)
    white_keywords = Column(Text, default="")
    black_keywords = Column(Text, default="")
    notify_urls = Column(Text, default="")
    created_at = Column(DateTime, nullable=False, default=now)
    updated_at = Column(DateTime, nullable=False, default=now)
    last_polled_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="")

    items = relationship("FeedItem", back_populates="feed", cascade="all, delete-orphan")


class FeedItem(Base):
    __tablename__ = "feed_items"
    id = Column(Integer, primary_key=True)
    feed_id = Column(Integer, ForeignKey("feeds.id"), nullable=False)
    guid = Column(String(128), nullable=False)
    title = Column(String(500), nullable=False, default="")
    link = Column(String(1000), default="")
    description = Column(Text, default="")
    body_text = Column(Text, default="")
    pub_date = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=False, default=now)
    matched = Column(Boolean, default=False)
    matched_keywords = Column(Text, default="")
    notified = Column(Boolean, default=False)

    feed = relationship("Feed", back_populates="items")
