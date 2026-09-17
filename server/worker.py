"""Durable database queue. Run independently: python -m server.worker."""
import logging
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

from sqlalchemy import func, or_, select, text, update

from .app.analysis import grouping, parse_csharp
from .app.config import get_settings
from .app.db import db_session, engine, init_db, now, uid
from .app.errors import AppError, LostLease
from .app.github import GitHubClient
from .app.models import AnalysisRun, ConfigVersion, Job, Project, Revision, Snapshot, SourceFile, System
from .app.services import fork_config, version_check
from .app.structure import structure_document
from .app.operations import check_storage, cleanup_expired, enabled as public_limits_enabled, worker_heartbeat

log = logging.getLogger("code_retro.worker")
settings = get_settings()
shutdown = threading.Event()


def claim_job():
    with db_session() as db:
        if engine.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(73104291)"))
        db.execute(update(Job).where(Job.status == "cancel_requested", Job.lease_until < now()).values(status="cancelled", lease_token=None, updated_at=now()))
        db.execute(update(Job).where(Job.status == "running", Job.lease_until < now(), Job.attempts >= 3).values(
            status="failed", error_code="worker_interrupted", error_message="작업이 반복해서 중단되었습니다. 다시 시도해주세요.", lease_token=None, updated_at=now()))
        running = db.scalar(select(func.count()).select_from(Job).where(Job.status == "running", Job.lease_until >= now()))
        if running >= settings.global_job_limit:
            return None
        candidate = db.scalar(select(Job).where(or_(Job.status.in_(["queued", "waiting_retry"]), (Job.status == "running") & (Job.lease_until < now())),
                                                     Job.available_at <= now(), Job.attempts < 3).order_by(Job.created_at).limit(1).with_for_update(skip_locked=True))
        if not candidate:
            return None
        candidate.status, candidate.lease_token = "running", uid()
        candidate.lease_until, candidate.updated_at = now() + settings.job_lease_seconds, now()
        candidate.attempts += 1
        candidate.error_code = candidate.error_message = None
        return candidate.id, candidate.lease_token


@contextmanager
def guarded(job_id, token):
    with db_session() as db:
        project_id = db.scalar(select(Job.project_id).where(Job.id == job_id))
        p = db.scalar(select(Project).where(Project.id == project_id).with_for_update()) if project_id else None
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if not job or job.lease_token != token or job.lease_until < now() or job.status not in ("running", "cancel_requested"):
            raise LostLease()
        if job.status == "cancel_requested":
            raise AppError("cancelled", "작업을 취소했습니다.")
        if not p or p.deleted:
            raise AppError("cancelled", "삭제한 프로젝트의 작업을 취소했습니다.")
        yield db, job


def progress(job_id, token, stage, **details):
    with guarded(job_id, token) as (_db, job):
        job.stage, job.progress, job.updated_at = stage, {**job.progress, **details}, now()


class Heartbeat:
    def __init__(self, job_id, token):
        self.job_id, self.token = job_id, token
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        while not self.stop.wait(max(2, settings.job_lease_seconds // 4)):
            try:
                with db_session() as db:
                    result = db.execute(update(Job).where(Job.id == self.job_id, Job.lease_token == self.token,
                                                         Job.lease_until >= now(), Job.status.in_(["running", "cancel_requested"])).values(lease_until=now() + settings.job_lease_seconds))
                    if not result.rowcount:
                        return
                worker_heartbeat()
            except Exception:
                log.warning("Heartbeat update failed for job %s", self.job_id)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=5)


def prepare(job_id, token):
    with guarded(job_id, token) as (db, job):
        project = db.get(Project, job.project_id)
        expected, ref = job.payload["expected_version"], job.payload.get("ref", "")
    progress(job_id, token, "저장소·브랜치와 C# 파일 목록 확인 중", completed=0, total=1)
    with GitHubClient(settings) as github:
        data = github.inspect(project.repo_owner, project.repo_name, ref, project.github_username)
    with guarded(job_id, token) as (db, job):
        project = db.scalar(select(Project).where(Project.id == job.project_id).with_for_update())
        version_check(project.config_version, expected)
        snapshot = Snapshot(project_id=project.id, ref=data["ref"], commit_sha=data["commit_sha"], tree_sha=data["tree_sha"],
                            repository_id=data["repository_id"], metadata_json=data["metadata"], coverage=data["coverage"])
        db.add(snapshot)
        db.flush()
        files = [SourceFile(snapshot_id=snapshot.id, **f) for f in data["files"]]
        db.add_all(files)
        db.flush()
        selected, total_size = [], 0
        for file in files:
            if file.category == "project" and len(selected) < settings.max_files and total_size + file.size <= settings.max_total_bytes:
                selected.append(file.id)
                total_size += file.size
        project.snapshot_id, project.ref = snapshot.id, snapshot.ref
        fork_config(db, project, snapshot_id=snapshot.id, selected=selected, classifications={}, attribution={})
        job.status = "succeeded" if snapshot.coverage.get("tree_complete") else "partial"
        job.stage = "분석 범위를 선택해주세요"
        job.progress = {"completed": 1, "total": 1, "files_found": len(files)}
        job.result = {"snapshot_id": snapshot.id, "selected_count": len(selected), "file_count": len(files)}
        job.lease_token, job.lease_until, job.updated_at = None, 0, now()


def analyze(job_id, token):
    with guarded(job_id, token) as (db, job):
        project = db.get(Project, job.project_id)
        config = db.get(ConfigVersion, job.payload["config_id"])
        snapshot = db.get(Snapshot, config.snapshot_id)
        files = db.scalars(select(SourceFile).where(SourceFile.snapshot_id == snapshot.id, SourceFile.id.in_(config.selected_file_ids)).order_by(SourceFile.path)).all()
        use_ai = job.payload.get("use_ai", False)
        existing_run_id = job.result.get("run_id")
    if not files:
        raise AppError("empty_scope", "분석할 파일이 없습니다.")
    if not existing_run_id:
        progress(job_id, token, "선택한 C# 파일 수집·구문 분석 중", completed=0, total=len(files))
        completed, errors = 0, []
        def collect(file):
            if file.content is not None and file.parsed:
                return file.id, file.content, file.encoding, file.parsed, None
            for attempt in range(2):
                try:
                    with GitHubClient(settings) as github:
                        content, encoding = github.read_file(project.repo_owner, project.repo_name, snapshot.commit_sha, file.path, file.blob_sha)
                    return file.id, content, encoding, parse_csharp(content, file.id), None
                except AppError as exc:
                    if attempt == 0 and exc.code == "github_network":
                        shutdown.wait(1)
                        continue
                    return file.id, None, None, {}, exc
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(collect, f) for f in files]
            try:
                for future in as_completed(futures):
                    file_id, content, encoding, parsed, error = future.result()
                    with guarded(job_id, token) as (db, job):
                        file = db.get(SourceFile, file_id)
                        if error:
                            file.error = error.message
                            errors.append(file.path)
                        else:
                            check_storage(db)
                            file.content, file.encoding, file.parsed, file.error = content, encoding, parsed, None
                        completed += 1
                        job.progress = {"completed": completed, "total": len(files), "failed_files": len(errors)}
                        job.updated_at = now()
            finally:
                for future in futures:
                    future.cancel()
        history_warning = None
        try:
            with GitHubClient(settings) as github:
                history = github.history(project.repo_owner, project.repo_name, snapshot.commit_sha, limit=min(30, settings.max_history_commits))
        except AppError as exc:
            history, history_warning = [], exc.message
        with guarded(job_id, token) as (db, job):
            project = db.scalar(select(Project).where(Project.id == job.project_id).with_for_update())
            snapshot = db.get(Snapshot, config.snapshot_id)
            snapshot.history = history
            files = db.scalars(select(SourceFile).where(SourceFile.id.in_(config.selected_file_ids))).all()
            if not any(f.content is not None for f in files):
                raise AppError("collection_failed", "선택한 코드를 읽지 못했습니다. 파일 오류를 확인하고 다시 시도해주세요.", retryable=True, retry_after=30)
            details = {"selected_count": len(files), "collected_count": sum(f.content is not None for f in files),
                       "failed_files": errors, "parse_error_files": [f.path for f in files if f.parsed.get("has_errors")],
                       "history_warning": history_warning, "history_limit": 30, "history_complete": False,
                       "grouping": "folder_and_syntax", "ai_requested": use_ai}
            run = AnalysisRun(project_id=project.id, snapshot_id=snapshot.id, config_id=config.id, status="running", details=details)
            db.add(run)
            db.flush()
            for group in grouping(files):
                system = System(run_id=run.id, **group)
                db.add(system)
                db.flush()
                members = [f for f in files if f.id in system.file_ids and f.content is not None]
                document, evidence = structure_document(project, snapshot, system, members, config)
                rev = Revision(system_id=system.id, config_id=config.id, system_version=system.version, number=1,
                               document=document, evidence=evidence, source="structure")
                db.add(rev)
                db.flush()
                system.current_revision_id = rev.id
            if project.config_version == config.version:
                project.current_run_id, project.updated_at = run.id, now()
            job.result = {"run_id": run.id}
            existing_run_id = run.id
    if use_ai:
        with guarded(job_id, token) as (db, job):
            systems = db.scalars(select(System).where(System.run_id == existing_run_id).order_by(System.group_key)).all()
        for index, system in enumerate(systems):
            with guarded(job_id, token) as (db, _job):
                rev = db.get(Revision, system.current_revision_id)
                if rev and rev.source == "ai":
                    continue
            progress(job_id, token, f"AI가 {system.name} 설명을 작성하고 있습니다", completed=index, total=len(systems))
            try:
                explain(job_id, token, {"system_id": system.id, "system_version": system.version, "file_ids": system.file_ids,
                                        "config_id": config.id, "base_revision_id": system.current_revision_id, "comment_ids": []}, finish=False)
            except AppError as exc:
                if exc.code == "cancelled":
                    raise
                with guarded(job_id, token) as (db, job):
                    run = db.get(AnalysisRun, existing_run_id)
                    run.details = {**run.details, "ai_warning": exc.message}
                break
    with guarded(job_id, token) as (db, job):
        run = db.get(AnalysisRun, existing_run_id)
        partial = bool(run.details.get("failed_files") or run.details.get("parse_error_files") or run.details.get("history_warning") or run.details.get("ai_warning"))
        run.status = "partial" if partial else "succeeded"
        job.status, job.stage, job.updated_at = run.status, "시스템별 분석 완료", now()
        job.result = {**job.result, "details": run.details}
        job.progress = {**job.progress, "completed": job.progress.get("total", 1)}
        job.lease_token, job.lease_until = None, 0


def explain(job_id, token, payload=None, finish=True):
    from .app.agent import generate_explanation
    with guarded(job_id, token) as (db, job):
        payload = payload or job.payload
        system = db.get(System, payload["system_id"])
        project = db.get(Project, job.project_id)
        config = db.get(ConfigVersion, payload["config_id"])
        version_check(project.config_version, config.version)
        version_check(system.version, payload["system_version"])
        if system.current_revision_id != payload["base_revision_id"]:
            raise AppError("stale_revision", "설명 버전이 바뀌었습니다. 최신 버전에서 다시 요청해주세요.", 409)
    progress(job_id, token, "AI가 관련 코드를 확인하고 설명을 작성하고 있습니다")
    document, evidence, model = generate_explanation(job_id, token, payload)
    with guarded(job_id, token) as (db, job):
        check_storage(db)
        project = db.scalar(select(Project).where(Project.id == job.project_id).with_for_update())
        system = db.get(System, payload["system_id"])
        number = (db.scalar(select(func.max(Revision.number)).where(Revision.system_id == system.id)) or 0) + 1
        revision = Revision(system_id=system.id, config_id=config.id, system_version=payload["system_version"], number=number,
                            parent_id=payload["base_revision_id"], document=document, evidence=evidence,
                            comment_ids=payload["comment_ids"], source="ai", model=model)
        db.add(revision)
        db.flush()
        if system.version == payload["system_version"] and project.config_version == config.version and system.current_revision_id == payload["base_revision_id"]:
            system.current_revision_id = revision.id
        if finish:
            job.status, job.stage = "succeeded", "새 설명 버전을 저장했습니다"
            job.result = {**job.result, "revision_id": revision.id, "system_id": system.id}
            job.lease_token, job.lease_until, job.updated_at = None, 0, now()


def execute_job(job_id, token):
    try:
        with Heartbeat(job_id, token):
            with guarded(job_id, token) as (_db, job):
                kind = job.kind
            {"prepare": prepare, "analyze": analyze, "explain": explain}[kind](job_id, token)
    except LostLease:
        log.info("Lease replaced: %s", job_id)
    except Exception as exc:
        known = isinstance(exc, AppError)
        # Provider exception strings may contain request material. Never print them.
        if not known:
            log.error("Job %s failed with %s", job_id, type(exc).__name__)
        with db_session() as db:
            job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if not job or job.lease_token != token or job.lease_until < now():
                return
            code = exc.code if known else "internal_error"
            cancelled = code == "cancelled" or job.status == "cancel_requested"
            retry = known and exc.retryable and job.attempts < 3 and not cancelled
            job.status = "cancelled" if cancelled else "waiting_retry" if retry else "failed"
            job.error_code = code
            job.error_message = exc.message if known else "작업 중 오류가 발생했습니다. 작업 번호와 함께 운영자에게 알려주세요."
            job.stage = "취소됨" if cancelled else "잠시 후 다시 시도합니다" if retry else "작업 실패"
            job.available_at = now() + (exc.retry_after or 15) if retry else now()
            job.lease_token, job.lease_until, job.updated_at = None, 0, now()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if settings.app_env == "development":
        init_db()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: shutdown.set())
    log.info("Code Retro worker started")
    heartbeat_at, cleanup_at = 0, 0
    while not shutdown.is_set():
        try:
            if now() >= heartbeat_at:
                worker_heartbeat()
                heartbeat_at = now() + 30
            if public_limits_enabled() and now() >= cleanup_at:
                cleanup_expired()
                cleanup_at = now() + 900
            claim = claim_job()
            if claim:
                execute_job(*claim)
            else:
                shutdown.wait(2)
        except Exception as exc:
            log.error("Queue unavailable: %s", type(exc).__name__)
            shutdown.wait(5)


if __name__ == "__main__":
    main()
