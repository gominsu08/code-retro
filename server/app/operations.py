"""Small-service limits and retention. Never store raw client IP addresses."""
import hashlib
import hmac
import ipaddress
import secrets

from fastapi import Request
from sqlalchemy import delete, func, or_, select, text

from .config import get_settings
from .db import db_session, now
from .errors import AppError
from .models import Idempotency, Job, OperationalState, Project, RequestQuota, Visitor

ACTIVE = ("queued", "running", "waiting_retry", "cancel_requested")


def enabled():
    settings = get_settings()
    return settings.app_env == "production" or settings.public_limits_enabled


def insert_for(db, model):
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(model)


def client_address(request: Request):
    # Enable only behind the selected, trusted deployment proxy. Select the
    # rightmost forwarded address so a client-supplied prefix cannot evade limits.
    if get_settings().trust_proxy_headers:
        chain = request.headers.get("x-forwarded-for", "")
        if chain:
            try:
                return str(ipaddress.ip_address(chain.split(",")[-1].strip()))
            except ValueError:
                pass
    return request.client.host if request.client else "unknown"


def consume_quota(db, key, limit, expires_at):
    statement = insert_for(db, RequestQuota).values(key=key, count=1, expires_at=expires_at)
    statement = statement.on_conflict_do_update(
        index_elements=["key"], set_={"count": RequestQuota.count + 1}
    ).returning(RequestQuota.count)
    count = db.scalar(statement)
    if count > limit:
        raise AppError("request_limit", "요청이 많습니다. 잠시 후 다시 시도해주세요.", 429)


def enforce_request_limits(request: Request):
    if not enabled() or not request.url.path.startswith("/api/") or request.url.path == "/api/health":
        return
    timestamp = now()
    with db_session() as db:
        db.execute(insert_for(db, OperationalState).values(
            key="ip_hash_key", value={"key": secrets.token_hex(32)}, updated_at=timestamp
        ).on_conflict_do_nothing(index_elements=["key"]))
        secret = db.get(OperationalState, "ip_hash_key").value["key"]
        address = hmac.new(secret.encode(), client_address(request).encode(), hashlib.sha256).hexdigest()
        # The global bucket also bounds quota-table cardinality across changing IPs.
        consume_quota(db, f"all:{timestamp // 60}", 1800, timestamp + 120)
        consume_quota(db, f"read:{timestamp // 60}:{address}", 360, timestamp + 120)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            consume_quota(db, f"write:{timestamp // 60}:{address}", 60, timestamp + 120)
        if request.url.path == "/api/v1/session" and not request.cookies.get("code_retro_session"):
            consume_quota(db, f"session:{timestamp // 3600}:{address}", 12, timestamp + 7200)


def storage_bytes(db):
    if db.get_bind().dialect.name == "postgresql":
        return db.scalar(text("SELECT pg_database_size(current_database())"))
    page_count = db.scalar(text("PRAGMA page_count"))
    page_size = db.scalar(text("PRAGMA page_size"))
    return page_count * page_size


def check_storage(db, creating_project=False):
    if not enabled():
        return
    settings = get_settings()
    if creating_project:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(73104292)"))
        count = db.scalar(select(func.count()).select_from(Project))
        if count >= settings.global_project_limit:
            raise AppError("server_capacity", "서버의 프로젝트 보관 한도에 도달했습니다. 기존 결과는 계속 확인할 수 있습니다.", 429)
    if storage_bytes(db) >= settings.database_limit_bytes:
        raise AppError("storage_capacity", "서버의 저장 한도에 도달했습니다. 기존 결과를 내보내고 운영자에게 알려주세요.", 507)


def worker_heartbeat():
    with db_session() as db:
        stamp = now()
        db.execute(insert_for(db, OperationalState).values(key="worker", value={}, updated_at=stamp)
                   .on_conflict_do_update(index_elements=["key"], set_={"updated_at": stamp}))


def cleanup_expired():
    """Purge expired sessions and projects deleted at least seven days ago."""
    stamp = now()
    with db_session() as db:
        active_projects = select(Job.project_id).where(Job.status.in_(ACTIVE))
        expired_visitors = select(Visitor.id).where(Visitor.expires_at < stamp)
        projects = select(Project.id).where(
            or_(Project.visitor_id.in_(expired_visitors),
                Project.deleted.is_(True) & (Project.updated_at < stamp - 7 * 86400)),
            Project.id.not_in(active_projects),
        )
        db.execute(delete(Project).where(Project.id.in_(projects)))
        unused_expired = select(Visitor.id).where(Visitor.expires_at < stamp, Visitor.id.not_in(select(Project.visitor_id)))
        expired_ids = list(db.scalars(unused_expired))
        db.execute(delete(Idempotency).where(or_(Idempotency.visitor_id.in_(expired_ids), Idempotency.created_at < stamp - 86400)))
        if expired_ids:
            db.execute(delete(Visitor).where(Visitor.id.in_(expired_ids)))
        db.execute(delete(RequestQuota).where(RequestQuota.expires_at < stamp))
