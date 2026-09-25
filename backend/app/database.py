from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_batch_chain_columns() -> None:
    """Add 连烤 columns on databases created before they existed.

    ``create_all`` only creates missing tables, so existing deployments need
    these columns added explicitly.
    """
    insp = inspect(engine)
    if "batches" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("batches")}
    with engine.begin() as conn:
        if "chain_group" not in cols:
            conn.execute(text("ALTER TABLE batches ADD COLUMN chain_group VARCHAR(40)"))
        if "chain_max_gap_min" not in cols:
            conn.execute(text("ALTER TABLE batches ADD COLUMN chain_max_gap_min INTEGER"))
