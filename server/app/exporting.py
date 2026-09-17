import re

from .models import ConfigVersion, Snapshot, System


def safe_text(text):
    # Exported repository names and AI/user prose remain text, never active HTML.
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_export(db, project, revisions):
    lines = [f"# {safe_text(project.name)} · 개발 회고", "", f"저장소: {project.repo_url}", "",
             "이 문서는 코드 근거와 사용자 코멘트를 바탕으로 정리한 초안입니다. 담당 범위와 설계 의도는 별도로 확인해주세요.", ""]
    labels = {"code_observation": "코드 관찰", "history_observation": "이력 관찰", "user_statement": "사용자 설명", "inference": "추정"}
    for rev in revisions:
        system = db.get(System, rev.system_id)
        config = db.get(ConfigVersion, rev.config_id)
        snapshot = db.get(Snapshot, config.snapshot_id)
        doc = rev.document
        lines += [f"## {safe_text(system.name)}", "", f"설명 v{rev.number} · {'검토 완료' if rev.reviewed else '미검토'} · 기준 계정: {safe_text(config.github_username)}",
                  f"코드 기준: `{snapshot.commit_sha}` · 설정 v{config.version}", "", safe_text(doc.get("summary", "")), ""]
        claims = {c["claim_id"]: c for c in doc.get("claims", [])}
        for block in doc.get("blocks", []):
            lines += [f"### {safe_text(block['title'])}", "", safe_text(block["text"]), ""]
            for cid in block.get("claim_ids", []):
                c = claims.get(cid, {})
                label = labels.get(c.get("basis"), "확인 필요")
                if c.get("status") != "supported":
                    label += " · 확인 필요"
                lines.append(f"- {label}: {safe_text(c.get('statement', ''))}")
                for eid in c.get("evidence_ids", []):
                    e = rev.evidence.get(eid, {})
                    if e.get("kind") == "code":
                        label_path = safe_text(e['path']).replace("[", "\\[").replace("]", "\\]")
                        lines.append(f"  - [{label_path} L{e['start_line']}–{e['end_line']}]({e['url']})")
                    elif e.get("kind") == "comment":
                        lines.append(f"  - 사용자 코멘트: {safe_text(e.get('text', ''))}")
                    elif e.get("kind") == "history" and re.fullmatch(r"[a-f0-9]{40}", e.get("sha", "")):
                        lines.append(f"  - [커밋 {e['sha'][:7]}]({project.repo_url}/commit/{e['sha']})")
            lines.append("")
        if doc.get("open_questions"):
            lines += ["### 추가로 확인할 내용", ""] + [f"- {safe_text(q)}" for q in doc["open_questions"]] + [""]
    return "\n".join(lines).rstrip() + "\n"
