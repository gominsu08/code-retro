import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import ROOT, get_settings
from .body_limit import BodyLimitMiddleware
from .operations import check_storage, enforce_request_limits
from .db import get_db, init_db, now, uid
from .errors import AppError
from .exporting import markdown_export
from .github import parse_repo_url
from .models import AnalysisRun, Comment, ConfigVersion, Export, Job, OperationalState, Project, Revision, Snapshot, SourceFile, System, ToolRun, Visitor
from .schemas import AnalyzeRequest, CommentCreate, CommentEdit, ExportRequest, ProjectCreate, ProjectPatch, ReviewRequest, ReviseRequest, ScopeUpdate, SnapshotRequest, SystemUpdate
from .security import COOKIE, check_origin, csrf, digest, require_visitor
from .services import ACTIVE, config_for, enqueue, file_view, get_revision, idempotent, job_view, latest_comments, owned_project, owned_system, project_view, revision_is_current, revision_view, validate_scope, version_check, fork_config

settings = get_settings()
log = logging.getLogger("code_retro")


@asynccontextmanager
async def lifespan(_app):
    if settings.app_env == "development":
        init_db()
    if settings.app_env == "production" and (not settings.cookie_secure or not settings.public_base_url.startswith("https://")):
        raise RuntimeError("Production requires HTTPS and COOKIE_SECURE=true.")
    yield


app = FastAPI(title="Code Retro", version="0.1.0", lifespan=lifespan, docs_url="/api/docs" if settings.app_env == "development" else None, redoc_url=None)
app.add_middleware(BodyLimitMiddleware)
DB = Depends(get_db)
VisitorAuth = Depends(require_visitor)


@app.middleware("http")
async def headers(request, call_next):
    try:
        await run_in_threadpool(enforce_request_limits, request)
    except AppError as exc:
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)
    try:
        content_length = int(request.headers.get("content-length", "0") or "0")
        if content_length < 0:
            raise ValueError
    except ValueError:
        return JSONResponse({"error": {"code": "invalid_input", "message": "요청 크기 형식이 올바르지 않습니다."}}, status_code=400)
    if content_length > 1_048_576:
        return JSONResponse({"error": {"code": "request_too_large", "message": "요청 크기가 너무 큽니다."}}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif settings.app_env == "production":
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    return response


@app.exception_handler(AppError)
async def app_error(_request, exc):
    return JSONResponse({"error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable}}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def input_error(_request, exc):
    return JSONResponse({"error": {"code": "invalid_input", "message": "입력한 형식과 길이를 확인해주세요.",
                                   "fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}}, status_code=422)


@app.exception_handler(IntegrityError)
async def conflict_error(_request, _exc):
    return JSONResponse({"error": {"code": "version_conflict", "message": "동시에 변경된 내용이 있습니다. 새로고침 후 다시 시도해주세요."}}, status_code=409)


@app.get("/api/health")
def health(db: Session = DB):
    db.execute(text("SELECT 1"))
    if settings.app_env == "production":
        heartbeat = db.get(OperationalState, "worker")
        if not heartbeat or heartbeat.updated_at < now() - 240:
            return JSONResponse({"status": "starting", "worker": "unavailable"}, status_code=503)
    return {"status": "ok"}


@app.post("/api/v1/session")
def session(request: Request, response: Response, db: Session = DB):
    check_origin(request)
    token = request.cookies.get(COOKIE, "")
    visitor = db.scalar(select(Visitor).where(Visitor.token_hash == digest(token), Visitor.expires_at > now())) if token else None
    if not visitor:
        token = secrets.token_urlsafe(32)
        visitor = Visitor(token_hash=digest(token), expires_at=now() + settings.session_days * 86400)
        db.add(visitor)
    visitor.expires_at = now() + settings.session_days * 86400
    db.commit()
    response.set_cookie(COOKIE, token, max_age=settings.session_days * 86400, httponly=True,
                        secure=settings.cookie_secure, samesite="lax", path="/")
    return {"csrf_token": csrf(token), "session_id": visitor.id,
            "capabilities": {"ai_enabled": settings.ai_ready, "model": settings.ai_model if settings.ai_ready else None,
                             "max_files": settings.max_files, "max_total_bytes": settings.max_total_bytes}}


@app.get("/api/v1/projects")
def projects(visitor=VisitorAuth, db: Session = DB):
    rows = db.scalars(select(Project).where(Project.visitor_id == visitor.id, Project.deleted.is_(False)).order_by(Project.updated_at.desc())).all()
    return {"projects": [project_view(db, p) for p in rows]}


@app.post("/api/v1/projects", status_code=202)
def create_project(body: ProjectCreate, visitor=VisitorAuth, db: Session = DB, idempotency_key: str = Header(default="")):
    def action():
        check_storage(db, creating_project=True)
        db.scalar(select(Visitor).where(Visitor.id == visitor.id).with_for_update())
        count = db.scalar(select(func.count()).select_from(Project).where(Project.visitor_id == visitor.id, Project.deleted.is_(False)))
        if count >= settings.max_projects_per_session:
            raise AppError("project_limit", f"프로젝트를 {settings.max_projects_per_session}개까지 저장할 수 있습니다.")
        owner, repo, url = parse_repo_url(body.repo_url)
        p = Project(visitor_id=visitor.id, name=body.name.strip() or repo, repo_url=url, repo_owner=owner, repo_name=repo,
                    github_username=body.github_username, project_type=body.project_type, ref=body.ref)
        db.add(p)
        db.flush()
        db.add(ConfigVersion(project_id=p.id, version=1, github_username=p.github_username, project_type=p.project_type))
        job = enqueue(db, p, "prepare", {"expected_version": 1, "ref": p.ref})
        return {"project_id": p.id, "job": job_view(job)}
    return idempotent(db, visitor, idempotency_key, "projects.create", body.model_dump(), action)


@app.get("/api/v1/projects/{project_id}")
def project_detail(project_id: str, visitor=VisitorAuth, db: Session = DB):
    return project_view(db, owned_project(db, visitor, project_id))


@app.patch("/api/v1/projects/{project_id}")
def update_project(project_id: str, body: ProjectPatch, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    version_check(p.config_version, body.expected_version)
    p.name, p.github_username, p.project_type = body.name, body.github_username, body.project_type
    fork_config(db, p)
    db.commit()
    return project_view(db, p)


@app.delete("/api/v1/projects/{project_id}")
def delete_project(project_id: str, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    p.deleted = True
    p.updated_at = now()
    db.execute(update(Job).where(Job.project_id == p.id, Job.status.in_(ACTIVE)).values(status="cancel_requested", updated_at=now()))
    db.commit()
    return {"deleted": True}


@app.post("/api/v1/projects/{project_id}/snapshots", status_code=202)
def refresh_snapshot(project_id: str, body: SnapshotRequest, visitor=VisitorAuth, db: Session = DB, idempotency_key: str = Header(default="")):
    def action():
        p = owned_project(db, visitor, project_id)
        version_check(p.config_version, body.expected_version)
        job = enqueue(db, p, "prepare", body.model_dump())
        return {"job": job_view(job)}
    return idempotent(db, visitor, idempotency_key, f"{project_id}/snapshot", body.model_dump(), action)


@app.get("/api/v1/projects/{project_id}/files")
def files(project_id: str, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    files = db.scalars(select(SourceFile).where(SourceFile.snapshot_id == p.snapshot_id).order_by(SourceFile.path)).all() if p.snapshot_id else []
    return {"files": [file_view(f) for f in files]}


@app.get("/api/v1/projects/{project_id}/files/{file_id}")
def read_file(project_id: str, file_id: str, start: int = 1, end: int = 120, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    f = db.get(SourceFile, file_id)
    snap = db.get(Snapshot, f.snapshot_id) if f else None
    if not f or not snap or snap.project_id != p.id:
        raise AppError("not_found", "파일을 찾을 수 없습니다.", 404)
    if f.content is None:
        raise AppError("file_not_collected", "분석을 실행하면 선택한 파일의 코드를 확인할 수 있습니다.", 409)
    lines = f.content.splitlines()
    if start < 1 or end < start or end - start >= 200 or start > len(lines):
        raise AppError("invalid_range", "코드는 한 번에 최대 200줄까지 확인할 수 있습니다.")
    return {**file_view(f), "start_line": start, "end_line": min(end, len(lines)), "line_count": len(lines),
            "content": "\n".join(lines[start - 1:end]), "symbols": f.parsed.get("symbols", []), "commit_sha": snap.commit_sha}


@app.put("/api/v1/projects/{project_id}/scope")
def update_scope(project_id: str, body: ScopeUpdate, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    version_check(p.config_version, body.expected_version)
    if not p.snapshot_id:
        raise AppError("snapshot_missing", "저장소 연결을 먼저 완료해주세요.", 409)
    validate_scope(db, p.snapshot_id, body.selected_file_ids)
    all_ids = set(db.scalars(select(SourceFile.id).where(SourceFile.snapshot_id == p.snapshot_id)).all())
    if not set(body.classifications).union(body.attribution).issubset(all_ids):
        raise AppError("invalid_scope", "현재 저장소에 없는 파일 설정입니다.")
    fork_config(db, p, selected=body.selected_file_ids, classifications=body.classifications,
                attribution={k: v.model_dump() for k, v in body.attribution.items()})
    db.commit()
    return project_view(db, p)


@app.post("/api/v1/projects/{project_id}/analyses", status_code=202)
def analyze(project_id: str, body: AnalyzeRequest, visitor=VisitorAuth, db: Session = DB, idempotency_key: str = Header(default="")):
    def action():
        p = owned_project(db, visitor, project_id)
        version_check(p.config_version, body.expected_version)
        config = config_for(db, p)
        if not config.snapshot_id or not config.selected_file_ids:
            raise AppError("empty_scope", "분석할 C# 파일을 선택해주세요.")
        validate_scope(db, config.snapshot_id, config.selected_file_ids)
        snapshot = db.get(Snapshot, config.snapshot_id)
        checked = snapshot.metadata_json.get("identity_checked", "").lower() == config.github_username.lower()
        if not body.manual_identity and (not checked or not snapshot.metadata_json.get("user_exists")):
            raise AppError("identity_confirmation", "계정 확인이 필요합니다. 저장소를 다시 확인하거나 담당 범위를 직접 지정한다고 선택해주세요.", 409)
        if body.use_ai and not settings.ai_ready:
            raise AppError("ai_disabled", "서버의 AI 연결이 아직 활성화되지 않았습니다. 코드 구조 분석은 사용할 수 있습니다.", 503)
        job = enqueue(db, p, "analyze", {"config_id": config.id, "use_ai": body.use_ai})
        return {"job": job_view(job)}
    return idempotent(db, visitor, idempotency_key, f"{project_id}/analyze", body.model_dump(), action)


def system_view(db, p, s):
    rev = db.get(Revision, s.current_revision_id) if s.current_revision_id else None
    return {"id": s.id, "run_id": s.run_id, "name": s.name, "group_key": s.group_key, "file_ids": s.file_ids,
            "version": s.version, "summary": s.summary, "revision": revision_view(db, p, s, rev) if rev else None}


@app.get("/api/v1/projects/{project_id}/systems")
def systems(project_id: str, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    runs = db.scalars(select(AnalysisRun).where(AnalysisRun.project_id == p.id).order_by(AnalysisRun.created_at.desc())).all()
    systems = db.scalars(select(System).where(System.run_id == p.current_run_id).order_by(System.group_key)).all() if p.current_run_id else []
    snapshot = db.get(Snapshot, p.snapshot_id) if p.snapshot_id else None
    return {"systems": [system_view(db, p, s) for s in systems],
            "runs": [{"id": r.id, "status": r.status, "details": r.details} for r in runs],
            "history": snapshot.history if snapshot else []}


@app.patch("/api/v1/projects/{project_id}/systems/{system_id}")
def update_system(project_id: str, system_id: str, body: SystemUpdate, visitor=VisitorAuth, db: Session = DB):
    from .structure import structure_document
    p = owned_project(db, visitor, project_id)
    s, run = owned_system(db, p, system_id)
    version_check(s.version, body.expected_version)
    config = db.get(ConfigVersion, run.config_id)
    if not set(body.file_ids).issubset(config.selected_file_ids):
        raise AppError("invalid_scope", "분석 대상 안에서 파일을 선택해주세요.")
    validate_scope(db, run.snapshot_id, body.file_ids)
    s.name, s.file_ids, s.version = body.name, body.file_ids, s.version + 1
    members = db.scalars(select(SourceFile).where(SourceFile.id.in_(s.file_ids), SourceFile.content.is_not(None))).all()
    document, evidence = structure_document(p, db.get(Snapshot, run.snapshot_id), s, members, config)
    number = (db.scalar(select(func.max(Revision.number)).where(Revision.system_id == s.id)) or 0) + 1
    revision = Revision(system_id=s.id, config_id=config.id, system_version=s.version, number=number,
                        parent_id=s.current_revision_id, document=document, evidence=evidence, source="structure")
    db.add(revision)
    db.flush()
    s.current_revision_id = revision.id
    db.commit()
    return system_view(db, p, s)


@app.get("/api/v1/projects/{project_id}/systems/{system_id}/revisions")
def revisions(project_id: str, system_id: str, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    s, _ = owned_system(db, p, system_id)
    rows = db.scalars(select(Revision).where(Revision.system_id == s.id).order_by(Revision.number.desc())).all()
    return {"revisions": [revision_view(db, p, s, r) for r in rows]}


def comment_view(c):
    return {"id": c.id, "root_id": c.root_id, "version": c.version, "base_revision_id": c.base_revision_id,
            "block_id": c.block_id, "text": c.text, "kind": c.kind, "created_at": c.created_at, "deleted": c.deleted}


@app.get("/api/v1/projects/{project_id}/systems/{system_id}/comments")
def comments(project_id: str, system_id: str, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    s, _ = owned_system(db, p, system_id)
    return {"comments": [comment_view(c) for c in latest_comments(db, s.id)]}


@app.post("/api/v1/projects/{project_id}/systems/{system_id}/comments", status_code=201)
def add_comment(project_id: str, system_id: str, body: CommentCreate, visitor=VisitorAuth, db: Session = DB, idempotency_key: str = Header(default="")):
    def action():
        p = owned_project(db, visitor, project_id)
        s, _ = owned_system(db, p, system_id)
        rev = get_revision(db, s, body.base_revision_id)
        if body.block_id and body.block_id not in {b["block_id"] for b in rev.document.get("blocks", [])}:
            raise AppError("invalid_block", "설명 문단을 찾을 수 없습니다.")
        c = Comment(root_id=uid(), system_id=s.id, **body.model_dump())
        db.add(c)
        db.flush()
        return {"comment": comment_view(c)}
    return idempotent(db, visitor, idempotency_key, f"{project_id}/{system_id}/comment", body.model_dump(), action)


@app.patch("/api/v1/projects/{project_id}/systems/{system_id}/comments/{root_id}")
def edit_comment(project_id: str, system_id: str, root_id: str, body: CommentEdit, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    s, _ = owned_system(db, p, system_id)
    previous = next((c for c in latest_comments(db, s.id, True) if c.root_id == root_id), None)
    if not previous:
        raise AppError("not_found", "코멘트를 찾을 수 없습니다.", 404)
    version_check(previous.version, body.expected_version)
    c = Comment(root_id=root_id, version=previous.version + 1, system_id=s.id, base_revision_id=previous.base_revision_id,
                block_id=previous.block_id, kind=previous.kind, text=body.text, deleted=body.deleted)
    db.add(c)
    db.commit()
    return {"comment": comment_view(c)}


@app.post("/api/v1/projects/{project_id}/systems/{system_id}/generate", status_code=202)
def generate_system(project_id: str, system_id: str, visitor=VisitorAuth, db: Session = DB, idempotency_key: str = Header(default="")):
    def action():
        p = owned_project(db, visitor, project_id)
        s, run = owned_system(db, p, system_id)
        if not settings.ai_ready:
            raise AppError("ai_disabled", "서버의 AI 연결이 아직 활성화되지 않았습니다.", 503)
        version_check(db.get(ConfigVersion, run.config_id).version, p.config_version)
        job = enqueue(db, p, "explain", {"system_id": s.id, "system_version": s.version, "file_ids": s.file_ids,
                                         "config_id": run.config_id, "base_revision_id": s.current_revision_id, "comment_ids": []})
        return {"job": job_view(job)}
    return idempotent(db, visitor, idempotency_key, f"{project_id}/{system_id}/generate", {}, action)


@app.post("/api/v1/projects/{project_id}/systems/{system_id}/revise", status_code=202)
def revise(project_id: str, system_id: str, body: ReviseRequest, visitor=VisitorAuth, db: Session = DB, idempotency_key: str = Header(default="")):
    def action():
        p = owned_project(db, visitor, project_id)
        s, _ = owned_system(db, p, system_id)
        rev = get_revision(db, s, body.base_revision_id)
        if not revision_is_current(db, p, s, rev):
            raise AppError("stale_revision", "최신 설명을 기준으로 코멘트를 적용해주세요.", 409)
        valid = {c.id: c for c in latest_comments(db, s.id) if c.base_revision_id == rev.id}
        if len(set(body.comment_ids)) != len(body.comment_ids) or not set(body.comment_ids).issubset(valid):
            raise AppError("invalid_comments", "현재 설명에 저장된 최신 코멘트만 선택해주세요.", 409)
        if not settings.ai_ready:
            raise AppError("ai_disabled", "코멘트는 저장되었습니다. 설명에 반영하려면 서버의 AI 연결이 필요합니다.", 503)
        job = enqueue(db, p, "explain", {"system_id": s.id, "system_version": s.version, "file_ids": s.file_ids,
                                         "config_id": rev.config_id, **body.model_dump()})
        return {"job": job_view(job)}
    return idempotent(db, visitor, idempotency_key, f"{project_id}/{system_id}/revise", body.model_dump(), action)


@app.put("/api/v1/projects/{project_id}/systems/{system_id}/review")
def review(project_id: str, system_id: str, body: ReviewRequest, visitor=VisitorAuth, db: Session = DB):
    p = owned_project(db, visitor, project_id)
    s, _ = owned_system(db, p, system_id)
    rev = get_revision(db, s, body.base_revision_id)
    if body.reviewed and not revision_is_current(db, p, s, rev):
        raise AppError("stale_revision", "현재 설정의 최신 설명만 검토 완료할 수 있습니다.", 409)
    rev.reviewed = body.reviewed
    db.commit()
    return revision_view(db, p, s, rev)


@app.post("/api/v1/projects/{project_id}/exports", status_code=201)
def export(project_id: str, body: ExportRequest, visitor=VisitorAuth, db: Session = DB, idempotency_key: str = Header(default="")):
    def action():
        p = owned_project(db, visitor, project_id)
        rows, seen = [], set()
        for rid in body.revision_ids:
            r = db.get(Revision, rid)
            if not r:
                raise AppError("not_found", "설명을 찾을 수 없습니다.", 404)
            s, _ = owned_system(db, p, r.system_id)
            if s.id in seen or not revision_is_current(db, p, s, r):
                raise AppError("stale_revision", "시스템별 최신 설명을 한 개씩 선택해주세요.", 409)
            if not r.reviewed and not body.include_unreviewed:
                raise AppError("review_required", "검토하지 않은 설명이 있습니다. 검토하거나 미검토 포함을 선택해주세요.", 409)
            seen.add(s.id)
            rows.append(r)
        e = Export(project_id=p.id, revision_ids=body.revision_ids, markdown=markdown_export(db, p, rows))
        db.add(e)
        db.flush()
        return {"id": e.id, "markdown": e.markdown, "created_at": e.created_at}
    return idempotent(db, visitor, idempotency_key, f"{project_id}/export", body.model_dump(), action)


def owned_job(db, visitor, job_id):
    job = db.get(Job, job_id)
    if not job:
        raise AppError("not_found", "작업을 찾을 수 없습니다.", 404)
    owned_project(db, visitor, job.project_id)
    return job


@app.get("/api/v1/jobs/{job_id}")
def job_status(job_id: str, visitor=VisitorAuth, db: Session = DB):
    return job_view(owned_job(db, visitor, job_id))


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str, visitor=VisitorAuth, db: Session = DB):
    j = owned_job(db, visitor, job_id)
    if j.status in ACTIVE:
        j.status = "cancel_requested" if j.status == "running" else "cancelled"
        j.stage = "취소 요청을 처리하고 있습니다" if j.status == "cancel_requested" else "작업을 취소했습니다"
        j.error_code = j.error_message = None
        j.updated_at = now()
    db.commit()
    return job_view(j)


@app.post("/api/v1/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, visitor=VisitorAuth, db: Session = DB, idempotency_key: str = Header(default="")):
    def action():
        j = owned_job(db, visitor, job_id)
        if j.status not in ("failed", "cancelled", "partial"):
            raise AppError("job_not_retryable", "종료된 작업만 다시 실행할 수 있습니다.", 409)
        p = owned_project(db, visitor, j.project_id)
        if j.kind == "prepare":
            version_check(p.config_version, j.payload["expected_version"])
        else:
            version_check(p.config_version, db.get(ConfigVersion, j.payload["config_id"]).version)
        if j.kind == "explain":
            s, _ = owned_system(db, p, j.payload["system_id"])
            version_check(s.version, j.payload["system_version"])
            if s.current_revision_id != j.payload["base_revision_id"]:
                raise AppError("stale_revision", "설명이 변경되었습니다. 최신 설명에서 다시 요청해주세요.", 409)
        retry = enqueue(db, p, j.kind, j.payload)
        return {"job": job_view(retry)}
    return idempotent(db, visitor, idempotency_key, f"{job_id}/retry", {}, action)


@app.get("/api/v1/jobs/{job_id}/tools")
def tool_runs(job_id: str, visitor=VisitorAuth, db: Session = DB):
    owned_job(db, visitor, job_id)
    rows = db.scalars(select(ToolRun).where(ToolRun.job_id == job_id).order_by(ToolRun.created_at)).all()
    return {"tools": [{"name": r.name, "arguments": r.arguments, "summary": r.result_summary, "duration_ms": r.duration_ms} for r in rows]}


dist = ROOT / "web" / "dist"
if (dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise AppError("not_found", "API 경로를 찾을 수 없습니다.", 404)
    if path == "favicon.svg":
        return FileResponse(ROOT / "web" / "public" / "favicon.svg")
    if (dist / "index.html").is_file():
        return FileResponse(dist / "index.html")
    return JSONResponse({"message": "개발 화면은 http://127.0.0.1:5173 에서 확인해주세요."})
