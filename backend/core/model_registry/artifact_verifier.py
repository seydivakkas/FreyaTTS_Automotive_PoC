"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.model_registry.contracts import (
    ArtifactStatus,
    ArtifactVerificationResult,
)

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_CHUNK_SIZE = 65536


class PathEscapeError(ValueError):
    """Raised when a relative artifact path attempts traversal, absolute escape, or symlink escape."""


def safe_resolve_under_root(base_dir: Path | str, relative_path: str | Path) -> Path:
    """Resolve relative_path strictly inside base_dir, rejecting traversal and symlink escapes."""
    raw = os.fspath(relative_path)
    if not isinstance(raw, str) or not raw.strip():
        raise PathEscapeError("Artifact path must be a non-empty relative path")
    if "\x00" in raw:
        raise PathEscapeError("Artifact path must not contain null bytes")
    if raw.startswith(("/", "\\")) or _WINDOWS_DRIVE_RE.match(raw):
        raise PathEscapeError(f"Absolute or drive-qualified path rejected: {raw!r}")
    if os.path.isabs(raw):
        raise PathEscapeError(f"Absolute path rejected: {raw!r}")

    win_parts = PureWindowsPath(raw).parts
    posix_parts = PurePosixPath(raw).parts
    if PureWindowsPath(raw).drive or PureWindowsPath(raw).root or PurePosixPath(raw).root:
        raise PathEscapeError(f"Rooted path rejected: {raw!r}")

    normalized_parts: list[str] = []
    for seg in raw.replace("\\", "/").split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            raise PathEscapeError(f"Parent traversal ('..') rejected: {raw!r}")
        normalized_parts.append(seg)

    if not normalized_parts or ".." in win_parts or ".." in posix_parts:
        raise PathEscapeError(f"Invalid relative artifact path: {raw!r}")

    base_resolved = Path(base_dir).resolve(strict=False)
    cursor = base_resolved
    for part in normalized_parts:
        cursor = cursor / part
        if cursor.is_symlink():
            link_target = cursor.resolve(strict=False)
            if not link_target.is_relative_to(base_resolved):
                raise PathEscapeError(f"Symlink escape rejected for {raw!r}")

    resolved = cursor.resolve(strict=False)
    if resolved == base_resolved or not resolved.is_relative_to(base_resolved):
        raise PathEscapeError(f"Resolved path escapes base_dir: {raw!r}")
    return resolved


def stream_sha256(path: Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> tuple[str, int]:
    """Compute SHA-256 hex digest and byte size using bounded streaming reads."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    total_bytes = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            total_bytes += len(chunk)
    return digest.hexdigest(), total_bytes


def verify_artifact(
    *,
    model_id: str,
    base_dir: Path | str,
    relative_path: str | Path,
    expected_sha256: str | None = None,
    require_digest: bool = True,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> ArtifactVerificationResult:
    """Verify artifact path containment and streaming SHA-256 without loading model weights."""
    try:
        resolved = safe_resolve_under_root(base_dir, relative_path)
    except PathEscapeError as exc:
        return ArtifactVerificationResult(
            model_id=model_id,
            status=ArtifactStatus.PATH_REJECTED,
            resolved_path=None,
            expected_sha256=expected_sha256,
            error=ErrorInfo(
                code="ARTIFACT_PATH_REJECTED",
                category=ErrorCategory.SECURITY,
                retryable=Retryability.NO,
                safe_message=str(exc),
                field_name="relative_path",
            ),
        )

    normalized_expected: str | None = None
    if expected_sha256 is not None and expected_sha256.strip():
        normalized_expected = expected_sha256.strip().lower()
        if _SHA256_HEX_RE.fullmatch(normalized_expected) is None:
            return ArtifactVerificationResult(
                model_id=model_id,
                status=ArtifactStatus.UNAPPROVED,
                resolved_path=resolved.as_posix(),
                expected_sha256=expected_sha256,
                error=ErrorInfo(
                    code="ARTIFACT_DIGEST_INVALID",
                    category=ErrorCategory.SECURITY,
                    retryable=Retryability.NO,
                    safe_message="Expected SHA-256 digest format is invalid",
                    field_name="expected_sha256",
                ),
            )
    elif require_digest:
        return ArtifactVerificationResult(
            model_id=model_id,
            status=ArtifactStatus.UNAPPROVED,
            resolved_path=resolved.as_posix(),
            expected_sha256=None,
            error=ErrorInfo(
                code="ARTIFACT_DIGEST_UNAPPROVED",
                category=ErrorCategory.SECURITY,
                retryable=Retryability.NO,
                safe_message="Approved SHA-256 digest is required before verification",
                field_name="expected_sha256",
            ),
        )

    if not resolved.exists() or not resolved.is_file():
        return ArtifactVerificationResult(
            model_id=model_id,
            status=ArtifactStatus.MISSING,
            resolved_path=resolved.as_posix(),
            expected_sha256=normalized_expected,
            error=ErrorInfo(
                code="ARTIFACT_MISSING",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Artifact file not found on disk",
                field_name="relative_path",
            ),
        )

    actual_sha256, size_bytes = stream_sha256(resolved, chunk_size=chunk_size)
    if normalized_expected is not None and not hmac.compare_digest(actual_sha256, normalized_expected):
        return ArtifactVerificationResult(
            model_id=model_id,
            status=ArtifactStatus.HASH_MISMATCH,
            resolved_path=resolved.as_posix(),
            actual_sha256=actual_sha256,
            expected_sha256=normalized_expected,
            size_bytes=size_bytes,
            error=ErrorInfo(
                code="ARTIFACT_HASH_MISMATCH",
                category=ErrorCategory.SECURITY,
                retryable=Retryability.NO,
                safe_message="Artifact SHA-256 digest mismatch",
                field_name="expected_sha256",
            ),
        )

    return ArtifactVerificationResult(
        model_id=model_id,
        status=ArtifactStatus.VERIFIED,
        resolved_path=resolved.as_posix(),
        actual_sha256=actual_sha256,
        expected_sha256=normalized_expected,
        size_bytes=size_bytes,
        error=None,
    )
