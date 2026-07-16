"""API key hashing.

API keys are high-entropy, machine-generated random tokens (not low-entropy
user passwords), so a fast deterministic hash is the right tool here — it
lets us look a key up by hash equality in one query. Argon2/bcrypt (slow,
salted, for brute-forcing low-entropy secrets) would make lookup-by-value
impossible without also storing an unsalted index, for no real security
benefit against a 256-bit random token.
"""

import hashlib
import secrets


def generate_api_key() -> str:
    return f"af_{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
