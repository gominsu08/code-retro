import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath

import tree_sitter_c_sharp as csharp
from tree_sitter import Language, Parser

PARSER_VERSION = "csharp-tree-sitter-v1"
TYPE_KINDS = {"class_declaration", "interface_declaration", "struct_declaration", "record_declaration", "enum_declaration"}
MEMBER_KINDS = {"method_declaration", "constructor_declaration", "property_declaration", "event_declaration"}


def _text(node):
    return node.text.decode("utf-8", errors="strict") if node else ""


def parse_csharp(content: str, file_id: str) -> dict:
    parser = Parser(Language(csharp.language()))
    root = parser.parse(content.encode("utf-8")).root_node
    symbols, calls, imports, namespaces = [], [], [], []
    stack = [(root, "", "")]
    while stack:
        node, namespace, containing_type = stack.pop()
        name = _text(node.child_by_field_name("name"))
        if node.type == "file_scoped_namespace_declaration":
            namespace = name
            namespaces.append(namespace)
        elif node.type == "namespace_declaration":
            namespace = ".".join(p for p in (namespace, name) if p)
            namespaces.append(namespace)
        if node.type == "using_directive":
            imports.append(_text(node)[:200])
        if node.type in TYPE_KINDS | MEMBER_KINDS:
            start = node.start_point.row + 1
            end = max(start, node.end_point.row + (1 if node.end_point.column else 0))
            base = next((n for n in node.named_children if n.type == "base_list"), None)
            modifiers = [_text(n) for n in node.children if n.type == "modifier"]
            symbol = {"id": f"{file_id}:{node.start_byte}", "name": name, "kind": node.type,
                      "namespace": namespace, "containing_type": containing_type,
                      "qualified_name": ".".join(p for p in (namespace, containing_type, name) if p),
                      "start_line": start, "end_line": end, "bases": _text(base).lstrip(": "),
                      "modifiers": modifiers, "type": _text(node.child_by_field_name("type")),
                      "signature": _text(node).split("{")[0].split("=>")[0].strip()[:500]}
            symbols.append(symbol)
            if node.type in TYPE_KINDS:
                containing_type = ".".join(p for p in (containing_type, name) if p)
        elif node.type in ("field_declaration", "event_field_declaration"):
            declaration = next((n for n in node.named_children if n.type == "variable_declaration"), None)
            if declaration:
                for variable in declaration.named_children:
                    if variable.type != "variable_declarator":
                        continue
                    field_name = _text(variable.child_by_field_name("name"))
                    symbols.append({"id": f"{file_id}:{variable.start_byte}", "name": field_name, "kind": node.type,
                                    "namespace": namespace, "containing_type": containing_type,
                                    "qualified_name": ".".join(p for p in (namespace, containing_type, field_name) if p),
                                    "start_line": node.start_point.row + 1, "end_line": node.end_point.row + 1,
                                    "type": _text(declaration.child_by_field_name("type")), "bases": "", "modifiers": [],
                                    "signature": _text(node)[:500]})
        elif node.type == "invocation_expression":
            function = node.child_by_field_name("function")
            calls.append({"name": _text(function)[:200], "line": node.start_point.row + 1, "type": containing_type,
                          "certainty": "syntax_only"})
        if node.type == "compilation_unit":
            file_namespace = next((n for n in node.named_children if n.type == "file_scoped_namespace_declaration"), None)
            if file_namespace:
                namespace = _text(file_namespace.child_by_field_name("name"))
        for child in reversed(node.named_children):
            stack.append((child, namespace, containing_type))
    namespaces = [n for n in namespaces if n]
    symbols.sort(key=lambda s: (s["start_line"], s["id"]))
    return {"parser_version": PARSER_VERSION, "has_errors": root.has_error,
            "line_count": len(content.splitlines()), "namespaces": sorted(set(namespaces)),
            "symbols": symbols[:2000], "calls": calls[:2000], "imports": imports[:200],
            "truncated": len(symbols) > 2000 or len(calls) > 2000,
            "style_hints": {"underscore_fields": sum(s["name"].startswith("_") for s in symbols if s["kind"] == "field_declaration"),
                            "tabs_present": "\t" in content, "note": "코드 스타일은 신원이나 인원수의 증거가 아닙니다."}}


def group_key(path: str) -> str:
    parts = list(PurePosixPath(path).parts[:-1])
    for i, part in enumerate(parts):
        if part.lower() in ("system", "systems") and i + 1 < len(parts):
            return "/".join(parts[:i + 2])
    if len(parts) > 1:
        return "/".join(parts)
    return "공통 코드"


def grouping(files) -> list[dict]:
    groups = defaultdict(list)
    for f in files:
        groups[group_key(f.path)].append(f)
    result = []
    for key, members in sorted(groups.items()):
        names = Counter(n for f in members for n in f.parsed.get("namespaces", []))
        result.append({"group_key": key, "name": key.split("/")[-1], "file_ids": [f.id for f in members],
                       "summary": {"grouping_basis": "folder_and_syntax", "namespaces": list(names),
                                   "file_count": len(members), "symbol_count": sum(len(f.parsed.get("symbols", [])) for f in members),
                                   "note": "폴더·구문 기반 분류 초안입니다. 시스템 이름과 파일 소속을 수정할 수 있습니다."}})
    return result


def relations(files, symbol_id: str) -> dict:
    symbols = [(f, s) for f in files for s in f.parsed.get("symbols", [])]
    target = next(((f, s) for f, s in symbols if s["id"] == symbol_id), None)
    if not target:
        return {"relations": [], "note": "현재 분석 범위에서 심볼을 찾지 못했습니다."}
    target_file, symbol = target
    matches = []
    pattern = re.compile(r"\b" + re.escape(symbol["name"]) + r"\b")
    for f in files:
        if not f.content:
            continue
        for line, text in enumerate(f.content.splitlines(), 1):
            if pattern.search(text) and not (f.id == target_file.id and line == symbol["start_line"]):
                matches.append({"file_id": f.id, "path": f.path, "line": line, "certainty": "name_match_candidate"})
                if len(matches) >= 80:
                    return {"relations": matches, "truncated": True, "note": "이름 기반 후보이며 실행 연결·정확한 타입 해석은 아닙니다."}
    return {"relations": matches, "truncated": False, "note": "이름 기반 후보이며 실행 연결·정확한 타입 해석은 아닙니다."}
