import hashlib
import json
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .config import get_settings
from .db import now
from .errors import AppError
from .models import AnalysisRun, Comment, ConfigVersion, Idempotency, Job, Project, Revision, Snapshot, SourceFile, System, Visitor

ACTIVE = ("queued", "running", "waiting_retry", "cancel_requested")
TERMINAL = ("succeeded", "partial", "failed", "cancelled")


def owned_project(db, visitor, project_id) -> Project:
    p = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if not p or p.deleted or p.visitor_id != visitor.id:
        raise AppError("not_found", "이 세션에서 프로젝트를 찾을 수 없습니다.", 404)
    return p


def config_for(db, project) -> ConfigVersion:
    config = db.scalar(select(ConfigVersion).where(ConfigVersion.project_id == project.id, ConfigVersion.version == project.config_version))
    if not config:
        raise AppError("configuration_missing", "프로젝트 설정을 찾을 수 없습니다.", 409)
    return config


def version_check(actual, expected):
    if actual != expected:
        raise AppError("version_conflict", "다른 변경 사항이 있습니다. 최신 내용을 불러온 뒤 다시 시도해주세요.", 409)


def fork_config(db, project, *, selected=None, classifications=None, attribution=None, snapshot_id=None):
    old = config_for(db, project)
    config = ConfigVersion(project_id=project.id, version=project.config_version + 1,
                           snapshot_id=snapshot_id or old.snapshot_id,
                           selected_file_ids=selected if selected is not None else old.selected_file_ids,
                           classifications=classifications if classifications is not None else old.classifications,
                           attribution=attribution if attribution is not None else old.attribution,
                           github_username=project.github_username, project_type=project.project_type)
    db.add(config)
    project.config_version = config.version
    project.updated_at = now()
    db.flush()
    return config


def owned_system(db, project, system_id):
    s = db.get(System, system_id)
    run = db.get(AnalysisRun, s.run_id) if s else None
    if not s or not run or run.project_id != project.id:
        raise AppError("not_found", "프로젝트의 시스템을 찾을 수 없습니다.", 404)
    return s, run


def get_revision(db, system, revision_id):
    r = db.get(Revision, revision_id)
    if not r or r.system_id != system.id:
        raise AppError("not_found", "설명 버전을 찾을 수 없습니다.", 404)
    return r


def latest_comments(db, system_id, include_deleted=False):
    all_comments = db.scalars(select(Comment).where(Comment.system_id == system_id).order_by(Comment.created_at, Comment.version)).all()
    latest = {}
    for comment in all_comments:
        if comment.root_id not in latest or latest[comment.root_id].version < comment.version:
            latest[comment.root_id] = comment
    return [c for c in latest.values() if include_deleted or not c.deleted]


def revision_is_current(db, project, system, revision):
    c = db.get(ConfigVersion, revision.config_id)
    return bool(c and c.version == project.config_version and revision.system_version == system.version
                and project.current_run_id == system.run_id and system.current_revision_id == revision.id)


def enqueue(db, project, kind, payload):
    db.scalar(select(Visitor).where(Visitor.id == project.visitor_id).with_for_update())
    count = db.scalar(select(func.count()).select_from(Job).join(Project).where(Project.visitor_id == project.visitor_id, Job.status.in_(ACTIVE)))
    if count:
        raise AppError("job_in_progress", "이미 진행 중인 작업이 있습니다. 완료하거나 취소한 뒤 진행해주세요.", 409)
    waiting = db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE)))
    if waiting >= 20:
        raise AppError("queue_full", "서버의 작업 대기열이 가득 찼습니다. 잠시 후 다시 시도해주세요.", 429)
    job = Job(project_id=project.id, kind=kind, payload=payload)
    db.add(job)
    db.flush()
    return job


def idempotent(db, visitor, key, route, body, action):
    if not key or len(key) > 150:
        raise AppError("idempotency_required", "요청 식별자가 필요합니다.")
    request_hash = hashlib.sha256(json.dumps([route, body], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    previous = db.scalar(select(Idempotency).where(Idempotency.visitor_id == visitor.id, Idempotency.key == key))
    if previous:
        if previous.request_hash != request_hash:
            raise AppError("idempotency_conflict", "같은 요청 식별자로 다른 내용을 보낼 수 없습니다.", 409)
        return previous.response
    result = action()
    db.add(Idempotency(visitor_id=visitor.id, key=key, request_hash=request_hash, response=result))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.scalar(select(Idempotency).where(Idempotency.visitor_id == visitor.id, Idempotency.key == key))
        if previous and previous.request_hash == request_hash:
            return previous.response
        raise AppError("version_conflict", "요청이 동시에 변경되었습니다. 최신 상태를 확인해주세요.", 409) from None
    return result


def project_view(db, p):
    config = config_for(db, p)
    snapshot = db.get(Snapshot, p.snapshot_id) if p.snapshot_id else None
    jobs = db.scalars(select(Job).where(Job.project_id == p.id).order_by(Job.created_at.desc()).limit(5)).all()
    return {"id": p.id, "name": p.name, "repo_url": p.repo_url, "github_username": p.github_username,
            "project_type": p.project_type, "ref": p.ref, "config_version": p.config_version,
            "current_run_id": p.current_run_id, "created_at": p.created_at,
            "scope": {"selected_file_ids": config.selected_file_ids, "classifications": config.classifications, "attribution": config.attribution},
            "snapshot": {"id": snapshot.id, "ref": snapshot.ref, "commit_sha": snapshot.commit_sha,
                         "metadata": snapshot.metadata_json, "coverage": snapshot.coverage} if snapshot else None,
            "jobs": [job_view(j) for j in jobs]}


def job_view(j):
    return {"id": j.id, "project_id": j.project_id, "kind": j.kind, "status": j.status, "stage": j.stage,
            "progress": j.progress, "result": j.result, "error": {"code": j.error_code, "message": j.error_message} if j.error_code else None,
            "attempts": j.attempts, "available_at": j.available_at, "updated_at": j.updated_at}


def file_view(f):
    return {"id": f.id, "path": f.path, "size": f.size, "category": f.category, "reason": f.reason,
            "error": f.error, "collected": f.content is not None,
            "namespaces": f.parsed.get("namespaces", []), "symbol_count": len(f.parsed.get("symbols", [])),
            "parse_errors": f.parsed.get("has_errors", False)}


def revision_view(db, project, system, revision):
    return {"id": revision.id, "system_id": system.id, "number": revision.number, "parent_id": revision.parent_id,
            "document": revision.document, "evidence": revision.evidence, "comment_ids": revision.comment_ids,
            "source": revision.source, "model": revision.model, "reviewed": revision.reviewed,
            "stale": not revision_is_current(db, project, system, revision), "created_at": revision.created_at}


def code_evidence(snapshot, project, file, start, end):
    line_count = len((file.content or "").splitlines())
    if file.snapshot_id != snapshot.id or start < 1 or end < start or end > line_count:
        raise AppError("invalid_evidence", "현재 코드 범위를 벗어난 근거입니다.")
    url = f"{project.repo_url}/blob/{snapshot.commit_sha}/{quote(file.path, safe='/')}#L{start}-L{end}"
    evidence_id = f"code:{file.id}:{start}:{end}"
    return evidence_id, {"kind": "code", "file_id": file.id, "path": file.path, "snapshot_id": snapshot.id,
                         "commit_sha": snapshot.commit_sha, "blob_sha": file.blob_sha, "start_line": start,
                         "end_line": end, "url": url}


def validate_scope(db, snapshot_id, file_ids):
    if len(file_ids) != len(set(file_ids)):
        raise AppError("duplicate_files", "분석 파일 목록에 중복이 있습니다.")
    files = db.scalars(select(SourceFile).where(SourceFile.snapshot_id == snapshot_id, SourceFile.id.in_(file_ids))).all()
    if len(files) != len(file_ids):
        raise AppError("invalid_scope", "다른 버전 또는 다른 프로젝트의 파일이 포함되어 있습니다.")
    settings = get_settings()
    if len(files) > settings.max_files or sum(f.size for f in files) > settings.max_total_bytes:
        raise AppError("scope_limit", f"분석 범위를 {settings.max_files}개 파일, {settings.max_total_bytes // 1048576}MiB 이내로 줄여주세요.")
    if any(f.category in ("unsupported", "oversize") for f in files):
        raise AppError("unsupported_scope", "크기 초과 파일이나 링크 파일은 분석에 포함할 수 없습니다.")
    return files
