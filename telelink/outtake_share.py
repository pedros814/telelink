"""Publish a local file to GitHub for phone download (outtake QR)."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from telelink.config import expand_path

DEFAULT_OUTTAKE_REPO = "telelink-sharing"
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_OUTTAKE_STAMP_RE = re.compile(r"-(\d{8})-(\d{6})-[a-f0-9]{8}(?:\.[^.]+)?$", re.I)


def slug_kebab(text: str, *, maxlen: int = 100) -> str:
    """Lowercase kebab-case (e.g. telelink-sharing, screenshot-2026-05-27)."""
    s = (text or "").strip().lower()
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if maxlen > 0:
        s = s[:maxlen].rstrip("-")
    return s


def normalize_github_owner(owner: str, *, login: str = "") -> str:
    """GitHub usernames are case-insensitive; use lowercase."""
    return (owner or login or "").strip().lower()


def normalize_github_repo(repo: str) -> str:
    """Repo folder names: kebab-case, default telelink-sharing."""
    raw = (repo or DEFAULT_OUTTAKE_REPO).strip()
    return slug_kebab(raw, maxlen=100) or DEFAULT_OUTTAKE_REPO


def _github_cfg(config: dict[str, Any]) -> dict[str, Any]:
    outtake = config.get("outtake", {}) or {}
    gh = outtake.get("github", {}) or {}
    if not gh and "github" in config:
        gh = config.get("github", {}) or {}
    return gh


def github_token(config: dict[str, Any]) -> str:
    import os

    gh = _github_cfg(config)
    return (
        (gh.get("token") or "").strip()
        or os.environ.get("TELELINK_GITHUB_TOKEN", "").strip()
        or os.environ.get("GITHUB_TOKEN", "").strip()
    )


def github_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Resolved outtake GitHub settings (lowercase owner, kebab-case repo paths)."""
    return resolve_github_target(config)


def resolve_github_target(config: dict[str, Any]) -> dict[str, Any]:
    gh = _github_cfg(config)
    outtake = config.get("outtake", {}) or {}
    token = github_token(config)
    login = ""
    if token:
        try:
            login = github_api_user(token)
        except RuntimeError:
            pass
    owner = normalize_github_owner((gh.get("owner") or "").strip(), login=login)
    repo = normalize_github_repo((gh.get("repo") or "").strip())
    branch = ((gh.get("branch") or "main").strip() or "main").lower()
    prefix = slug_kebab((gh.get("path_prefix") or "outtake").strip("/")) or "outtake"
    prefer = (outtake.get("prefer") or gh.get("prefer") or "auto").strip().lower()
    return {
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "path_prefix": prefix,
        "prefer": prefer,
        "token": token,
        "login": login,
    }


def parse_github_remote(url: str) -> tuple[str, str] | None:
    url = (url or "").strip().rstrip("/")
    if not url:
        return None
    m = re.match(r"(?:https?://|git@)github\.com[:/]([^/]+)/([^/.]+)", url, re.I)
    if m:
        return m.group(1), m.group(2).removesuffix(".git")
    return None


def raw_content_url(owner: str, repo: str, branch: str, repo_path: str) -> str:
    path = repo_path.lstrip("/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{quote(branch, safe='')}/{quote(path, safe='/')}"


def _repo_path_for_file(local: Path, path_prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:8]
    stem = slug_kebab(local.stem, maxlen=80) or "file"
    ext = local.suffix.lower()
    name = f"{stem}-{stamp}-{short}{ext}"
    prefix = path_prefix.strip("/")
    return f"{prefix}/{name}" if prefix else name


def _git_run(repo_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo_dir), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        check=check,
    )


def git_available() -> bool:
    return shutil.which("git") is not None


def find_git_repo(config: dict[str, Any]) -> Path | None:
    candidates: list[Path] = [Path.cwd()]
    out_dir = config.get("output", {}).get("dir")
    if out_dir:
        candidates.append(expand_path(str(out_dir)) / "outtake-repo")

    seen: set[str] = set()
    for base in candidates:
        key = str(base)
        if key in seen:
            continue
        seen.add(key)
        if (base / ".git").is_dir():
            return base
    return None


def git_remote_github(repo_dir: Path) -> tuple[str, str] | None:
    try:
        r = _git_run(repo_dir, "remote", "get-url", "origin", check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return parse_github_remote((r.stdout or "").strip())


def git_repo_ready(config: dict[str, Any]) -> tuple[Path, str, str] | None:
    if not git_available():
        return None
    repo_dir = find_git_repo(config)
    if not repo_dir:
        return None
    gh = github_settings(config)
    owner, repo = gh["owner"], gh["repo"]
    if not owner or not repo:
        parsed = git_remote_github(repo_dir)
        if parsed:
            owner, repo = parsed
    if not owner or not repo:
        return None
    return repo_dir, owner, repo


def _api_request(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "telelink-outtake",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(detail)
            msg = err.get("message") or detail
        except json.JSONDecodeError:
            msg = detail or str(exc)
        raise RuntimeError(f"GitHub API {exc.code}: {msg}") from exc


def github_api_user(token: str) -> str:
    data = _api_request("GET", "https://api.github.com/user", token)
    login = (data.get("login") or "").strip()
    if not login:
        raise RuntimeError("GitHub token is valid but returned no username")
    return login


def _find_existing_repo(token: str, login: str, repo_slug: str) -> tuple[str, str] | None:
    """Match repo by kebab name (case-insensitive), return canonical owner/name from GitHub."""
    target = repo_slug.lower()
    page = 1
    while page <= 10:
        url = f"https://api.github.com/user/repos?per_page=100&page={page}&affiliation=owner"
        try:
            batch = _api_request("GET", url, token)
        except RuntimeError:
            return None
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            name = (item.get("name") or "").strip()
            if name.lower() != target:
                continue
            owner_obj = item.get("owner") or {}
            owner_login = (owner_obj.get("login") or login).strip()
            if owner_login:
                return owner_login, name
        if len(batch) < 100:
            break
        page += 1
    return None


def ensure_github_repo(config: dict[str, Any]) -> dict[str, Any]:
    """Ensure outtake repo exists; create telelink-sharing-style repo when missing."""
    target = resolve_github_target(config)
    owner, repo, token = target["owner"], target["repo"], target["token"]
    if not owner:
        raise ValueError(
            "GitHub owner required — set outtake.github.owner in config.yaml "
            "(or use a token so your username is detected)"
        )
    if not token:
        raise ValueError(
            "GitHub token required — set outtake.github.token or GITHUB_TOKEN"
        )

    created = False
    repo_url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        meta = _api_request("GET", repo_url, token)
        owner = (meta.get("owner") or {}).get("login") or owner
        repo = meta.get("name") or repo
        return {**target, "owner": owner, "repo": repo, "created": created}
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise

    found = _find_existing_repo(token, target["login"] or owner, repo)
    if found:
        owner, repo = found
        return {**target, "owner": owner, "repo": repo, "created": created}

    login = target["login"] or github_api_user(token)
    if owner.lower() != login.lower():
        raise RuntimeError(
            f"GitHub repository {owner}/{repo} was not found. "
            f"Create it at https://github.com/new?name={quote(repo)} (owner must be {owner!r})."
        ) from exc

    try:
        meta = _api_request(
            "POST",
            "https://api.github.com/user/repos",
            token,
            {
                "name": repo,
                "private": False,
                "auto_init": True,
                "description": "TeleLink outtake — shared files for phone QR download",
            },
        )
        created = True
        owner = (meta.get("owner") or {}).get("login") or login
        repo = meta.get("name") or repo
    except RuntimeError as create_exc:
        raise RuntimeError(
            f"Could not create GitHub repository {owner}/{repo}. "
            f"Create it at https://github.com/new?name={quote(repo)} "
            f"(token needs repo scope). {create_exc}"
        ) from create_exc

    return {**target, "owner": owner, "repo": repo, "created": created}


def share_via_api(local: Path, config: dict[str, Any]) -> str:
    gh = ensure_github_repo(config)
    owner, repo, branch = gh["owner"], gh["repo"], gh["branch"]
    token = gh["token"]

    repo_path = _repo_path_for_file(local, gh["path_prefix"])
    api_base = f"https://api.github.com/repos/{owner}/{repo}/contents/{quote(repo_path, safe='/')}"
    sha = ""
    try:
        existing = _api_request("GET", f"{api_base}?ref={quote(branch)}", token)
        sha = existing.get("sha", "") or ""
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise

    content_b64 = base64.b64encode(local.read_bytes()).decode("ascii")
    body: dict[str, Any] = {
        "message": f"outtake: {local.name}",
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    _api_request("PUT", api_base, token, body)
    return raw_content_url(owner, repo, branch, repo_path)


def share_via_git(local: Path, config: dict[str, Any]) -> str:
    ready = git_repo_ready(config)
    if not ready:
        raise RuntimeError("No git repo with GitHub remote found for outtake")
    repo_dir, owner, repo = ready
    gh = ensure_github_repo(config)
    owner, repo = gh["owner"], gh["repo"]
    branch = gh["branch"]
    repo_path = _repo_path_for_file(local, gh["path_prefix"])
    dest = repo_dir / Path(*repo_path.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local, dest)

    rel = dest.relative_to(repo_dir)
    _git_run(repo_dir, "add", "--", str(rel).replace("\\", "/"))
    commit = _git_run(repo_dir, "commit", "-m", f"outtake: {local.name}", check=False)
    if commit.returncode != 0:
        err = (commit.stderr or commit.stdout or "git commit failed").strip()
        raise RuntimeError(err)
    push = _git_run(repo_dir, "push", "origin", branch, check=False)
    if push.returncode != 0:
        push = _git_run(repo_dir, "push", "-u", "origin", branch, check=False)
    if push.returncode != 0:
        err = (push.stderr or push.stdout or "git push failed").strip()
        raise RuntimeError(err)
    return raw_content_url(owner, repo, branch, repo_path)


def share_file(local: Path, config: dict[str, Any]) -> str:
    """Upload file via git or GitHub API; return raw download URL."""
    if not local.is_file():
        raise FileNotFoundError(f"Not a file: {local}")
    prefer = github_settings(config)["prefer"]
    if prefer == "api":
        return share_via_api(local, config)
    if prefer == "git":
        return share_via_git(local, config)

    if git_repo_ready(config):
        try:
            return share_via_git(local, config)
        except (OSError, subprocess.TimeoutExpired, RuntimeError):
            pass
    return share_via_api(local, config)


def _clean_path_part(part: str) -> str:
    return part.strip().strip('"').strip("'")


def resolve_local_paths(parts: list[str]) -> list[Path] | None:
    """Resolve CLI args to local files. Multiple args = multiple files (or one spaced path)."""
    if not parts:
        return None
    cleaned = [_clean_path_part(p) for p in parts]
    cleaned = [p for p in cleaned if p]
    if not cleaned:
        return None

    joined = expand_path(" ".join(cleaned))
    if joined.is_file():
        return [joined]

    if len(cleaned) > 1:
        paths: list[Path] = []
        for raw in cleaned:
            p = expand_path(raw)
            if not p.is_file():
                return None
            paths.append(p)
        return paths

    p = expand_path(cleaned[0])
    if p.is_file():
        return [p]
    return None


def resolve_local_path(parts: list[str]) -> Path | None:
    paths = resolve_local_paths(parts)
    if paths and len(paths) == 1:
        return paths[0]
    return None


def _unique_zip_name(path: Path, used: dict[str, int]) -> str:
    name = path.name
    if name not in used:
        used[name] = 0
        return name
    used[name] += 1
    return f"{path.stem}-{used[name]}{path.suffix}"


def zip_local_files(paths: list[Path]) -> Path:
    """Bundle multiple files into a temporary zip for upload."""
    if len(paths) < 2:
        raise ValueError("zip_local_files requires at least two paths")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    fd, name = tempfile.mkstemp(prefix=f"outtake-{stamp}-", suffix=".zip")
    os.close(fd)
    zip_path = Path(name)
    used: dict[str, int] = {}
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in paths:
                zf.write(p, arcname=_unique_zip_name(p, used))
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise
    return zip_path


def prepare_share_file(paths: list[Path]) -> tuple[Path, bool]:
    """Return (upload path, is_temp). Zips when more than one file."""
    if not paths:
        raise ValueError("No files to share")
    if len(paths) == 1:
        return paths[0], False
    return zip_local_files(paths), True


def confirm_public_outtake(paths: list[Path], *, config: dict[str, Any] | None = None) -> bool:
    """Warn that GitHub upload is public; require 1/yes to continue."""
    from telelink.prompts import confirm_choice

    details = [
        "This will be pushed to GitHub and may be seen by anyone",
        "browsing the repo, raw URLs, or search engines.",
    ]
    if config:
        gh = github_settings(config)
        if gh.get("owner") and gh.get("repo"):
            details.append(f"Destination: {gh['owner']}/{gh['repo']}")
    if len(paths) == 1:
        details.append(f"File: {paths[0]}")
    else:
        details.append(f"Files: {len(paths)} (will be zipped)")
        for p in paths:
            details.append(f"  {p.name}  ({p.parent})")

    return confirm_choice(
        title="Public upload",
        details=details,
        yes_label="Yes — upload to GitHub",
        no_label="No — abort",
    )


def outtake_auto_delete_seconds(config: dict[str, Any]) -> int | None:
    """Resolved TTL for GitHub outtake files (None = never delete)."""
    outtake = config.get("outtake", {}) or {}
    ttl = outtake.get("auto_delete_seconds")
    if ttl is not None:
        return ttl
    from telelink.duration import parse_duration

    return parse_duration(outtake.get("auto_delete"))


def outtake_auto_delete_poll_seconds(config: dict[str, Any]) -> float:
    outtake = config.get("outtake", {}) or {}
    poll = outtake.get("auto_delete_poll_seconds")
    if poll:
        return float(poll)
    from telelink.duration import parse_duration

    parsed = parse_duration(outtake.get("auto_delete_poll"))
    return float(parsed) if parsed else 1800.0


def _parse_github_datetime(value: str) -> datetime | None:
    """Parse GitHub committer/author ISO-8601 timestamps."""
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_outtake_upload_time(name: str) -> datetime | None:
    """Fallback UTC time from outtake filename (…-YYYYMMDD-HHMMSS-xxxxxxxx.ext)."""
    m = _OUTTAKE_STAMP_RE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def github_file_pushed_at(
    config: dict[str, Any],
    repo_path: str,
    *,
    target: dict[str, Any] | None = None,
) -> datetime | None:
    """When this path was last committed on GitHub (committer date), or None if unknown."""
    gh = target or resolve_github_target(config)
    owner, repo, branch, token = (
        gh["owner"],
        gh["repo"],
        gh["branch"],
        gh["token"],
    )
    if not owner or not repo or not token:
        return None

    path = repo_path.lstrip("/")
    url = (
        f"https://api.github.com/repos/{owner}/{repo}/commits"
        f"?path={quote(path, safe='/')}&sha={quote(branch)}&per_page=1"
    )
    try:
        data = _api_request("GET", url, token)
    except RuntimeError:
        return None
    if not isinstance(data, list) or not data:
        return None

    commit = data[0].get("commit") if isinstance(data[0], dict) else None
    if not isinstance(commit, dict):
        return None
    committer = commit.get("committer") or {}
    author = commit.get("author") or {}
    if isinstance(committer, dict):
        pushed = _parse_github_datetime(str(committer.get("date") or ""))
        if pushed is not None:
            return pushed
    if isinstance(author, dict):
        return _parse_github_datetime(str(author.get("date") or ""))
    return None


def outtake_file_age(
    config: dict[str, Any],
    *,
    repo_path: str,
    name: str,
    target: dict[str, Any] | None = None,
) -> tuple[datetime | None, str]:
    """Return (upload/push time UTC, source) — GitHub commit date preferred over filename."""
    pushed = github_file_pushed_at(config, repo_path, target=target)
    if pushed is not None:
        return pushed, "github"
    parsed = parse_outtake_upload_time(name)
    if parsed is not None:
        return parsed, "filename"
    return None, ""


def list_github_outtake_files(config: dict[str, Any]) -> list[dict[str, Any]]:
    """List file entries under outtake path_prefix via GitHub Contents API."""
    target = resolve_github_target(config)
    owner, repo, branch, token = (
        target["owner"],
        target["repo"],
        target["branch"],
        target["token"],
    )
    if not owner or not repo or not token:
        return []

    prefix = (target["path_prefix"] or "outtake").strip("/")
    url = (
        f"https://api.github.com/repos/{owner}/{repo}/contents/"
        f"{quote(prefix, safe='/')}?ref={quote(branch)}"
    )
    try:
        data = _api_request("GET", url, token)
    except RuntimeError as exc:
        if "404" in str(exc):
            return []
        raise

    if isinstance(data, dict):
        return [data] if data.get("type") == "file" else []
    if not isinstance(data, list):
        return []
    return [item for item in data if item.get("type") == "file"]


def delete_github_outtake_file(config: dict[str, Any], repo_path: str, sha: str) -> None:
    target = resolve_github_target(config)
    owner, repo, branch, token = (
        target["owner"],
        target["repo"],
        target["branch"],
        target["token"],
    )
    if not token:
        raise ValueError("GitHub token required for outtake auto-delete")
    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}/contents/"
        f"{quote(repo_path.lstrip('/'), safe='/')}"
    )
    _api_request(
        "DELETE",
        api_url,
        token,
        {
            "message": f"outtake: auto-delete {Path(repo_path).name}",
            "sha": sha,
            "branch": branch,
        },
    )


def prune_outtake_github(config: dict[str, Any]) -> int:
    """Delete GitHub outtake files older than outtake.auto_delete. Returns count removed."""
    ttl = outtake_auto_delete_seconds(config)
    if not ttl or ttl <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl)
    target = resolve_github_target(config)
    removed = 0
    for item in list_github_outtake_files(config):
        name = (item.get("name") or "").strip()
        path = (item.get("path") or "").strip()
        sha = (item.get("sha") or "").strip()
        if not name or not path or not sha:
            continue
        pushed_at, _source = outtake_file_age(
            config, repo_path=path, name=name, target=target
        )
        if pushed_at is None or pushed_at >= cutoff:
            continue
        delete_github_outtake_file(config, path, sha)
        removed += 1
    return removed
