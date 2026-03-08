"""SQLAlchemy models for the Chat Recall production database."""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255))
    github_id = Column(String(100), unique=True)
    google_id = Column(String(100), unique=True)
    avatar_url = Column(Text)
    password_hash = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Subscription / trial lifecycle
    subscription_status = Column(Text, nullable=False, server_default="none", default="none")
    trial_ends_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    retention_warned_at = Column(DateTime(timezone=True))

    # Analytics counters — updated after each import/upload
    total_conversations = Column(Integer, nullable=False, server_default="0", default=0)
    total_messages = Column(Integer, nullable=False, server_default="0", default=0)
    total_uploads = Column(Integer, nullable=False, server_default="0", default=0)
    last_upload_at = Column(DateTime(timezone=True))

    conversations = relationship("Conversation", back_populates="user")
    uploads = relationship("Upload", back_populates="user")
    subscription = relationship("Subscription", back_populates="user", uselist=False)


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    imported_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    record_count = Column(Integer, nullable=False, default=0)
    metadata_ = Column("metadata", JSONB)

    conversations = relationship("Conversation", back_populates="source")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Text, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    title = Column(Text)
    create_time = Column(Double)
    update_time = Column(Double)
    model = Column(Text)
    gizmo_id = Column(Text)
    message_count = Column(Integer, nullable=False, default=0)
    has_branches = Column(Boolean, nullable=False, default=False)
    metadata_ = Column("metadata", JSONB)
    source_type = Column(Text)
    project = Column(Text)
    tags = Column(JSONB)

    user = relationship("User", back_populates="conversations")
    source = relationship("Source", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_conversations_user_id", "user_id"),
        Index("idx_conversations_source_type", "source_type"),
        Index("idx_conversations_project", "project"),
        Index("idx_conversations_create_time", "create_time"),
        Index("idx_conversations_source", "source_id"),
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Text, nullable=False, primary_key=True)
    conversation_id = Column(
        Text, ForeignKey("conversations.id"), nullable=False, primary_key=True
    )
    parent_id = Column(Text)
    role = Column(Text)
    content_type = Column(Text)
    content_text = Column(Text)
    raw_content = Column(Text)
    is_canonical = Column(Boolean, nullable=False, default=True)
    create_time = Column(Double)
    attachments = Column(JSONB)
    metadata_ = Column("metadata", JSONB)
    # search_vector is a generated column — created in migration SQL, not in ORM

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("idx_messages_conversation", "conversation_id"),
        Index("idx_messages_canonical", "conversation_id", "is_canonical"),
    )


class Thread(Base):
    __tablename__ = "threads"

    id = Column(Text, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    status = Column(Text, nullable=False, default="active")
    tags = Column(JSONB)
    create_time = Column(Double, nullable=False)
    update_time = Column(Double, nullable=False)

    thread_conversations = relationship("ThreadConversation", back_populates="thread")


class ThreadConversation(Base):
    __tablename__ = "thread_conversations"

    thread_id = Column(Text, ForeignKey("threads.id"), primary_key=True)
    conversation_id = Column(Text, ForeignKey("conversations.id"), primary_key=True)
    note = Column(Text)
    added_time = Column(Double, nullable=False)

    thread = relationship("Thread", back_populates="thread_conversations")

    __table_args__ = (
        Index("idx_thread_conversations_thread", "thread_id"),
        Index("idx_thread_conversations_conversation", "conversation_id"),
    )


class Upload(Base):
    __tablename__ = "uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    filename = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    conversations_imported = Column(Integer, nullable=False, default=0)
    messages_imported = Column(Integer, nullable=False, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="uploads")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    stripe_customer_id = Column(String(255))
    stripe_subscription_id = Column(String(255))
    plan = Column(Text, nullable=False, default="free")
    status = Column(Text, nullable=False, default="active")
    current_period_end = Column(DateTime(timezone=True))
    conversation_limit = Column(Integer, nullable=False, default=200)

    user = relationship("User", back_populates="subscription")
