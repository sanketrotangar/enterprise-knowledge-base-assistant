# Postgres retrieval store — beta schema (docs/diagrams/03-schema.drawio)
# Table `chunks` is created/altered only by Alembic. Do not create_all.
# chunk_role_access.org_id is intentional denorm for RLS.

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.config import settings
from app.core.database import Base


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id = Column(UUID(as_uuid=True), nullable=False)
    chunk_index = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(settings.EMBEDDING_DIM), nullable=False)
    # tsv is GENERATED ALWAYS AS to_tsvector(content) — omit from INSERT.
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ChunkRoleAccess(Base):
    """Role copy on each chunk for RLS. org_id denorm avoids policy recursion."""

    __tablename__ = "chunk_role_access"

    chunk_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role = Column(String(50), primary_key=True)  # user|manager|admin
    org_id = Column(UUID(as_uuid=True), nullable=False, index=True)
