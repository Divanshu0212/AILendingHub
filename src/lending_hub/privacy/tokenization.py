"""PII tokenization service.

SRS §11.4 requires "PII minimization in the ML platform: tokenized identifiers in
the feature store". Phase 0 WS-0.3.3 puts the service in the platform.

Tokens are deterministic (the same identifier always yields the same token, so
joins survive tokenization) and keyed (a token cannot be reversed or brute-forced
without the key). Determinism is what makes tokenized data usable; the key is what
stops the token being a thin disguise. A plain hash would give the first without
the second — an unkeyed SHA-256 of a 12-digit customer id is trivially reversible
by enumeration, which is the failure mode this module exists to avoid.

Workstream: WS-0.3.3
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from enum import Enum


class TokenizationError(Exception):
    pass


class Domain(str, Enum):
    """Separate token spaces.

    Tokens are domain-separated so the same raw value in two contexts does not
    produce the same token. Without this, a customer id appearing as both a
    customer key and a guarantor reference would be linkable across contexts that
    the consent artifact treats as separate purposes.
    """

    CUSTOMER = "customer"
    ACCOUNT = "account"
    LOAN = "loan"
    DEVICE = "device"
    DOCUMENT = "document"
    PAN = "pan"
    PHONE = "phone"
    EMAIL = "email"


TOKEN_LENGTH = 32
_KEY_ENV = "LENDING_HUB_TOKENIZATION_KEY"


@dataclass(frozen=True)
class Token:
    domain: Domain
    value: str

    def __str__(self) -> str:
        return f"{self.domain.value}:{self.value}"


class Tokenizer:
    """Keyed, deterministic, domain-separated tokenization.

    The key never appears in a repr, a log line, or a report. There is no
    ``detokenize`` here on purpose: reversal belongs to a separately-permissioned
    vault service, and putting it on the same object as the forward path is how
    re-identification ends up one attribute access away from any pipeline that
    already holds a tokenizer.
    """

    def __init__(self, key: bytes):
        if not key or len(key) < 32:
            raise TokenizationError(
                "tokenization key must be at least 32 bytes of high-entropy material"
            )
        self._key = key

    @classmethod
    def from_env(cls) -> Tokenizer:
        """Load the key from the environment, refusing to invent one.

        No default and no auto-generated key: a generated key would silently
        produce tokens that do not match yesterday's, breaking every join while
        looking like it worked.
        """
        raw = os.environ.get(_KEY_ENV)
        if not raw:
            raise TokenizationError(
                f"{_KEY_ENV} is not set. The production key is held in the bank's "
                "KMS/HSM and is not a value this repository may carry or generate "
                "— see TBD[Security Architecture, LH-140]."
            )
        return cls(raw.encode("utf-8"))

    @classmethod
    def for_tests(cls) -> Tokenizer:
        """A fixed non-secret key for tests. Never valid outside a test process."""
        return cls(b"test-only-key-not-a-secret-000000")

    def tokenize(self, domain: Domain, raw: object) -> Token:
        if raw is None or str(raw).strip() == "":
            raise TokenizationError("refusing to tokenize an empty identifier")
        message = f"{domain.value}\x00{str(raw).strip()}".encode("utf-8")
        digest = hmac.new(self._key, message, hashlib.sha256).hexdigest()
        return Token(domain, digest[:TOKEN_LENGTH])

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return "<Tokenizer key=***>"


def tokenize_record(
    tokenizer: Tokenizer, record: dict, mapping: dict[str, Domain]
) -> dict:
    """Return a copy of ``record`` with mapped columns replaced by tokens.

    Columns not in ``mapping`` pass through untouched. Which columns belong in the
    mapping is a DPO classification (**LH-110**), not an engineering guess — this
    function applies a decision, it does not make one.
    """
    out = dict(record)
    for column, domain in mapping.items():
        if column in out and out[column] is not None:
            out[column] = tokenizer.tokenize(domain, out[column]).value
    return out
