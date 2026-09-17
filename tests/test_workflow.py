from fastapi.testclient import TestClient
from sqlalchemy import select

from server import worker
from server.app.db import now
from server.app.main import app
from server.app.models import Comment, ConfigVersion, Job, Revision, ToolRun
from conftest import ready_project, send


def test_session_csrf_and_isolation(client):
    p, _ = ready_project(client)
    with TestClient(app) as other:
        r = other.post("/api/v1/session")
        assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=lax" in r.headers["set-cookie"]
        assert other.get(f"/api/v1/projects/{p['id']}").status_code == 404
        assert other.get("/api/v1/projects").json()["projects"] == []
        assert other.delete(f"/api/v1/projects/{p['id']}").status_code == 403
        assert other.post("/api/v1/session", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get(f"/api/v1/projects/{p['id']}").status_code == 200


def test_idempotency_and_version_conflict(client, isolated_database):
    data = {"repo_url": "https://github.com/tester/game", "github_username": "tester", "project_type": "team"}
    first = send(client, "POST", "/projects", data, key="same-create")
    second = send(client, "POST", "/projects", data, key="same-create")
    assert first.json() == second.json()
    assert send(client, "POST", "/projects", {**data, "github_username": "another"}, key="same-create").status_code == 409
    worker.execute_job(*worker.claim_job())
    pid = first.json()["project_id"]
    p = send(client, "GET", f"/projects/{pid}").json()
    patch = {"expected_version": p["config_version"], "name": "Changed", "github_username": "tester", "project_type": "solo"}
    assert send(client, "PATCH", f"/projects/{pid}", patch).status_code == 200
    assert send(client, "PATCH", f"/projects/{pid}", patch).status_code == 409
    with isolated_database() as db:
        versions = db.scalars(select(ConfigVersion).where(ConfigVersion.project_id == pid).order_by(ConfigVersion.version)).all()
        assert [v.version for v in versions] == [1, 2, 3]
        assert versions[-2].project_type == "team" and versions[-1].project_type == "solo"


def test_end_to_end_comments_review_and_export(client, isolated_database):
    p, systems = ready_project(client)
    assert len(systems) == 2
    assert len(p["scope"]["selected_file_ids"]) == 2
    s = next(s for s in systems if s["name"] == "Machines")
    revision = s["revision"]
    assert revision["source"] == "structure" and not revision["stale"]
    assert "Demo.Machines.Machine" in revision["document"]["blocks"][0]["text"]
    base = f"/projects/{p['id']}/systems/{s['id']}"
    data = {"base_revision_id": revision["id"], "text": "확장을 위해 데이터와 동작을 분리했습니다.", "kind": "intent", "block_id": "structure"}
    comment = send(client, "POST", base + "/comments", data).json()["comment"]
    changed = send(client, "PATCH", base + f"/comments/{comment['root_id']}", {"expected_version": 1, "text": "SO 부분은 함께 작업했습니다."}).json()["comment"]
    assert changed["version"] == 2 and changed["id"] != comment["id"]
    with isolated_database() as db:
        old = db.get(Comment, comment["id"])
        assert old.text == data["text"]
        assert db.get(Revision, revision["id"]).document == revision["document"]
    assert send(client, "POST", base + "/revise", {"base_revision_id": revision["id"], "comment_ids": [comment["id"]]}).status_code == 409
    assert send(client, "POST", base + "/revise", {"base_revision_id": revision["id"], "comment_ids": [changed["id"]]}).json()["error"]["code"] == "ai_disabled"
    export = f"/projects/{p['id']}/exports"
    assert send(client, "POST", export, {"revision_ids": [revision["id"]]}).status_code == 409
    assert send(client, "PUT", base + "/review", {"base_revision_id": revision["id"], "reviewed": True}).status_code == 200
    result = send(client, "POST", export, {"revision_ids": [revision["id"]]})
    assert result.status_code == 201, result.text
    markdown = result.json()["markdown"]
    assert revision["document"]["blocks"][0]["text"] in markdown
    assert "/blob/" + "a" * 40 in markdown and "검토 완료" in markdown
    assert send(client, "PATCH", f"/projects/{p['id']}", {"expected_version": p["config_version"], "name": p["name"], "github_username": "another", "project_type": "team"}).status_code == 200
    assert send(client, "POST", export, {"revision_ids": [revision["id"]]}).status_code == 409


def test_scope_cross_project_and_code_range(client):
    p, systems = ready_project(client)
    scope = {**p["scope"], "expected_version": p["config_version"], "selected_file_ids": ["not-this-snapshot"]}
    assert send(client, "PUT", f"/projects/{p['id']}/scope", scope).status_code == 400
    file_id = systems[0]["file_ids"][0]
    assert send(client, "GET", f"/projects/{p['id']}/files/{file_id}?start=1&end=2000").status_code == 400
    response = send(client, "GET", f"/projects/{p['id']}/files/{file_id}?start=1&end=120")
    assert response.status_code == 200 and response.json()["commit_sha"] == "a" * 40


def test_worker_lease_fencing_recovery_and_cancel(client, isolated_database):
    response = send(client, "POST", "/projects", {"repo_url": "https://github.com/tester/game", "github_username": "tester", "project_type": "team"})
    claim = worker.claim_job()
    with isolated_database() as db:
        job = db.get(Job, claim[0])
        job.lease_until = now() - 10
        db.commit()
    recovered = worker.claim_job()
    assert recovered[0] == claim[0] and recovered[1] != claim[1]
    worker.execute_job(*claim)
    with isolated_database() as db:
        assert db.get(Job, claim[0]).lease_token == recovered[1]
    send(client, "POST", f"/jobs/{claim[0]}/cancel")
    worker.execute_job(*recovered)
    assert send(client, "GET", f"/jobs/{claim[0]}").json()["status"] == "cancelled"
    assert response.status_code == 202
    with isolated_database() as db:
        pending = db.get(Job, claim[0])
        pending.status = "waiting_retry"
        pending.available_at = now() + 3600
        pending.stage = "잠시 후 다시 시도합니다"
        pending.error_code, pending.error_message = "github_rate_limit", "GitHub 요청 한도"
        db.commit()
    cancelled = send(client, "POST", f"/jobs/{claim[0]}/cancel").json()
    assert cancelled["status"] == "cancelled" and cancelled["stage"] == "작업을 취소했습니다"
    assert cancelled["error"] is None and worker.claim_job() is None


def test_ai_tool_scope_and_evidence_validation(client, isolated_database):
    import pytest
    from server.app.agent import ToolContext, validate_document
    p, systems = ready_project(client)
    s = next(s for s in systems if s["name"] == "Machines")
    with isolated_database() as db:
        revision = db.get(Revision, s["revision"]["id"])
        job = Job(project_id=p["id"], kind="explain", status="running", lease_token="test-lease", lease_until=now() + 1000,
                  payload={"system_id": s["id"], "system_version": s["version"], "file_ids": s["file_ids"], "config_id": revision.config_id,
                           "base_revision_id": revision.id, "comment_ids": []})
        db.add(job)
        db.commit()
        job_id, payload = job.id, job.payload
    context = ToolContext(job_id, "test-lease", payload)
    assert context.call("read_code", '{"file_id":"foreign-file","start_line":1,"end_line":10}')["error"] == "out_of_scope"
    assert context.call("read_code", '{"file_id":"x","start_line":1,"end_line":10,"url":"https://evil"}')["error"] == "invalid_tool_args"
    assert context.call("execute_shell", '{}')["error"] == "unknown_tool"
    initial_review = context.call("get_review_context", '{}')
    assert initial_review["base_document"] is None and initial_review["base_evidence"] == {}
    assert initial_review["requires_code_read"] and not context.evidence
    result = context.call("read_code", '{"file_id":"' + s["file_ids"][0] + '","start_line":1,"end_line":10}')
    assert result["evidence_id"] in context.evidence
    short_prose = ("기계마다 필요한 동작을 같은 틀에서 다루도록 Machine을 공통 기반으로 둔 구조입니다. "
                   "개별 기계는 이를 상속하고 Tick을 구현하는 방식으로 구성되어 있습니다.\n\n"
                   "기본 클래스는 동작의 틀을 정하고 실제 처리는 각 기계에 나눠 둡니다. "
                   "새 기계를 추가할 때 같은 형태로 구현하려는 구조로 보이며, 당시 의도는 직접 확인이 필요합니다.")
    assert 120 <= len(short_prose) < 350
    doc = {"title": "Machine", "summary": "구조", "blocks": [{"block_id": "b1", "section": "implementation", "title": "구현", "text": short_prose, "claim_ids": ["c1"]}],
           "claims": [{"claim_id": "c1", "statement": "Machine이 추상 클래스다", "basis": "code_observation", "status": "supported", "evidence_ids": [result["evidence_id"]]}],
           "open_questions": [], "applied_comment_ids": []}
    accepted, evidence = validate_document(doc, context)
    assert accepted["title"] == "Machine" and evidence
    doc["blocks"][0]["text"] = short_prose.replace("\n\n", " ")
    with pytest.raises(ValueError, match="회고 문단"):
        validate_document(doc, context)
    doc["blocks"][0]["text"] = "공통 기반입니다.\n\n상속합니다."
    with pytest.raises(ValueError, match="회고 문단"):
        validate_document(doc, context)
    doc["blocks"][0]["text"] = short_prose
    doc["claims"][0]["evidence_ids"] = ["code:invented:1:2"]
    with pytest.raises(ValueError, match="근거"):
        validate_document(doc, context)
    with isolated_database() as db:
        assert len(db.scalars(select(ToolRun).where(ToolRun.job_id == job_id)).all()) == 5
