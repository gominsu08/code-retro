import hashlib
import os
import uuid

import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from server import worker
from server.app import agent, db as database
from server.app.analysis import parse_csharp
from server.app.config import get_settings
from server.app.github import classify
from server.app.main import app

MACHINE = """namespace Demo.Machines;
public abstract class Machine
{
    protected MachineSO definition;
    public abstract void Tick();
    public int Tier => definition.Tier;
}
public sealed class Mine : Machine
{
    public override void Tick() { Gather(); }
    private void Gather() { }
}
"""
DATA = """using UnityEngine;
namespace Demo.Data {
public class MachineSO : ScriptableObject {
    public int Tier;
    public float Duration;
    public int Amount;
}
}
"""
FILES = {"Assets/Scripts/Machines/Machine.cs": MACHINE, "Assets/Scripts/Data/MachineSO.cs": DATA, "Assets/Plugins/Other.cs": "class External { }"}


def blob(text):
    raw = text.encode()
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


class FakeGithub:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def inspect(self, owner, repo, ref, username):
        return {"ref": ref or "main", "commit_sha": "a" * 40, "tree_sha": "b" * 40, "repository_id": 42,
                "metadata": {"full_name": f"{owner}/{repo}", "user_exists": True, "identity_checked": username},
                "coverage": {"tree_complete": True, "uncollected_paths": []},
                "files": [{"path": p, "blob_sha": blob(t), "size": len(t.encode()), "category": classify(p)[0], "reason": classify(p)[1]} for p, t in FILES.items()]}

    def read_file(self, _owner, _repo, _commit, path, _blob_sha):
        return FILES[path], "utf-8"

    def history(self, *_args, **_kwargs):
        return [{"sha": "c" * 40, "author_login": "tester", "author_name": "Tester", "date": "2026-09-01T00:00:00Z", "message": "Add machines"}]


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    postgres_url = os.environ.get("TEST_POSTGRES_URL")
    schema = "test_" + uuid.uuid4().hex
    base_engine = database.make_engine(postgres_url or f"sqlite:///{tmp_path / 'test.db'}")
    if postgres_url:
        with base_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        test_engine = base_engine.execution_options(schema_translate_map={None: schema})
    else:
        test_engine = base_engine
    factory = sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(worker, "engine", test_engine)
    monkeypatch.setattr(agent, "engine", test_engine)
    monkeypatch.setattr(worker, "GitHubClient", FakeGithub)
    monkeypatch.setattr(agent, "GitHubClient", FakeGithub)
    monkeypatch.setattr(get_settings(), "ai_enabled", False)
    database.Base.metadata.create_all(test_engine)
    yield factory
    if postgres_url:
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    base_engine.dispose()


@pytest.fixture
def client():
    with TestClient(app) as client:
        response = client.post("/api/v1/session")
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield client


def send(client, method, path, body=None, key=None):
    return client.request(method, "/api/v1" + path, json=body, headers={"Idempotency-Key": key or uuid.uuid4().hex})


def ready_project(client):
    response = send(client, "POST", "/projects", {"repo_url": "https://github.com/tester/game", "github_username": "tester", "project_type": "team"})
    assert response.status_code == 202, response.text
    project_id = response.json()["project_id"]
    worker.execute_job(*worker.claim_job())
    project = send(client, "GET", f"/projects/{project_id}").json()
    assert project["snapshot"] is not None
    response = send(client, "POST", f"/projects/{project_id}/analyses", {"expected_version": project["config_version"]})
    assert response.status_code == 202, response.text
    worker.execute_job(*worker.claim_job())
    project = send(client, "GET", f"/projects/{project_id}").json()
    systems = send(client, "GET", f"/projects/{project_id}/systems").json()["systems"]
    assert systems, project["jobs"]
    return project, systems


def parsed(content=MACHINE, file_id="fixture"):
    return parse_csharp(content, file_id)
