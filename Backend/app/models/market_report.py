import uuid
from datetime import date

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.models.base import Base, TimestampMixin, uuid_pk


class MarketReport(Base, TimestampMixin):
    """Reference price data (never presented as live). is_sample marks seeded demo rows."""
    __tablename__ = "market_reports"
    __table_args__ = (
        UniqueConstraint("crop", "market", "report_date", "source", name="uq_market_reports_natural"),
        CheckConstraint("min_price_paise <= average_price_paise AND average_price_paise <= max_price_paise",
                        name="price_range_valid"),
        Index("ix_market_reports_crop_date", "crop", "report_date"),
        Index("ix_market_reports_embedding_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    crop: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(200), index=True)
    market: Mapped[str] = mapped_column(String(200))
    min_price_paise: Mapped[int] = mapped_column(BigInteger)
    max_price_paise: Mapped[int] = mapped_column(BigInteger)
    average_price_paise: Mapped[int] = mapped_column(BigInteger)
    report_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(200))
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding = mapped_column(Vector(get_settings().EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120))
