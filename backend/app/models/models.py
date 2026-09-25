from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    ferment_min: Mapped[int] = mapped_column(Integer)
    bake_min: Mapped[int] = mapped_column(Integer)


class Oven(Base):
    __tablename__ = "ovens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(40), unique=True)
    capacity_note: Mapped[str] = mapped_column(String(80), default="")


class ChainGroup(Base):
    __tablename__ = "chain_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    max_gap_min: Mapped[int] = mapped_column(Integer, default=0)


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    oven_id: Mapped[int] = mapped_column(ForeignKey("ovens.id"))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    start_min: Mapped[int] = mapped_column(Integer)  # minutes from 00:00
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    chain_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("chain_groups.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    chain_group: Mapped[ChainGroup | None] = relationship()


class ConflictLog(Base):
    __tablename__ = "conflict_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_code: Mapped[str] = mapped_column(String(40))
    oven_id: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
