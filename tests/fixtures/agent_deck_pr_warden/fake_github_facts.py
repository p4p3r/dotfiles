#!/usr/bin/env python3
"""Isolated current-PR facts fixture; it has no network implementation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, NoReturn


RFC3339 = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
SHA = re.compile(r"^[0-9a-f]{40}$")
REF = re.compile(r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
REQUEST_FIELDS = {"schema_version", "op", "fixture", "binding"}
BINDING_FIELDS = {
    "repository_id", "pull_request_id", "pull_request_number", "url", "head_repository_id",
    "head_ref", "worktree", "remote_name", "remote_url",
}
FIXTURE_FIELDS = {
    "schema_version", "mode", "state", "draft", "head_sha", "mergeability",
    "review_decision", "check_counts", "unresolved_review_threads", "updated_at", "observed_at",
}


class FixtureError(Exception):
    pass


def require(condition: bool) -> None:
    if not condition:
        raise FixtureError()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        require(key not in value)
        value[key] = item
    return value


def reject(_value: str) -> NoReturn:
    raise FixtureError()


def parse(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=unique,
            parse_constant=reject,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise FixtureError() from None
    require(type(value) is dict)
    return value


def exact(value: Any, fields: set[str]) -> dict[str, Any]:
    require(type(value) is dict and set(value) == fields)
    return value


def positive(value: Any) -> int:
    require(type(value) is int and 0 < value < 2**63)
    return value


def bounded(value: Any, maximum: int) -> str:
    require(type(value) is str and 0 < len(value) <= maximum and "\x00" not in value)
    return value


def private_fixture(value: Any) -> dict[str, Any]:
    raw = bounded(value, 4096)
    path = Path(raw)
    require(path.is_absolute() and path != Path("/") and ".." not in path.parts)
    for ancestor in (path, *path.parents):
        require(not ancestor.is_symlink())
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            require(
                stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
                and 0 < info.st_size <= 16_384
            )
            raw_fixture = os.read(descriptor, 16_385)
            require(len(raw_fixture) == info.st_size)
        finally:
            os.close(descriptor)
    except OSError:
        raise FixtureError() from None
    return parse(raw_fixture)


def main() -> int:
    try:
        request = exact(parse(sys.stdin.buffer.read(131_073)), REQUEST_FIELDS)
        require(type(request["schema_version"]) is int and request["schema_version"] == 1 and request["op"] == "fetch_current_pr")
        binding = exact(request["binding"], BINDING_FIELDS)
        for field in ("repository_id", "pull_request_id", "pull_request_number", "head_repository_id"):
            positive(binding[field])
        bounded(binding["url"], 2048)
        require(REF.fullmatch(bounded(binding["head_ref"], 266)) is not None)
        for field in ("worktree", "remote_name", "remote_url"):
            bounded(binding[field], 4096)
        fixture = exact(private_fixture(request["fixture"]), FIXTURE_FIELDS)
        require(type(fixture["schema_version"]) is int and fixture["schema_version"] == 1)
        require(fixture["mode"] in {"OK", "API_UNAVAILABLE", "MALFORMED", "IDENTITY_MISMATCH", "STALE_HEAD"})
        if fixture["mode"] == "MALFORMED":
            sys.stdout.write('{"schema_version":1,"code":"OK","facts":')
            return 0
        if fixture["mode"] == "API_UNAVAILABLE":
            sys.stdout.write('{"schema_version":1,"code":"API_UNAVAILABLE"}\n')
            return 0
        require(fixture["state"] in {"OPEN", "CLOSED", "MERGED"} and type(fixture["draft"]) is bool)
        require(SHA.fullmatch(bounded(fixture["head_sha"], 40)) is not None)
        require(fixture["mergeability"] in {"MERGEABLE", "CONFLICTING", "UNKNOWN"})
        require(fixture["review_decision"] in {"APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED", "NONE"})
        counts = exact(fixture["check_counts"], {"pending", "success", "failure", "total"})
        for value in counts.values():
            require(type(value) is int and 0 <= value <= 1_000_000)
        require(counts["total"] == counts["pending"] + counts["success"] + counts["failure"])
        require(type(fixture["unresolved_review_threads"]) is int and 0 <= fixture["unresolved_review_threads"] <= 1_000_000)
        require(RFC3339.fullmatch(bounded(fixture["updated_at"], 20)) is not None)
        require(RFC3339.fullmatch(bounded(fixture["observed_at"], 20)) is not None)
        facts = {
            "repository_id": binding["repository_id"],
            "pull_request_id": binding["pull_request_id"],
            "pull_request_number": binding["pull_request_number"],
            "url": binding["url"],
            "state": fixture["state"],
            "draft": fixture["draft"],
            "head_repository_id": binding["head_repository_id"],
            "head_ref": binding["head_ref"],
            "head_sha": "f" * 40 if fixture["mode"] == "STALE_HEAD" else fixture["head_sha"],
            "mergeability": fixture["mergeability"],
            "review_decision": fixture["review_decision"],
            "check_counts": counts,
            "unresolved_review_threads": fixture["unresolved_review_threads"],
            "updated_at": fixture["updated_at"],
            "observed_at": fixture["observed_at"],
            "result_code": "OK",
        }
        if fixture["mode"] == "IDENTITY_MISMATCH":
            facts["pull_request_id"] += 1
        sys.stdout.write(json.dumps(
            {"schema_version": 1, "code": "OK", "facts": facts},
            sort_keys=True, separators=(",", ":"),
        ) + "\n")
        return 0
    except FixtureError:
        sys.stderr.write("ERROR: INVALID_FIXTURE\n")
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
