"""Approval tokens.

`POST /plans/{plan_id}/approve` (console session only) issues
`token = HMAC_SHA256(secret, plan_id | repo | expiry)`. A token is valid for 10 minutes and
works once. The API gives the token directly to the fix executor. The LLM does not see, issue
or pass on a token.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass

TTL_S = 600


def _secret() -> bytes:
    s = os.environ.get("FALLOUT_APPROVAL_SECRET")
    return s.encode() if s else _PROCESS_SECRET


# Without FALLOUT_APPROVAL_SECRET, tokens become invalid when the process stops.
_PROCESS_SECRET = secrets.token_bytes(32)


class ApprovalError(Exception):
    pass


@dataclass(frozen=True)
class Token:
    plan_id: str
    repo: str
    expiry: int
    sig: str

    def encode(self) -> str:
        return f"{self.expiry}.{self.sig}"


def _sign(plan_id: str, repo: str, expiry: int) -> str:
    msg = f"{plan_id}|{repo}|{expiry}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def mint(plan_id: str, repo: str, now: float | None = None) -> str:
    expiry = int((now or time.time()) + TTL_S)
    return Token(plan_id, repo, expiry, _sign(plan_id, repo, expiry)).encode()


class UsedTokens:
    """Makes each token single-use. The set is in memory. A restart also replaces the default secret."""

    def __init__(self) -> None:
        self._used: set[str] = set()
        self._lock = threading.Lock()

    def consume(self, sig: str) -> bool:
        with self._lock:
            if sig in self._used:
                return False
            self._used.add(sig)
            return True


used_tokens = UsedTokens()


def verify(
    token: str, plan_id: str, repo: str, now: float | None = None, used: UsedTokens = used_tokens
) -> None:
    """Raises ApprovalError if `token` is not a valid, unexpired, unused signature over (plan_id, repo)."""
    try:
        exp_s, sig = token.split(".", 1)
        expiry = int(exp_s)
    except ValueError as e:
        raise ApprovalError("malformed token") from e
    if not hmac.compare_digest(sig, _sign(plan_id, repo, expiry)):
        raise ApprovalError("bad signature (forged, or issued for a different plan or repo)")
    if (now or time.time()) > expiry:
        raise ApprovalError("token expired")
    if not used.consume(sig):
        raise ApprovalError("token already used")
