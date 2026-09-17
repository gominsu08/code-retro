from .analysis import TYPE_KINDS
from .services import code_evidence


def structure_document(project, snapshot, system, files, config):
    evidence, claims, blocks = {}, [], []
    types = [(f, s) for f in files for s in f.parsed.get("symbols", []) if s["kind"] in TYPE_KINDS]
    selected = sorted(types, key=lambda fs: (fs[1]["name"].lower() != system.name.lower(),
                                            "abstract" not in fs[1]["modifiers"],
                                            fs[1]["kind"] != "class_declaration", not bool(fs[1]["bases"]), fs[0].path))[:6]
    paragraphs, claim_ids = [], []
    for index, (file, symbol) in enumerate(selected):
        start, end = symbol["start_line"], min(symbol["end_line"], symbol["start_line"] + 80)
        eid, ref = code_evidence(snapshot, project, file, start, end)
        evidence[eid] = ref
        name = symbol["qualified_name"] or symbol["name"]
        abstract = "abstract로 선언된 " if "abstract" in symbol["modifiers"] else ""
        statement = f"{abstract}{name} 선언을 확인했습니다."
        if symbol["bases"]:
            statement += f" 기반 타입 목록에는 {symbol['bases']}가 지정되어 있습니다."
        members = [s for s in file.parsed.get("symbols", []) if s["containing_type"].split(".")[-1] == symbol["name"]]
        fields = [s for s in members if s["kind"] in ("field_declaration", "property_declaration")][:5]
        methods = [s["name"] for s in members if s["kind"] == "method_declaration"][:5]
        text = statement
        if fields:
            text += " 이 타입에서 " + ", ".join(f"{s['name']} ({s['type'] or '타입 확인 필요'})" for s in fields) + " 필드·프로퍼티를 확인할 수 있습니다."
        if methods:
            text += " 선언된 메서드에는 " + ", ".join(methods) + "가 있습니다. 실제 처리 순서는 메서드 본문과 호출부를 함께 확인해야 합니다."
        paragraphs.append(text)
        cid = f"structure-{index + 1}"
        claim_ids.append(cid)
        claims.append({"claim_id": cid, "statement": statement, "basis": "code_observation", "status": "supported", "evidence_ids": [eid]})
        # Long classes need separate line references for members outside the first excerpt.
        for member in fields + [s for s in members if s["name"] in methods]:
            mid, mref = code_evidence(snapshot, project, file, member["start_line"], min(member["end_line"], member["start_line"] + 40))
            evidence[mid] = mref
            if mid not in claims[-1]["evidence_ids"]:
                claims[-1]["evidence_ids"].append(mid)
    if paragraphs:
        blocks.append({"block_id": "structure", "section": "implementation", "title": "코드에서 확인한 구조", "text": "\n\n".join(paragraphs), "claim_ids": claim_ids})
    states = [config.attribution.get(f.id, {}).get("status", "unknown") for f in files]
    ownership = f"현재 기준 계정은 {config.github_username}입니다. "
    if config.project_type == "solo":
        ownership += "개인 프로젝트로 설정되어 있습니다. 포함한 외부 코드와 본인이 작성한 코드는 구분해서 확인해주세요."
    else:
        ownership += f"선택 파일 중 직접 내 코드로 지정한 파일은 {states.count('mine')}개, 공동 작업으로 지정한 파일은 {states.count('shared')}개입니다. 네임스페이스나 코드 스타일만으로 작성자를 확정하지 않습니다."
    claims.append({"claim_id": "confirm-intent", "statement": "설계 의도와 실제 담당 범위는 사용자 확인이 필요합니다.", "basis": "inference", "status": "needs_confirmation", "evidence_ids": []})
    blocks.append({"block_id": "review", "section": "ownership", "title": "회고를 위한 확인", "text": ownership + "\n\n이 내용은 구문 분석으로 만든 구조 메모입니다. AI 설명을 생성하면 연결되는 코드 본문을 도구로 읽고 설계 선택, 데이터 구성, 동작 흐름을 문단으로 정리합니다. 당시 이 구조를 선택한 이유와 이후 확장한 기능을 코멘트로 남겨주세요.", "claim_ids": ["confirm-intent"]})
    return {"title": system.name, "summary": f"{len(files)}개 파일에서 {len(types)}개 타입 선언을 확인했습니다. 폴더 기준 시스템 분류 초안입니다.",
            "blocks": blocks, "claims": claims, "open_questions": ["이 시스템에서 직접 개발한 부분과 공동 작업한 부분은 무엇인가요?", "상속·데이터 분리 등 현재 구조를 선택한 배경이 있었나요?"], "applied_comment_ids": []}, evidence
