import pytest
from fastapi import Request
from sqlalchemy import func, select

from conftest import ready_project
from server.app.config import get_settings
from server.app.db import now
from server.app.errors import AppError
from server.app.models import Comment, Idempotency, Job, Project, RequestQuota, Revision, SourceFile, Visitor
from server.app.operations import check_storage, cleanup_expired, client_address, enforce_request_limits


def request(headers=None):
    return Request({"type": "http", "method": "POST", "path": "/api/v1/projects",
                    "scheme": "https", "server": ("testserver", 443),
                    "client": ("203.0.113.10", 1234), "headers": headers or []})


def test_public_write_limit_and_untrusted_ip_header(isolated_database, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_limits_enabled", True)
    monkeypatch.setattr(get_settings(), "trust_proxy_headers", False)
    req = request([(b"x-forwarded-for", b"198.51.100.1")])
    assert client_address(req) == "203.0.113.10"
    for _ in range(60):
        enforce_request_limits(req)
    with pytest.raises(AppError) as error:
        enforce_request_limits(request([(b"x-forwarded-for", b"198.51.100.2")]))
    assert error.value.code == "request_limit"
    with isolated_database() as db:
        assert all("203.0.113.10" not in q.key for q in db.scalars(select(RequestQuota)))
    monkeypatch.setattr(get_settings(), "trust_proxy_headers", True)
    assert client_address(request([(b"x-forwarded-for", b"198.51.100.1, 203.0.113.10")])) == "203.0.113.10"


def test_public_capacity_preserves_reads_and_existing_data(client, isolated_database, monkeypatch):
    project, _ = ready_project(client)
    monkeypatch.setattr(get_settings(), "public_limits_enabled", True)
    monkeypatch.setattr(get_settings(), "global_project_limit", 1)
    with isolated_database() as db, pytest.raises(AppError) as error:
        check_storage(db, creating_project=True)
    assert error.value.code == "server_capacity"
    monkeypatch.setattr(get_settings(), "database_limit_bytes", 1)
    with isolated_database() as db, pytest.raises(AppError) as error:
        check_storage(db)
    assert error.value.code == "storage_capacity"
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 200


def test_expired_session_cleanup_cascades_but_preserves_active_job(client, isolated_database):
    project, _ = ready_project(client)
    with isolated_database() as db:
        visitor = db.get(Visitor, db.get(Project, project["id"]).visitor_id)
        visitor.expires_at = now() - 10
        active = Job(project_id=project["id"], kind="analyze", status="queued")
        db.add(active)
        db.commit()
        active_id, visitor_id = active.id, visitor.id
    cleanup_expired()
    with isolated_database() as db:
        assert db.get(Project, project["id"]) is not None
        db.get(Job, active_id).status = "cancelled"
        db.commit()
    cleanup_expired()
    with isolated_database() as db:
        assert db.get(Visitor, visitor_id) is None
        for model in (Project, Revision, SourceFile, Comment, Idempotency, Job):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_streamed_body_limit(client):
    response = client.post("/api/v1/session", content=(b"x" * 600_000 for _ in range(2)),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_postgres_quota_is_atomic(isolated_database):
    from concurrent.futures import ThreadPoolExecutor
    from server.app.operations import consume_quota
    with isolated_database() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL CI verifies concurrent upserts")

    def attempt(_):
        with isolated_database() as db:
            try:
                consume_quota(db, "concurrent-test", 3, now() + 60)
                db.commit()
                return True
            except AppError:
                db.rollback()
                return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(attempt, range(12))) == 3
