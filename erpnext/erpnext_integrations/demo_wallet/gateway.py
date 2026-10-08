# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Pure-python helpers for the DEMO Wallet mock payment gateway.

Everything here is a demo stand-in for a real wallet provider: tokens are HMAC-signed
strings (no JWT library), callbacks are signed with HMAC-SHA256 over the raw body, and
all comparisons are constant time. Nothing in this module talks to the network.

DEMO ASSUMPTIONS (not sourced from any real provider's specification):
- OAuth2 client-credentials token = ``dwt1.<base64url(client_id|exp|nonce)>.<hex hmac>``
- Callback signature header ``X-Demo-Wallet-Signature`` = hex HMAC-SHA256(secret, raw body)
- Payment ids look like ``dwp_<16 hex>``, refund ids like ``dwr_<16 hex>``
"""

import base64
import hashlib
import hmac
import secrets
import time

TOKEN_VERSION = "dwt1"
PAYMENT_ID_PREFIX = "dwp_"
REFUND_ID_PREFIX = "dwr_"
DEFAULT_TOKEN_TTL_SECONDS = 300


def sign(secret: str, message: bytes) -> str:
	"""Hex HMAC-SHA256 of ``message`` under ``secret``."""
	return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
	"""Constant-time check of a callback signature. Empty secrets or signatures never verify."""
	if not secret or not signature or payload is None:
		return False
	return hmac.compare_digest(sign(secret, payload), signature.strip().lower())


def verify_client_credentials(
	client_id: str | None, client_secret: str | None, expected_id: str | None, expected_secret: str | None
) -> bool:
	if not (client_id and client_secret and expected_id and expected_secret):
		return False
	id_ok = hmac.compare_digest(client_id.encode("utf-8"), expected_id.encode("utf-8"))
	secret_ok = hmac.compare_digest(client_secret.encode("utf-8"), expected_secret.encode("utf-8"))
	return id_ok and secret_ok


def _b64encode(raw: bytes) -> str:
	return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
	padding = "=" * (-len(text) % 4)
	return base64.urlsafe_b64decode(text + padding)


def issue_token(
	client_id: str, secret: str, ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS, now: int | None = None
) -> dict:
	"""Issue a signed, time-limited bearer token (HMAC over ``client_id|exp|nonce``)."""
	ttl_seconds = int(ttl_seconds) if int(ttl_seconds) > 0 else DEFAULT_TOKEN_TTL_SECONDS
	expires_at = int(now if now is not None else time.time()) + ttl_seconds
	nonce = secrets.token_hex(8)
	claims = f"{client_id}|{expires_at}|{nonce}".encode()
	token = f"{TOKEN_VERSION}.{_b64encode(claims)}.{sign(secret, claims)}"
	return {
		"access_token": token,
		"token_type": "Bearer",
		"expires_in": ttl_seconds,
		"expires_at": expires_at,
		"token_id": nonce,
	}


def verify_token(token: str | None, secret: str, now: int | None = None) -> dict | None:
	"""Return the token claims if the signature is valid and the token has not expired, else None."""
	if not token or not secret:
		return None
	parts = token.strip().split(".")
	if len(parts) != 3 or parts[0] != TOKEN_VERSION:
		return None
	try:
		claims = _b64decode(parts[1])
	except (ValueError, TypeError):
		return None
	if not hmac.compare_digest(sign(secret, claims), parts[2]):
		return None
	try:
		client_id, expires_at, nonce = claims.decode("utf-8").split("|")
		expires_at = int(expires_at)
	except ValueError:
		return None
	if expires_at <= int(now if now is not None else time.time()):
		return None
	return {"client_id": client_id, "expires_at": expires_at, "token_id": nonce}


def new_payment_id() -> str:
	return PAYMENT_ID_PREFIX + secrets.token_hex(8)


def new_refund_id() -> str:
	return REFUND_ID_PREFIX + secrets.token_hex(8)
