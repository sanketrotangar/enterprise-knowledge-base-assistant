# Document models — beta schema (docs/diagrams/03-schema.drawio)
# document_role_access.org_id is intentional denorm for RLS (not on diagram).

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'ready', 'failed')",
            name="documents_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    filename = Column(String(500), nullable=False)
    disk_path = Column(String(1000), nullable=False)
    status = Column(String(50), nullable=False, default="pending", index=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentRoleAccess(Base):
    """Which beta roles may see a document. org_id denorm for RLS."""

    __tablename__ = "document_role_access"

    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role = Column(String(50), primary_key=True)  # user|manager|admin
    org_id = Column(UUID(as_uuid=True), nullable=False, index=True)
