"""Opt-in Gemini verification against an existing browser-test workspace."""
import argparse
import json
import time
import uuid

import httpx

from server.app.config import ROOT, get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemini", action="store_true", help="Explicitly run a real Gemini generation and revision")
    parser.add_argument("--resume-revision", action="store_true", help="Reuse the existing AI draft after a corrected revision failure")
    args = parser.parse_args()
    settings = get_settings()
    if not args.gemini or settings.ai_provider != "gemini" or not settings.ai_ready:
        raise SystemExit("Gemini must be configured and --gemini must be explicitly supplied.")
    state = json.loads((ROOT / "web/.runtime/e2e-session.json").read_text(encoding="utf-8"))
    cookies = {c["name"]: c["value"] for c in state["cookies"] if c["name"] == "code_retro_session"}
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", cookies=cookies, timeout=30) as client:
        session = client.post("/session").json()
        client.headers["X-CSRF-Token"] = session["csrf_token"]
        def post(path, body=None):
            r = client.post(path, json=body, headers={"Idempotency-Key": uuid.uuid4().hex})
            if r.is_error:
                raise RuntimeError(r.json().get("error", {}).get("message", "API failed"))
            return r.json()
        def wait(job):
            started, previous = time.monotonic(), None
            while time.monotonic() - started < 240:
                result = client.get(f"/jobs/{job['id']}").json()
                state = (result["status"], result["stage"])
                if state != previous:
                    print(json.dumps({"job": job["id"], "status": state[0], "stage": state[1]}, ensure_ascii=True), flush=True)
                    previous = state
                if result["status"] not in ("queued", "running", "waiting_retry", "cancel_requested"):
                    if result["status"] != "succeeded":
                        raise RuntimeError(json.dumps(result.get("error"), ensure_ascii=True))
                    return result
                time.sleep(2)
            raise RuntimeError("Verification timed out; inspect the saved job before retrying.")
        project = next(p for p in client.get("/projects").json()["projects"] if p["repo_url"].endswith("gominsu08/2025_Engine_TeamProject"))
        systems = client.get(f"/projects/{project['id']}/systems").json()["systems"]
        system = next(s for s in systems if s["name"] == "Machine")
        base = f"/projects/{project['id']}/systems/{system['id']}"
        generation = {"status": "previously_generated"} if args.resume_revision else wait(post(base + "/generate")["job"])
        first = client.get(base + "/revisions").json()["revisions"][0]
        comment_text = "포트폴리오 초안에 참고할 수 있도록 Machine의 공통 동작과 개별 기계의 차이를 더 자세히 풀어주세요. 확인되지 않은 담당 여부·개발 의도·성능 수치는 단정하지 말아주세요."
        existing = client.get(base + "/comments").json()["comments"]
        comment = next((c for c in existing if c["base_revision_id"] == first["id"] and c["text"] == comment_text), None)
        if not comment:
            comment = post(base + "/comments", {"base_revision_id": first["id"], "kind": "emphasis", "text": comment_text})["comment"]
        revision_job = wait(post(base + "/revise", {"base_revision_id": first["id"], "comment_ids": [comment["id"]]})["job"])
        versions = client.get(base + "/revisions").json()["revisions"]
        latest = versions[0]
        assert latest["number"] == first["number"] + 1 and latest["parent_id"] == first["id"]
        assert latest["comment_ids"] == [comment["id"]]
        assert next(r for r in versions if r["id"] == first["id"])["document"] == first["document"]
        export = post(f"/projects/{project['id']}/exports", {"revision_ids": [latest["id"]], "include_unreviewed": True})
        report = {"project_id": project["id"], "system_id": system["id"], "model": latest["model"], "revision_numbers": [first["number"], latest["number"]],
                  "generation_job": generation, "revision_job": revision_job, "evidence_count": len(latest["evidence"]),
                  "prose_characters": sum(len(b["text"]) for b in latest["document"]["blocks"]), "comment_applied": True}
        folder = ROOT / ".runtime"
        folder.mkdir(exist_ok=True)
        (folder / "live-ai-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "machine-ai-retrospective.md").write_text(export["markdown"], encoding="utf-8")
        print(json.dumps({"ok": True, "model": report["model"], "revisions": report["revision_numbers"], "prose_characters": report["prose_characters"], "evidence_count": report["evidence_count"]}), flush=True)


if __name__ == "__main__":
    main()
