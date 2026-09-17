import hashlib
import secrets

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db, now
from .errors import AppError
from .models import Visitor

COOKIE = "code_retro_session"


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf(token: str) -> str:
    return digest("code-retro-csrf:" + token)


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in get_settings().origins:
        raise AppError("origin_denied", "허용되지 않은 출처의 요청입니다.", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise AppError("origin_denied", "다른 사이트에서 보낸 요청은 허용되지 않습니다.", 403)


def require_visitor(request: Request, db: Session = Depends(get_db)) -> Visitor:
    token = request.cookies.get(COOKIE, "")
    visitor = db.scalar(select(Visitor).where(Visitor.token_hash == digest(token), Visitor.expires_at > now())) if token else None
    if not visitor:
        raise AppError("session_expired", "작업 세션이 만료되었습니다. 새로고침 후 다시 시작해주세요.", 401)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        check_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(supplied, csrf(token)):
            raise AppError("csrf_denied", "세션을 새로고침한 뒤 다시 시도해주세요.", 403)
        if request.method != "DELETE" and not request.url.path.endswith("/cancel"):
            from .operations import check_storage
            check_storage(db)
    return visitor
