from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now, uid


class Visitor(Base):
    __tablename__ = "visitor_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[int] = mapped_column(default=now)
    expires_at: Mapped[int]


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    visitor_id: Mapped[str] = mapped_column(ForeignKey("visitor_sessions.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    repo_url: Mapped[str] = mapped_column(String(500))
    repo_owner: Mapped[str] = mapped_column(String(100))
    repo_name: Mapped[str] = mapped_column(String(100))
    github_username: Mapped[str] = mapped_column(String(100))
    project_type: Mapped[str] = mapped_column(String(20))
    ref: Mapped[str] = mapped_column(String(255), default="")
    config_version: Mapped[int] = mapped_column(default=1)
    snapshot_id: Mapped[str | None] = mapped_column(String(32))
    current_run_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[int] = mapped_column(default=now)
    updated_at: Mapped[int] = mapped_column(default=now)
    deleted: Mapped[bool] = mapped_column(default=False)


class ConfigVersion(Base):
    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int]
    snapshot_id: Mapped[str | None] = mapped_column(String(32))
    selected_file_ids: Mapped[list] = mapped_column(JSON, default=list)
    classifications: Mapped[dict] = mapped_column(JSON, default=dict)
    attribution: Mapped[dict] = mapped_column(JSON, default=dict)
    github_username: Mapped[str] = mapped_column(String(100))
    project_type: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[int] = mapped_column(default=now)


class Snapshot(Base):
    __tablename__ = "snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    ref: Mapped[str] = mapped_column(String(255))
    commit_sha: Mapped[str] = mapped_column(String(40))
    tree_sha: Mapped[str] = mapped_column(String(40))
    repository_id: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    history: Mapped[list] = mapped_column(JSON, default=list)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(default=now)


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("snapshot_id", "path"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(Text)
    blob_sha: Mapped[str] = mapped_column(String(40))
    size: Mapped[int]
    category: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(300))
    content: Mapped[str | None] = mapped_column(Text)
    encoding: Mapped[str | None] = mapped_column(String(30))
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    config_id: Mapped[str] = mapped_column(ForeignKey("config_versions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    created_at: Mapped[int] = mapped_column(default=now)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class System(Base):
    __tablename__ = "systems"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    group_key: Mapped[str] = mapped_column(String(500))
    file_ids: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(default=1)
    current_revision_id: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Revision(Base):
    __tablename__ = "explanation_revisions"
    __table_args__ = (UniqueConstraint("system_id", "number"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id", ondelete="CASCADE"), index=True)
    config_id: Mapped[str] = mapped_column(ForeignKey("config_versions.id", ondelete="CASCADE"))
    system_version: Mapped[int]
    number: Mapped[int]
    parent_id: Mapped[str | None] = mapped_column(String(32))
    document: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    comment_ids: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100), default="")
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(default=now)


class Comment(Base):
    __tablename__ = "comment_versions"
    __table_args__ = (UniqueConstraint("root_id", "version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    root_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(default=1)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id", ondelete="CASCADE"), index=True)
    base_revision_id: Mapped[str] = mapped_column(ForeignKey("explanation_revisions.id", ondelete="CASCADE"))
    block_id: Mapped[str | None] = mapped_column(String(150))
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="general")
    deleted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[int] = mapped_column(default=now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "available_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    stage: Mapped[str] = mapped_column(String(200), default="대기 중")
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[str | None] = mapped_column(String(32))
    lease_until: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[int] = mapped_column(default=now)
    created_at: Mapped[int] = mapped_column(default=now)
    updated_at: Mapped[int] = mapped_column(default=now)


class Idempotency(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("visitor_id", "key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    visitor_id: Mapped[str] = mapped_column(ForeignKey("visitor_sessions.id"))
    key: Mapped[str] = mapped_column(String(150))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(default=now)


class ToolRun(Base):
    __tablename__ = "tool_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    arguments: Mapped[dict] = mapped_column(JSON)
    result_summary: Mapped[dict] = mapped_column(JSON)
    duration_ms: Mapped[int]
    created_at: Mapped[int] = mapped_column(default=now)


class Budget(Base):
    __tablename__ = "ai_budgets"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    used_tokens: Mapped[int] = mapped_column(default=0)
    reserved_tokens: Mapped[int] = mapped_column(default=0)


class Export(Base):
    __tablename__ = "exports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    revision_ids: Mapped[list] = mapped_column(JSON)
    markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(default=now)


class OperationalState(Base):
    __tablename__ = "operational_state"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[int] = mapped_column(default=now)


class RequestQuota(Base):
    __tablename__ = "request_quotas"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[int] = mapped_column(index=True)
