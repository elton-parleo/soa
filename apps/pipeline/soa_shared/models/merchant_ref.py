"""
Read-only mirror of the merchants table owned by /supply.

Uses extend_existing=True so SQLAlchemy does not try to create,
alter, or migrate this table — it is owned and managed exclusively
by the supply app. The /soa alembic migration references merchants.id
via ForeignKey string only.
"""
from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.orm import relationship

from .base import Base


class Merchant(Base):
    __tablename__ = "merchants"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name = Column(Text)
    slug = Column(Text)
    url = Column(Text)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))

