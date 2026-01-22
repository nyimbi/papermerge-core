from uuid import UUID
from datetime import datetime
from sqlalchemy import String, TIMESTAMP, Index, ForeignKey, Integer, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TSVECTOR, ARRAY, UUID as PG_UUID
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    # Fallback if pgvector is not installed in the environment
    from sqlalchemy import ARRAY as Vector

from papermerge.core.db.base import Base


class DocumentSearchIndex(Base):
    """
    Search index for documents with pre-computed tsvector.

    This table is automatically maintained by database triggers and contains
    denormalized data optimized for fast full-text search.
    """
    __tablename__ = "document_search_index"

    # Primary key
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.node_id", ondelete="CASCADE"),
        primary_key=True
    )

    # Foreign keys
    document_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_types.id", ondelete="SET NULL"),
        nullable=True
    )

    # Ownership (for access control)
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(nullable=False)

    # Language for FTS configuration
    lang: Mapped[str] = mapped_column(String(10), nullable=False, default='en')

    # Searchable content (stored for debugging/display)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    document_type_name: Mapped[str | None] = mapped_column(String, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    custom_fields_text: Mapped[str | None] = mapped_column(String, nullable=True)

    # Pre-computed tsvector for full-text search
    search_vector: Mapped[str] = mapped_column(TSVECTOR, nullable=False)

    # Metadata
    last_updated: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.utcnow
    )

    # Indexes
    __table_args__ = (
        # GIN index for full-text search (most important!)
        Index(
            'idx_document_search_vector',
            'search_vector',
            postgresql_using='gin'
        ),

        # Indexes for filtering
        Index('idx_document_search_owner', 'owner_type', 'owner_id'),
        Index('idx_document_search_doc_type', 'document_type_id'),
        Index('idx_document_search_lang', 'lang'),
    )


class DocumentEmbeddingModel(Base):
    """
    Vector embeddings for document chunks.
    Used for semantic search and similarity analysis.
    """
    __tablename__ = "document_embeddings"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.node_id", ondelete="CASCADE"),
        index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        index=True
    )
    page_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=True
    )
    
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(String)
    
    # Vector embedding (768 dimensions for nomic-embed-text)
    embedding: Mapped[list[float]] = mapped_column(Vector(768))
    
    model_name: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(50))
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_doc_embeddings_lookup', 'document_id', 'chunk_index', unique=True),
    )
