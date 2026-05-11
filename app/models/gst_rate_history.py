from __future__ import annotations

from sqlalchemy import Column, Date, DateTime, Float, Integer, String, func

from app.models.database import Base


class GSTRateHistory(Base):
    """
    Historical GST rate entries per HSN code.

    One row per (hsn_code, effective_from) rate period.
    A NULL effective_to means the rate is currently active.
    """
    __tablename__ = "gst_rate_history"

    id = Column(Integer, primary_key=True)
    hsn_code = Column(String(10), index=True, nullable=False)
    gst_rate = Column(Float, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    source_url = Column(String(500), nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
