#!/usr/bin/env python3
"""Fail when tracked repository content is unsafe for public publication."""

from __future__ import annotations

import gzip
import os
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DATABASE_SEED = "seed_data/omnitrade.db.gz"
ALLOWED_SEED_TABLES = {
    "portfolio_history_snapshots",
    "signal_outcomes",
    "signals",
    "sqlite_sequence",
    "strategy_history_snapshots",
}
ALLOWED_BINARY_SUFFIXES = {".gif", ".gz", ".ico", ".jpeg", ".jpg", ".pdf", ".png", ".webp"}
MAX_SEED_COMPRESSED_BYTES = 10 * 1024 * 1024
MAX_SEED_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
PLACEHOLDERS = {
    "",
    "changeme",
    "example",
    "fixture",
    "replace_me",
    "test",
    "your_key_here",
}

SENSITIVE_PATH = re.compile(
    r"(^|/)(?:"
    r"\.env(?:\..+)?|"
    r"\.npmrc|\.pypirc|"
    r"credentials(?:\.[^/]+)?|"
    r"id_(?:rsa|ed25519)|"
    r"service-account[^/]*\.json|"
    r"[^/]+\.(?:jks|key|keystore|p12|pem|pfx)"
    r")$",
    re.IGNORECASE,
)
PERSONAL_HOME_PATH = re.compile(rb"/(?:Users|home)/[A-Za-z0-9._-]+/")
EMAIL_ADDRESS = re.compile(rb"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
EMBEDDED_URL_CREDENTIALS = re.compile(rb"https?://[^/\s:@]+:[^/\s@]+@")
SECRET_PATTERNS = {
    "AWS access key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "Anthropic API key": re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "Google API key": re.compile(rb"AIza[0-9A-Za-z_-]{30,}"),
    "OpenAI API key": re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "SendGrid API key": re.compile(rb"SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),
    "Slack token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "Stripe live secret": re.compile(rb"sk_live_[A-Za-z0-9]{16,}"),
}
ASSIGNED_SECRET = re.compile(
    rb"""(?ix)
    ["']?(?:api[_-]?key|client[_-]?secret|password|private[_-]?key|secret|token)["']?
    \s*(?:=|:)\s*
    ["']([^"']{8,})["']
    """
)
ENV_SECRET = re.compile(
    rb"(?m)^[ \t]*(?:export[ \t]+)?[A-Z][A-Z0-9_]*(?:KEY|PASSWORD|SECRET|TOKEN)[ \t]*=[ \t]*[\"']?([^\"'\s#]+)"
)


def _tracked_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [item.decode("utf-8") for item in output.split(b"\0") if item]


def _looks_like_placeholder(value: bytes) -> bool:
    normalized = value.decode("utf-8", errors="ignore").strip().lower()
    return (
        normalized in PLACEHOLDERS
        or normalized.startswith(("replace_", "your_", "${", "$"))
        or "example" in normalized
    )


def _scan_content(path: str, content: bytes) -> list[str]:
    findings: list[str] = []
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(content):
            findings.append(f"{path}: contains a high-confidence {label} pattern")
    if EMBEDDED_URL_CREDENTIALS.search(content):
        findings.append(f"{path}: contains credentials embedded in a URL")
    if PERSONAL_HOME_PATH.search(content):
        findings.append(f"{path}: contains a personal absolute home-directory path")
    for match in ASSIGNED_SECRET.finditer(content):
        if not _looks_like_placeholder(match.group(1)):
            findings.append(f"{path}: appears to assign a non-placeholder secret")
            break
    if Path(path).name.startswith(".env") or Path(path).suffix.lower() in {".sh", ".yaml", ".yml"}:
        for match in ENV_SECRET.finditer(content):
            if not _looks_like_placeholder(match.group(1)):
                findings.append(f"{path}: appears to assign a non-placeholder environment secret")
                break
    return findings


def _scan_seed_database(path: Path) -> list[str]:
    findings: list[str] = []
    if path.stat().st_size > MAX_SEED_COMPRESSED_BYTES:
        return [f"{PUBLIC_DATABASE_SEED}: compressed seed exceeds the inspection size limit"]
    with gzip.open(path, "rb") as compressed:
        payload = compressed.read(MAX_SEED_UNCOMPRESSED_BYTES + 1)
    if len(payload) > MAX_SEED_UNCOMPRESSED_BYTES:
        return [f"{PUBLIC_DATABASE_SEED}: expanded seed exceeds the inspection size limit"]

    fd, temporary_path = tempfile.mkstemp(suffix=".sqlite3")
    try:
        with os.fdopen(fd, "wb") as destination:
            destination.write(payload)
        with sqlite3.connect(temporary_path) as connection:
            objects = {
                (row[0], row[1])
                for row in connection.execute(
                    "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                )
            }
            unsupported_objects = sorted(
                f"{object_type}:{name}"
                for object_type, name in objects
                if object_type not in {"index", "table"}
            )
            if unsupported_objects:
                findings.append(
                    f"{PUBLIC_DATABASE_SEED}: contains unsupported database objects: "
                    + ", ".join(unsupported_objects)
                )
            tables = {name for object_type, name in objects if object_type == "table"}
            if "sqlite_sequence" in {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
                )
            }:
                tables.add("sqlite_sequence")
            unexpected = sorted(tables - ALLOWED_SEED_TABLES)
            if unexpected:
                findings.append(
                    f"{PUBLIC_DATABASE_SEED}: contains unexpected tables: {', '.join(unexpected)}"
                )
            for table in sorted(tables & ALLOWED_SEED_TABLES):
                columns = [
                    row[1]
                    for row in connection.execute(f'PRAGMA table_info("{table}")')
                    if str(row[2]).upper() in {"", "TEXT"}
                ]
                if not columns:
                    continue
                query = "SELECT " + ", ".join(f'"{column}"' for column in columns) + f' FROM "{table}"'
                for row in connection.execute(query):
                    content = "\n".join(str(value) for value in row if value is not None).encode()
                    for label, pattern in SECRET_PATTERNS.items():
                        if pattern.search(content):
                            findings.append(
                                f"{PUBLIC_DATABASE_SEED}: table {table} contains a {label} pattern"
                            )
                    if EMBEDDED_URL_CREDENTIALS.search(content):
                        findings.append(
                            f"{PUBLIC_DATABASE_SEED}: table {table} contains credentials in a URL"
                        )
                    if EMAIL_ADDRESS.search(content):
                        findings.append(
                            f"{PUBLIC_DATABASE_SEED}: table {table} contains an email address"
                        )
                    if PERSONAL_HOME_PATH.search(content):
                        findings.append(
                            f"{PUBLIC_DATABASE_SEED}: table {table} contains a personal home path"
                        )
                    for match in ASSIGNED_SECRET.finditer(content):
                        if not _looks_like_placeholder(match.group(1)):
                            findings.append(
                                f"{PUBLIC_DATABASE_SEED}: table {table} appears to contain a secret"
                            )
                            break
    except (gzip.BadGzipFile, OSError, sqlite3.DatabaseError) as exc:
        findings.append(f"{PUBLIC_DATABASE_SEED}: cannot be safely inspected ({type(exc).__name__})")
    finally:
        Path(temporary_path).unlink(missing_ok=True)
    return findings


def _scan_history() -> list[str]:
    findings: list[str] = []
    names = subprocess.check_output(
        ["git", "log", "--all", "--full-history", "--pretty=format:", "--name-only", "-z"],
        cwd=ROOT,
    )
    for raw_path in names.split(b"\0"):
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", errors="replace").strip()
        if path and SENSITIVE_PATH.search(path) and not path.endswith(".example"):
            findings.append(f"Git history: contains sensitive filename {path}")

    patches = subprocess.check_output(
        ["git", "log", "--all", "-p", "--no-ext-diff", "--unified=0"],
        cwd=ROOT,
    )
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(patches):
            findings.append(f"Git history: contains a high-confidence {label} pattern")
    if EMBEDDED_URL_CREDENTIALS.search(patches):
        findings.append("Git history: contains credentials embedded in a URL")
    return findings


def _history_privacy_warnings() -> list[str]:
    warnings: list[str] = []
    patches = subprocess.check_output(
        ["git", "log", "--all", "-p", "--no-ext-diff", "--unified=0"],
        cwd=ROOT,
    )
    if PERSONAL_HOME_PATH.search(patches):
        warnings.append("Git history contains personal absolute home-directory paths")

    emails = set(
        subprocess.check_output(
            ["git", "log", "--all", "--format=%ae%n%ce"],
            cwd=ROOT,
            text=True,
        ).splitlines()
    )
    personal_email_count = sum(
        bool(email) and not email.endswith("@users.noreply.github.com")
        for email in emails
    )
    if personal_email_count:
        warnings.append(
            f"Git history contains {personal_email_count} distinct non-noreply author/committer email(s)"
        )
    return warnings


def _index_content(path: str) -> bytes:
    return subprocess.check_output(["git", "show", f":{path}"], cwd=ROOT)


def main() -> int:
    findings: list[str] = []
    tracked_files = _tracked_files()

    for path in tracked_files:
        if SENSITIVE_PATH.search(path) and not path.endswith(".example"):
            findings.append(f"{path}: secret-bearing filename must not be tracked")

        content = _index_content(path)
        findings.extend(_scan_content(path, content))
        if b"\0" in content and Path(path).suffix.lower() not in ALLOWED_BINARY_SUFFIXES:
            findings.append(f"{path}: unexpected opaque binary file is tracked")

    seed_path = ROOT / PUBLIC_DATABASE_SEED
    if PUBLIC_DATABASE_SEED in tracked_files:
        findings.extend(_scan_seed_database(seed_path))

    findings.extend(_scan_history())
    findings = sorted(set(findings))
    privacy_warnings = sorted(set(_history_privacy_warnings()))

    if findings:
        print("Public repository safety check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print(f"Public repository safety check passed ({len(tracked_files)} tracked files inspected).")
    for warning in privacy_warnings:
        print(f"WARNING: {warning}; review or rewrite history before public release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
