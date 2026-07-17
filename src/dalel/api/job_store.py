"""Thread-safe ephemeral storage for authenticated API jobs.

The store deliberately keeps only a SHA-256 digest of each high-entropy access
token.  Job identifiers are also random, but they are locators rather than
credentials: every read or mutation still requires the separate token.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


class JobNotFoundError(Exception):
    """The job is absent, expired, or the supplied token is invalid."""


class JobCapacityError(Exception):
    """The bounded ephemeral store cannot accept another job."""


@dataclass(frozen=True)
class JobCredentials:
    job_id: str
    access_token: str


@dataclass
class _StoredJob(Generic[T]):
    token_digest: bytes
    value: T
    created_at: float
    expires_at: float


class SecureJobStore(Generic[T]):
    """A small authenticated in-memory store with fixed creation-time TTLs.

    ``clock`` and ``token_factory`` are injectable to make expiry/capacity
    behavior deterministic in tests. Cleanup callbacks run after records have
    been detached from the store and therefore never execute while its lock is
    held.
    """

    def __init__(
        self,
        *,
        prefix: str,
        ttl_seconds: float,
        max_records: int,
        cleanup: Callable[[T], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        if not prefix or not prefix.replace("_", "").isalnum():
            raise ValueError("prefix must contain only letters, digits, and underscores")
        self._prefix = prefix
        self._ttl_seconds = ttl_seconds
        self._max_records = max_records
        self._cleanup = cleanup
        self._clock = clock
        self._token_factory = token_factory
        self._records: dict[str, _StoredJob[T]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    def _new_credentials_locked(self) -> JobCredentials:
        # 32 random bytes = 256 bits for each independently generated value.
        for _ in range(16):  # collision is fantastically unlikely; stay bounded.
            job_id = f"{self._prefix}_{self._token_factory(32)}"
            if job_id not in self._records:
                return JobCredentials(job_id=job_id, access_token=self._token_factory(32))
        raise JobCapacityError("unable to allocate a unique job id")

    def _expired_locked(self, now: float) -> list[T]:
        expired_ids = [job_id for job_id, item in self._records.items() if item.expires_at <= now]
        return [self._records.pop(job_id).value for job_id in expired_ids]

    def _run_cleanup(self, values: list[T]) -> None:
        if self._cleanup is None:
            return
        for value in values:
            try:
                self._cleanup(value)
            except Exception:
                # Cleanup is best-effort here. Callers that own filesystem
                # workspaces log/report their own failures without exposing paths.
                continue

    def create(self, factory: Callable[[str], T]) -> tuple[T, JobCredentials]:
        expired: list[T]
        with self._lock:
            now = self._clock()
            expired = self._expired_locked(now)
            if len(self._records) >= self._max_records:
                raise JobCapacityError("job store capacity reached")
            credentials = self._new_credentials_locked()
            value = factory(credentials.job_id)
            self._records[credentials.job_id] = _StoredJob(
                token_digest=self._digest(credentials.access_token),
                value=value,
                created_at=now,
                expires_at=now + self._ttl_seconds,
            )
        self._run_cleanup(expired)
        return value, credentials

    def _authorized_locked(self, job_id: str, access_token: str, now: float) -> _StoredJob[T]:
        item = self._records.get(job_id)
        if item is None:
            raise JobNotFoundError
        if item.expires_at <= now:
            raise JobNotFoundError
        supplied = self._digest(access_token)
        if not hmac.compare_digest(item.token_digest, supplied):
            raise JobNotFoundError
        return item

    def get(self, job_id: str, access_token: str) -> T:
        expired: list[T]
        try:
            with self._lock:
                now = self._clock()
                expired = self._expired_locked(now)
                value = self._authorized_locked(job_id, access_token, now).value
        finally:
            # ``expired`` may not be assigned when an injected clock fails.
            if "expired" in locals():
                self._run_cleanup(expired)
        return value

    def get_internal(self, job_id: str) -> T:
        """Worker-only lookup. Never expose this method through an API route."""
        expired: list[T]
        try:
            with self._lock:
                now = self._clock()
                expired = self._expired_locked(now)
                item = self._records.get(job_id)
                if item is None:
                    raise JobNotFoundError
                return item.value
        finally:
            if "expired" in locals():
                self._run_cleanup(expired)

    def delete(self, job_id: str, access_token: str) -> T:
        expired: list[T]
        removed: T | None = None
        try:
            with self._lock:
                now = self._clock()
                expired = self._expired_locked(now)
                item = self._authorized_locked(job_id, access_token, now)
                removed = self._records.pop(job_id).value
                return item.value
        finally:
            if "expired" in locals():
                self._run_cleanup(expired)
            if removed is not None:
                self._run_cleanup([removed])

    def discard_internal(self, job_id: str, *, cleanup: bool = True) -> T | None:
        with self._lock:
            item = self._records.pop(job_id, None)
        if item is None:
            return None
        if cleanup:
            self._run_cleanup([item.value])
        return item.value

    def sweep_expired(self) -> int:
        with self._lock:
            expired = self._expired_locked(self._clock())
        self._run_cleanup(expired)
        return len(expired)

    def clear(self) -> None:
        with self._lock:
            values = [item.value for item in self._records.values()]
            self._records.clear()
        self._run_cleanup(values)

    def count(self) -> int:
        self.sweep_expired()
        with self._lock:
            return len(self._records)

    def values_internal(self) -> list[T]:
        """Testing/maintenance snapshot; never serialize without authentication."""
        self.sweep_expired()
        with self._lock:
            return [item.value for item in self._records.values()]
