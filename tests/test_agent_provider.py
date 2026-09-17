import json

import httpx
from openai import OpenAI
from pydantic import SecretStr
from sqlalchemy import select

from conftest import ready_project, send
from server import worker
from server.app import agent
from server.app.config import get_settings
from server.app.models import Budget, Job, Revision, ToolRun
from server.app.providers import GeminiProvider, gemini_schema
from server.app.schemas import Explanation


def test_gemini_tool_loop_and_comment_revision(client, isolated_database, monkeypatch):
    project, systems = ready_project(client)
    system = next(s for s in systems if s["name"] == "Machines")
    base = f"/projects/{project['id']}/systems/{system['id']}"
    original_id = system["revision"]["id"]
    monkeypatch.setattr(get_settings(), "ai_enabled", True)
    monkeypatch.setattr(get_settings(), "gemini_api_key", SecretStr("fixture-key"))
    requests = []

    def reply(name, arguments, index):
        return httpx.Response(200, json={"id": f"completion-{index}", "object": "chat.completion", "created": 1, "model": "gemini-3.5-flash-lite",
             "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": f"call-{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}}],
             "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}})

    def handler(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        body = json.loads(request.content)
        requests.append(body)
        assert "response_format" not in body
        assert any(t["function"]["name"] == "submit_explanation" for t in body["tools"])
        outputs = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
        code = next((o for o in outputs if o.get("kind") == "code"), None)
        review = next((o for o in outputs if "selected_comments" in o), None)
        seed = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user").split("\n", 1)[1])
        if seed["has_ai_base"] and not review:
            return reply("get_review_context", {}, len(requests))
        if review:
            evidence_id, reference = next((eid, item) for eid, item in review["base_evidence"].items() if item["kind"] == "code")
            code = {"evidence_id": evidence_id, **reference}
        if not code:
            return reply("read_code", {"file_id": system["file_ids"][0], "start_line": 1, "end_line": 12}, len(requests))
        claims = [{"claim_id": "c1", "statement": "Machine은 추상 클래스이며 Mine이 상속한다.", "basis": "code_observation", "status": "supported", "evidence_ids": [code["evidence_id"]]}]
        prose = "Machine은 공통 기반 클래스이며 Tick을 추상 메서드로 선언합니다. Mine은 Machine을 상속하고 Tick을 재정의해 Gather를 호출합니다. 현재 코드에서 확인할 수 있는 구조를 기준으로 공통 계약과 개별 동작이 나뉜다는 점을 살펴볼 수 있습니다. " * 2
        prose += "\n\nMachine에는 MachineSO 타입의 definition 필드가 있고 Tier 프로퍼티가 definition.Tier를 읽습니다. 기계 설정을 데이터 객체를 통해 참조하는 형태를 확인할 수 있지만, 실제 설정 값과 생성 경로를 확정하려면 데이터 클래스 및 할당 코드를 추가로 확인해야 합니다. " * 2
        if review and review["selected_comments"]:
            c = review["selected_comments"][0]
            claims.append({"claim_id": "c2", "statement": c["text"], "basis": "user_statement", "status": "supported", "evidence_ids": [c["evidence_id"]]})
            prose += "\n\n사용자는 다음과 같이 개발 배경을 보완했습니다: " + c["text"]
        elif review:
            for eid, reference in review["base_evidence"].items():
                if reference["kind"] == "comment":
                    claims.append({"claim_id": "c2", "statement": reference["text"], "basis": "user_statement", "status": "supported", "evidence_ids": [eid]})
                    prose += "\n\n사용자가 앞서 확인한 개발 배경: " + reference["text"]
        doc = {"title": "기계 시스템", "summary": "코드 확인 결과", "blocks": [{"block_id": "design", "section": "implementation", "title": "공통 기반과 개별 구현", "text": prose, "claim_ids": [c["claim_id"] for c in claims]}],
               "claims": claims, "open_questions": ["기계를 추가할 때 실제로 변경한 파일은 무엇인가요?"], "applied_comment_ids": seed["selected_comment_ids"]}
        return reply("submit_explanation", doc, len(requests))

    monkeypatch.setattr(agent, "create_provider", lambda: GeminiProvider(OpenAI(api_key="fixture-key", base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0)))
    response = send(client, "POST", base + "/generate")
    assert response.status_code == 202, response.text
    worker.execute_job(*worker.claim_job())
    revision = send(client, "GET", base + "/revisions").json()["revisions"][0]
    assert revision["number"] == 2 and revision["source"] == "ai"
    assert revision["parent_id"] == original_id
    comment = send(client, "POST", base + "/comments", {"base_revision_id": revision["id"], "text": "새로운 기계 추가 시 공통 로직 수정을 줄이고 싶었습니다.", "kind": "intent"}).json()["comment"]
    result = send(client, "POST", base + "/revise", {"base_revision_id": revision["id"], "comment_ids": [comment["id"]]})
    assert result.status_code == 202
    worker.execute_job(*worker.claim_job())
    revisions = send(client, "GET", base + "/revisions").json()["revisions"]
    assert [r["number"] for r in revisions] == [3, 2, 1]
    assert revisions[0]["comment_ids"] == [comment["id"]]
    assert comment["text"] in revisions[0]["document"]["blocks"][0]["text"]
    assert revisions[1]["document"] == revision["document"]
    with isolated_database() as db:
        assert db.get(Revision, original_id).source == "structure"
        assert len(db.scalars(select(ToolRun)).all()) == 2
        job = db.get(Job, result.json()["job"]["id"])
        assert job.result["ai_calls"] == 2 and job.result["tool_calls"] == 1
        budget = db.scalar(select(Budget))
        assert budget.used_tokens == 800 and budget.reserved_tokens == 0

    # Rewriting with no newly selected comments keeps an already-cited intent,
    # while excluding other comments that have not been selected for application.
    send(client, "POST", base + "/comments", {"base_revision_id": revisions[0]["id"], "text": "아직 반영하지 않은 별도 의견", "kind": "intent"})
    rewrite = send(client, "POST", base + "/generate")
    assert rewrite.status_code == 202
    worker.execute_job(*worker.claim_job())
    rewritten = send(client, "GET", base + "/revisions").json()["revisions"]
    assert [r["number"] for r in rewritten] == [4, 3, 2, 1]
    assert rewritten[0]["parent_id"] == revisions[0]["id"]
    assert rewritten[0]["comment_ids"] == []
    assert rewritten[1]["document"] == revisions[0]["document"]
    assert comment["text"] in rewritten[0]["document"]["blocks"][0]["text"]
    assert f"comment:{comment['id']}" in rewritten[0]["evidence"]
    assert "아직 반영하지 않은 별도 의견" not in json.dumps(rewritten[0]["document"], ensure_ascii=False)


def test_gemini_schema_expands_refs():
    schema = gemini_schema(Explanation.model_json_schema())
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    assert schema["properties"]["blocks"]["items"]["properties"]["text"]["type"] == "string"
    assert "title" in schema["properties"]
    assert "title" in schema["properties"]["blocks"]["items"]["properties"]
    def required_properties_exist(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert set(node.get("required", [])).issubset(node.get("properties", {}))
            for value in node.values():
                required_properties_exist(value)
        elif isinstance(node, list):
            for value in node:
                required_properties_exist(value)
    required_properties_exist(schema)
