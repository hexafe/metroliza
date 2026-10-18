"""Shared, lazy source inspection state for parser resolution and persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
from threading import Lock

from metroliza.parsing.pdf_backend import require_pdf_backend


SOURCE_HASH_CHUNK_BYTES = 1024 * 1024
PDF_EMBEDDED_TEXT_CACHE_KEY = "pdf_embedded_text_v1"
_UNSET = object()


class SourceChangedAfterInspectionError(ValueError):
    """Raised when source content no longer matches its inspected digest."""

    def __init__(
        self,
        source_path: str,
        *,
        inspected_sha256: str | None,
        current_sha256: str | None,
    ) -> None:
        self.source_path = str(source_path)
        self.inspected_sha256 = inspected_sha256
        self.current_sha256 = current_sha256
        super().__init__(
            "Source changed after parser resolution; refusing to persist stale parse output: "
            f"{self.source_path}"
        )


class SourceInspectionError(ValueError):
    """Raised when a source container cannot be inspected reliably."""


class SourceInspectionLimitError(SourceInspectionError):
    """Raised when bounded source inspection would exceed its configured limit."""


class PdfSourceInspectionError(SourceInspectionError):
    """Raised when a PDF container or its embedded text cannot be decoded."""


def _page_embedded_text(page: object) -> str:
    get_text = getattr(page, "get_text", None)
    if not callable(get_text):
        raise PdfSourceInspectionError("PDF page does not expose embedded-text extraction")
    try:
        return str(get_text() or "")
    except TypeError:
        return str(get_text("text") or "")


def _extract_pdf_embedded_text(path: Path, max_chars: int) -> str:
    """Decode bounded embedded text from every page through the canonical backend."""

    document = None
    try:
        backend = require_pdf_backend()
        document = backend.open(str(path))
        if bool(getattr(document, "needs_pass", False)):
            raise PdfSourceInspectionError(f"PDF requires a password: {path}")

        page_texts: list[str] = []
        extracted_chars = 0
        for page in document:
            page_text = _page_embedded_text(page)
            if not page_text:
                continue
            extracted_chars += len(page_text) + (1 if page_texts else 0)
            if extracted_chars > max_chars:
                raise SourceInspectionLimitError(
                    f"Embedded PDF text exceeds the {max_chars}-character inspection limit: "
                    f"{path}"
                )
            page_texts.append(page_text)
        return "\n".join(page_texts)
    except (PdfSourceInspectionError, SourceInspectionLimitError):
        raise
    except Exception as exc:
        detail = " ".join(str(exc).split())
        suffix = f": {detail}" if detail else ""
        raise PdfSourceInspectionError(f"Failed to inspect PDF {path}{suffix}") from exc
    finally:
        close = getattr(document, "close", None)
        if callable(close):
            close()


def source_stat_signature(path: str | Path) -> tuple[int, int] | None:
    """Return the cheap ``(size, mtime_ns)`` change signal, or None when unavailable."""

    try:
        stat_result = os.stat(path)
    except (OSError, ValueError):
        return None
    return stat_result.st_size, stat_result.st_mtime_ns


@dataclass
class _SourceInspectionCache:
    lock: Lock = field(default_factory=Lock)
    sha256: object = _UNSET
    extracted_text: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceInspectionContext:
    """Immutable source facts with lazily cached content-derived inspection data."""

    source_path: str
    source_format: str | None
    file_size_bytes: int | None
    file_modified_ns: int | None
    is_file: bool
    _cache: _SourceInspectionCache = field(
        default_factory=_SourceInspectionCache,
        compare=False,
        repr=False,
    )

    @classmethod
    def from_path(
        cls,
        source_path: str | Path,
        *,
        source_format: str | None = None,
    ) -> SourceInspectionContext:
        path = Path(source_path)
        try:
            stat_result = path.stat()
            is_file = path.is_file()
        except OSError:
            stat_result = None
            is_file = False
        return cls(
            source_path=str(path),
            source_format=source_format,
            file_size_bytes=stat_result.st_size if stat_result is not None and is_file else None,
            file_modified_ns=stat_result.st_mtime_ns if stat_result is not None and is_file else None,
            is_file=is_file,
        )

    def adopt_reviewed_sha256(
        self,
        reviewed_sha256: str | None,
        reviewed_stat: tuple[int, int] | None,
    ) -> bool:
        """Carry an earlier review's digest forward instead of rehashing the file.

        The reviewed digest becomes this context's *provisional* digest only while the file's
        ``(size, mtime_ns)`` still equals ``reviewed_stat`` and no digest was computed yet.
        It is never trusted for persistence: ``verified_sha256()`` always rehashes and
        compares against it, so a same-size/same-mtime content change is still rejected.
        """

        if (
            not reviewed_sha256
            or reviewed_stat is None
            or not self.is_file
            or (self.file_size_bytes, self.file_modified_ns) != tuple(reviewed_stat)
        ):
            return False
        with self._cache.lock:
            if self._cache.sha256 is not _UNSET:
                return False
            self._cache.sha256 = reviewed_sha256
        return True

    def _compute_sha256(self) -> str | None:
        if not self.is_file:
            return None
        digest = hashlib.sha256()
        try:
            with Path(self.source_path).open("rb") as handle:
                for chunk in iter(lambda: handle.read(SOURCE_HASH_CHUNK_BYTES), b""):
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()

    @property
    def sha256(self) -> str | None:
        """Return the source digest, computing it at most once for this context."""

        with self._cache.lock:
            if self._cache.sha256 is _UNSET:
                self._cache.sha256 = self._compute_sha256()
            value = self._cache.sha256
        return value if isinstance(value, str) else None

    def require_unchanged_size(self) -> None:
        """Reject definite content drift without a read; mtime alone is inconclusive."""

        current_stat = source_stat_signature(self.source_path)
        if current_stat is None or current_stat[0] != self.file_size_bytes:
            raise SourceChangedAfterInspectionError(
                self.source_path,
                inspected_sha256=self.sha256,
                current_sha256=None,
            )

    def verified_sha256(self) -> str | None:
        """Rehash the source and reject persistence when it changed after inspection.

        Atomic import calls this after acquiring the write lock. A file whose
        ``(size, mtime_ns)`` moved while it was being hashed is rejected as changed.
        """

        inspected_sha256 = self.sha256
        stat_before = source_stat_signature(self.source_path)
        current_sha256 = self._compute_sha256()
        stat_after = source_stat_signature(self.source_path)
        if inspected_sha256 != current_sha256 or stat_before != stat_after:
            raise SourceChangedAfterInspectionError(
                self.source_path,
                inspected_sha256=inspected_sha256,
                current_sha256=current_sha256,
            )
        return current_sha256

    @property
    def cache_identity(self) -> tuple[object, ...]:
        """Return a content-sensitive identity suitable for resolver caches."""

        if not self.is_file:
            return ("missing",)
        return (
            self.file_modified_ns,
            self.file_size_bytes,
            self.sha256 or "unreadable",
        )

    def get_extracted_text(
        self,
        *,
        cache_key: str,
        max_chars: int,
        loader: Callable[[Path, int], str],
    ) -> str:
        """Load and cache one bounded text representation of the source."""

        key = str(cache_key)
        with self._cache.lock:
            cached = self._cache.extracted_text.get(key, _UNSET)
            if cached is _UNSET:
                text = loader(Path(self.source_path), max_chars)
                if len(text) > max_chars:
                    raise SourceInspectionLimitError(
                        f"{self.source_path} extracted more than {max_chars} characters"
                    )
                cached = str(text)
                self._cache.extracted_text[key] = cached
            elif len(cached) > max_chars:
                raise SourceInspectionLimitError(
                    f"{self.source_path} extracted more than {max_chars} characters"
                )
        return str(cached)

    def get_pdf_text(self, *, max_chars: int) -> str:
        """Return bounded all-page PDF embedded text through the canonical backend."""

        return self.get_extracted_text(
            cache_key=PDF_EMBEDDED_TEXT_CACHE_KEY,
            max_chars=max_chars,
            loader=_extract_pdf_embedded_text,
        )

    def get_cached_pdf_text(self, *, max_chars: int) -> str | None:
        """Return cached all-page PDF text without reopening the source container."""

        return self.get_cached_extracted_text(
            cache_key=PDF_EMBEDDED_TEXT_CACHE_KEY,
            max_chars=max_chars,
        )

    def get_cached_extracted_text(
        self,
        *,
        cache_key: str,
        max_chars: int,
    ) -> str | None:
        """Return an already-loaded text representation without invoking its loader."""

        key = str(cache_key)
        with self._cache.lock:
            cached = self._cache.extracted_text.get(key, _UNSET)
        if cached is _UNSET:
            return None
        if len(cached) > max_chars:
            raise SourceInspectionLimitError(
                f"{self.source_path} extracted more than {max_chars} characters"
            )
        return str(cached)
