import time
import uuid
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from fastapi import Request

from .config import ROOT, get_settings


def uid() -> str:
    return uuid.uuid4().hex


def now() -> int:
    return int(time.time())


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("sqlite"):
        (ROOT / "data").mkdir(exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_setup(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=30000")
    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def db_session():
    with SessionLocal() as db:
        try:
            if engine.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def get_db(request: Request):
    with SessionLocal() as db:
        if request.method not in ("GET", "HEAD", "OPTIONS") and engine.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield db


def init_db():
    from . import models  # noqa: F401
    Base.metadata.create_all(engine)
