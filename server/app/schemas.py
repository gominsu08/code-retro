from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(Input):
    repo_url: str = Field(max_length=500)
    github_username: str = Field(min_length=1, max_length=40)
    project_type: Literal["solo", "team"]
    name: str = Field(default="", max_length=200)
    ref: str = Field(default="", max_length=255)

    @field_validator("github_username")
    @classmethod
    def clean_username(cls, value):
        import re
        value = value.strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", value):
            raise ValueError("GitHub 아이디 형식을 확인해주세요.")
        return value

    @field_validator("ref")
    @classmethod
    def clean_ref(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("브랜치·태그에 제어문자를 사용할 수 없습니다.")
        return value.strip()


class ProjectPatch(Input):
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    github_username: str = Field(min_length=1, max_length=40)
    project_type: Literal["solo", "team"]

    _clean_username = field_validator("github_username")(ProjectCreate.clean_username.__func__)


class Ownership(Input):
    status: Literal["unknown", "mine", "shared", "other"]
    account: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=2000)


class ScopeUpdate(Input):
    expected_version: int = Field(ge=1)
    selected_file_ids: list[str] = Field(max_length=1000)
    classifications: dict[str, Literal["project", "external", "generated", "uncertain"]] = Field(default_factory=dict)
    attribution: dict[str, Ownership] = Field(default_factory=dict)


class AnalyzeRequest(Input):
    expected_version: int = Field(ge=1)
    use_ai: bool = False
    manual_identity: bool = False


class SnapshotRequest(Input):
    expected_version: int = Field(ge=1)
    ref: str = Field(default="", max_length=255)

    _clean_ref = field_validator("ref")(ProjectCreate.clean_ref.__func__)


class SystemUpdate(Input):
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    file_ids: list[str] = Field(min_length=1, max_length=1000)


class CommentCreate(Input):
    base_revision_id: str
    block_id: str | None = None
    text: str = Field(min_length=1, max_length=4000)
    kind: Literal["general", "ownership", "intent", "emphasis", "correction"] = "general"

    @field_validator("text")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("코멘트를 입력해주세요.")
        return value.strip()


class CommentEdit(Input):
    expected_version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=4000)
    deleted: bool = False

    _nonempty = field_validator("text")(CommentCreate.nonempty.__func__)


class ReviseRequest(Input):
    base_revision_id: str
    comment_ids: list[str] = Field(min_length=1, max_length=20)


class ReviewRequest(Input):
    base_revision_id: str
    reviewed: bool


class ExportRequest(Input):
    revision_ids: list[str] = Field(min_length=1, max_length=100)
    include_unreviewed: bool = False


class Block(Input):
    block_id: str
    section: str
    title: str
    text: str = Field(min_length=1, max_length=10000)
    claim_ids: list[str]


class Claim(Input):
    claim_id: str
    statement: str
    basis: Literal["code_observation", "history_observation", "user_statement", "inference"]
    status: Literal["supported", "needs_confirmation", "conflicting"]
    evidence_ids: list[str]


class Explanation(Input):
    title: str
    summary: str
    blocks: list[Block] = Field(min_length=1, max_length=12)
    claims: list[Claim] = Field(min_length=1, max_length=40)
    open_questions: list[str] = Field(max_length=10)
    applied_comment_ids: list[str]


class FilesArgs(Input):
    query: str
    limit: int = Field(ge=1, le=100)


class ReadCodeArgs(Input):
    file_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class SymbolArgs(Input):
    query: str
    limit: int = Field(ge=1, le=80)


class RelationArgs(Input):
    symbol_id: str


class FileHistoryArgs(Input):
    file_id: str


class EmptyArgs(Input):
    pass
