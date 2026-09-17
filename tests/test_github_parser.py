import hashlib

import httpx
import pytest

from server.app.analysis import parse_csharp
from server.app.config import Settings
from server.app.errors import AppError
from server.app.github import GitHubClient, classify, parse_repo_url
from conftest import DATA, MACHINE


@pytest.mark.parametrize("url", ["http://github.com/a/b", "https://github.com.evil/a/b", "https://github.com@127.0.0.1/a/b", "https://127.0.0.1/a/b", "https://github.com/a/b/tree/main", "https://github.com/a/b?token=x", "file:///etc/passwd", "https://github.com/a/.."])
def test_only_repository_roots_allowed(url):
    with pytest.raises(AppError):
        parse_repo_url(url)


def test_repository_and_third_party_defaults():
    assert parse_repo_url("https://github.com/a/game.git/") == ("a", "game", "https://github.com/a/game")
    assert classify("Assets/BOXOPHOBIC/Runtime/X.cs")[0] == "external"
    assert classify("Assets/Scripts/GMS/Thing.cs")[0] == "project"
    assert classify("Assets/Scripts/Thing.g.cs")[0] == "generated"
    assert classify("Assets/Scripts/X.cs", "120000")[0] == "unsupported"


def test_csharp_file_scoped_namespace_inheritance_and_fields():
    result = parse_csharp(MACHINE, "m")
    assert result["namespaces"] == ["Demo.Machines"]
    assert not result["has_errors"]
    types = {s["name"]: s for s in result["symbols"] if s["kind"] == "class_declaration"}
    assert "abstract" in types["Machine"]["modifiers"]
    assert types["Mine"]["bases"] == "Machine"
    assert types["Machine"]["qualified_name"] == "Demo.Machines.Machine"
    field = next(s for s in result["symbols"] if s["name"] == "definition")
    assert field["type"] == "MachineSO"
    assert MACHINE.splitlines()[field["start_line"] - 1].strip() == "protected MachineSO definition;"
    data = parse_csharp(DATA, "d")
    assert data["namespaces"] == ["Demo.Data"]
    assert {s["name"] for s in data["symbols"] if s["kind"] == "field_declaration"} == {"Tier", "Duration", "Amount"}


def test_nested_namespace_and_parse_failure():
    result = parse_csharp("namespace A { namespace B { class C { class D { } } } }", "f")
    assert result["symbols"][-1]["qualified_name"] == "A.B.C.D"
    assert parse_csharp("class Bad { void X(", "f")["has_errors"]


def test_raw_content_is_pinned_and_token_not_forwarded():
    content = b"class Hello {}\n"
    sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=content)
    with GitHubClient(Settings(github_token="test-secret"), httpx.MockTransport(handler)) as github:
        text, encoding = github.read_file("owner", "repo", "a" * 40, "Assets/Hello.cs", sha)
        assert text == content.decode() and encoding == "utf-8-sig"
    assert seen[0].url.host == "raw.githubusercontent.com"
    assert "a" * 40 in seen[0].url.path
    assert "authorization" not in seen[0].headers


def test_blob_mismatch_and_private_repo_rejected():
    with GitHubClient(Settings(), httpx.MockTransport(lambda _: httpx.Response(200, content=b"changed"))) as github:
        with pytest.raises(AppError, match="일치"):
            github.read_file("a", "b", "a" * 40, "x.cs", "b" * 40)
    with GitHubClient(Settings(), httpx.MockTransport(lambda _: httpx.Response(200, json={"private": True}))) as github:
        with pytest.raises(AppError, match="공개"):
            github.inspect("a", "b", "", "me")


def test_truncated_tree_falls_back_and_reports_incomplete():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if "recursive" in request.url.params:
            return httpx.Response(200, json={"truncated": True, "tree": []})
        return httpx.Response(200, json={"truncated": False, "tree": [{"path": "deep", "type": "tree", "sha": "b" * 40}]})
    with GitHubClient(Settings(max_tree_requests=2), httpx.MockTransport(handler)) as github:
        files, coverage = github.tree("/repos/a/b", "a" * 40)
    assert len(calls) == 2 and files == []
    assert not coverage["tree_complete"] and coverage["uncollected_paths"] == ["deep"]
