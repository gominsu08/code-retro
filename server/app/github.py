import hashlib
import re
from collections import deque
from urllib.parse import quote, urlsplit

import httpx

from .config import Settings
from .errors import AppError

SHA = re.compile(r"^[a-f0-9]{40}$")


def parse_repo_url(value: str) -> tuple[str, str, str]:
    try:
        url = urlsplit(value.strip())
        parts = url.path.strip("/").split("/")
        if url.scheme != "https" or url.hostname != "github.com" or url.port not in (None, 443):
            raise ValueError
        if url.username or url.password or url.query or url.fragment or len(parts) != 2:
            raise ValueError
        owner, repo = parts
        repo = repo.removesuffix(".git")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner):
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repo) or repo in (".", ".."):
            raise ValueError
        return owner, repo, f"https://github.com/{owner}/{repo}"
    except (ValueError, AttributeError):
        raise AppError("invalid_repository", "https://github.com/사용자/저장소 형식으로 입력해주세요.") from None


def classify(path: str, mode: str = "100644") -> tuple[str, str]:
    p = path.lower()
    if mode in ("120000", "160000"):
        return "unsupported", "심볼릭 링크와 서브모듈은 자동으로 따라가지 않습니다."
    if any(s in p.split("/") for s in ("library", "obj", "bin", "temp")) or p.endswith((".g.cs", ".generated.cs", ".designer.cs")):
        return "generated", "빌드·자동 생성 경로 또는 파일 이름 후보"
    external = {"packages", "plugins", "thirdparty", "third-party", "vendor", "external", "boxophobic", "_mk", "textmesh pro", "textmeshpro", "bitgem", "tutorialinfo", "starterassets"}
    if external.intersection(p.split("/")):
        return "external", "패키지·플러그인·외부 에셋 경로 후보"
    if any(s in p.split("/") for s in ("code", "scripts", "src", "source", "sources")):
        return "project", "소스 코드 경로 후보 · 실제 담당과는 별개"
    return "uncertain", "경로만으로 프로젝트 코드인지 확인이 필요합니다."


class GitHubClient:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "CodeRetro/0.1"}
        if settings.github_token.get_secret_value():
            headers["Authorization"] = f"Bearer {settings.github_token.get_secret_value()}"
        self.api = httpx.Client(base_url="https://api.github.com", headers=headers, timeout=25, follow_redirects=False, transport=transport)
        # Authentication headers must never be forwarded to the raw-content host.
        self.raw = httpx.Client(base_url="https://raw.githubusercontent.com", timeout=30, follow_redirects=False, transport=transport)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.api.close()
        self.raw.close()

    def _error(self, response):
        status = response.status_code
        if status == 404:
            raise AppError("github_not_found", "저장소·브랜치를 찾을 수 없거나 공개 접근이 불가능합니다.", 404)
        if status in (403, 429):
            retry_after = response.headers.get("retry-after", "60")
            delay = int(retry_after) if retry_after.isdigit() else 60
            if response.headers.get("x-ratelimit-remaining") == "0":
                import time
                delay = max(delay, int(response.headers.get("x-ratelimit-reset", "0")) - int(time.time()))
            raise AppError("github_rate_limited", "GitHub 요청 한도에 도달했습니다. 대기 후 다시 시도합니다.", 429, retryable=True, retry_after=min(max(delay, 30), 3600))
        if status >= 500:
            raise AppError("github_unavailable", "GitHub 응답이 불안정합니다. 잠시 후 다시 시도합니다.", 503, retryable=True, retry_after=30)
        if status >= 400 or status in range(300, 400):
            raise AppError("github_request_failed", "GitHub 자료를 읽지 못했습니다. 주소와 공개 여부를 확인해주세요.", 502)

    def json(self, path: str, params=None):
        try:
            response = self.api.get(path, params=params)
        except httpx.HTTPError:
            raise AppError("github_network", "GitHub 연결에 실패했습니다.", 503, retryable=True, retry_after=15) from None
        self._error(response)
        try:
            return response.json()
        except ValueError:
            raise AppError("github_bad_response", "GitHub에서 올바른 자료를 받지 못했습니다.", 502) from None

    def inspect(self, owner: str, repo: str, ref: str, username: str):
        prefix = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        metadata = self.json(prefix)
        if metadata.get("private") or metadata.get("visibility", "public") != "public":
            raise AppError("private_repository", "첫 버전에서는 공개 GitHub 저장소만 분석할 수 있습니다.")
        selected_ref = ref or metadata.get("default_branch") or "main"
        commit = self.json(f"{prefix}/commits/{quote(selected_ref, safe='')}")
        sha, tree_sha = commit["sha"], commit["commit"]["tree"]["sha"]
        if not SHA.fullmatch(sha) or not SHA.fullmatch(tree_sha):
            raise AppError("invalid_snapshot", "저장소 버전을 확정하지 못했습니다.", 502)
        user_exists = True
        try:
            self.json(f"/users/{quote(username, safe='')}")
        except AppError as exc:
            if exc.code == "github_not_found":
                user_exists = False
            else:
                raise
        files, coverage = self.tree(prefix, tree_sha)
        return {
            "ref": selected_ref, "commit_sha": sha, "tree_sha": tree_sha,
            "repository_id": metadata["id"], "files": files, "coverage": coverage,
            "metadata": {"full_name": metadata["full_name"], "description": metadata.get("description"),
                         "default_branch": metadata["default_branch"], "user_exists": user_exists,
                         "identity_checked": username, "html_url": metadata["html_url"]},
        }

    def tree(self, prefix: str, tree_sha: str):
        data = self.json(f"{prefix}/git/trees/{tree_sha}", {"recursive": "1"})
        entries = data.get("tree", [])
        pending = []
        requests = 1
        if data.get("truncated"):
            entries = []
            queue = deque([(tree_sha, "")])
            while queue and requests < self.settings.max_tree_requests and len(entries) < self.settings.max_tree_entries:
                sha, parent = queue.popleft()
                subtree = self.json(f"{prefix}/git/trees/{sha}")
                requests += 1
                if subtree.get("truncated"):
                    pending.append(parent or "/")
                for item in subtree.get("tree", []):
                    path = f"{parent}/{item['path']}".lstrip("/")
                    if item["type"] == "tree":
                        queue.append((item["sha"], path))
                    else:
                        entries.append({**item, "path": path})
                    if len(entries) >= self.settings.max_tree_entries:
                        pending.append(parent or "/")
                        break
            pending += [p or "/" for _, p in queue]
        result = []
        for item in entries[:self.settings.max_tree_entries]:
            path = item["path"]
            if not path.lower().endswith(".cs"):
                continue
            if path.startswith("/") or any(p in (".", "..") for p in path.split("/")):
                continue
            category, reason = classify(path, item.get("mode", ""))
            if item.get("size", 0) > self.settings.max_file_bytes:
                category, reason = "oversize", "파일 크기가 개별 수집 한도를 초과합니다."
            result.append({"path": path, "blob_sha": item["sha"], "size": item.get("size", 0), "category": category, "reason": reason})
        return result, {"tree_complete": not pending and len(entries) <= self.settings.max_tree_entries,
                        "uncollected_paths": pending[:100], "entries_seen": len(entries), "tree_requests": requests}

    def read_file(self, owner: str, repo: str, commit: str, path: str, blob_sha: str):
        if not SHA.fullmatch(commit) or not SHA.fullmatch(blob_sha):
            raise AppError("invalid_snapshot", "고정된 코드 버전이 필요합니다.")
        url_path = "/" + "/".join(quote(p, safe="") for p in [owner, repo, commit, *path.split("/")])
        data = bytearray()
        try:
            with self.raw.stream("GET", url_path) as response:
                self._error(response)
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > self.settings.max_file_bytes:
                        raise AppError("file_too_large", "이 파일은 개별 수집 크기 한도를 초과합니다.")
        except httpx.HTTPError:
            raise AppError("github_network", "코드 파일을 가져오지 못했습니다.", 503, retryable=True, retry_after=15) from None
        raw = bytes(data)
        digest = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()
        if digest != blob_sha:
            raise AppError("blob_mismatch", "파일 내용이 고정된 Git 버전과 일치하지 않습니다.", 502)
        if raw.startswith(b"version https://git-lfs.github.com/spec/") or b"\0" in raw[:4096]:
            raise AppError("unsupported_file", "Git LFS 포인터 또는 바이너리 파일은 분석하지 않습니다.")
        for encoding in ("utf-8-sig", "cp949"):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                pass
        raise AppError("unsupported_encoding", "UTF-8 또는 CP949로 읽을 수 없는 파일입니다.")

    def history(self, owner: str, repo: str, commit: str, path: str = "", limit: int = 30):
        params = {"sha": commit, "per_page": min(limit, 100), "page": 1}
        if path:
            params["path"] = path
        data = self.json(f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/commits", params)
        return [{"sha": c["sha"], "author_login": (c.get("author") or {}).get("login"),
                 "author_name": c["commit"]["author"]["name"], "date": c["commit"]["author"]["date"],
                 "message": c["commit"]["message"][:500]} for c in data[:limit]]
