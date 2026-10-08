# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""DEMO Wallet mock payment gateway - whitelisted endpoints.

The "gateway" runs inside the same Frappe site. No external calls, no real money.
Endpoints are reachable at ``/api/method/erpnext.erpnext_integrations.demo_wallet.api.<fn>``.

Flow (mirrors a hosted-checkout wallet):
1. ``token``          merchant exchanges client_id/client_secret for a bearer token
2. ``create_payment`` merchant creates a payment -> gets a hosted page URL
3. hosted page        payer presses Pay / Fail -> ``complete_payment`` builds the signed callback
4. ``callback``       gateway -> ERPNext webhook, HMAC-SHA256 over the raw body
                      (``X-Demo-Wallet-Signature``); success creates + submits a Payment Entry
5. ``check_status`` / ``refund``   merchant-side status query and refund (reversing Payment Entry)
"""

import json
from contextlib import contextmanager
from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_url, now_datetime, nowdate

from erpnext.erpnext_integrations.demo_wallet import gateway

SIGNATURE_HEADER = "X-Demo-Wallet-Signature"
TOKEN_HEADER = "X-Demo-Wallet-Token"
EVENT_SUCCEEDED = "payment.succeeded"
EVENT_FAILED = "payment.failed"
CHECKOUT_PATH = "/demo_wallet_checkout"
SUCCESS_PATH = "/payment-success"
FAILED_PATH = "/payment-failed"
SETTINGS_DOCTYPE = "Demo Wallet Settings"
TRANSACTION_DOCTYPE = "Demo Wallet Transaction"
FINAL_STATUSES = ("Paid", "Refunded")


def get_settings():
	return frappe.get_single(SETTINGS_DOCTYPE)


def get_signing_key(settings=None) -> str:
	settings = settings or get_settings()
	key = settings.get_password("hmac_secret", raise_exception=False)
	if not key:
		# verifying against an empty key would accept anything anyone signs
		frappe.throw(_("Set an HMAC Secret in Demo Wallet Settings"), frappe.ValidationError)
	return key


def _ensure_enabled(settings):
	if not cint(settings.enabled):
		frappe.throw(_("The Demo Wallet gateway is disabled"), frappe.ValidationError)


def _unauthorized(error: str, description: str):
	frappe.local.response["error"] = error
	frappe.throw(_(description), frappe.AuthenticationError, title=_("Unauthorized"))


@contextmanager
def _as_administrator():
	"""Gateway requests are authenticated by HMAC/bearer token, not by a Desk session."""
	user = frappe.session.user
	frappe.set_user("Administrator")  # nosemgrep: caller already verified HMAC signature / bearer token
	try:
		yield
	finally:
		frappe.set_user(user)  # nosemgrep


def issue_access_token(settings) -> dict:
	return gateway.issue_token(
		settings.client_id, get_signing_key(settings), cint(settings.token_ttl_seconds)
	)


def require_bearer_token(settings, access_token: str | None = None) -> dict:
	"""Accept the token as the RFC 6750 ``access_token`` form/query parameter or in the
	``X-Demo-Wallet-Token`` header. (``Authorization: Bearer`` is consumed by Frappe's own OAuth
	middleware before the endpoint runs, so the mock gateway cannot use it.)"""
	token = access_token
	if not token and getattr(frappe.local, "request", None):
		token = (frappe.get_request_header(TOKEN_HEADER, "") or "").strip()
	if not token:
		_unauthorized("invalid_request", "Missing bearer token")

	claims = gateway.verify_token(token, get_signing_key(settings))
	if not claims or claims.get("client_id") != settings.client_id:
		_unauthorized("invalid_token", "The bearer token is invalid or has expired")
	return claims


def get_transaction(payment_id: str):
	if not payment_id or not frappe.db.exists(TRANSACTION_DOCTYPE, payment_id):
		frappe.throw(_("Unknown Demo Wallet payment {0}").format(payment_id), frappe.DoesNotExistError)
	return frappe.get_doc(TRANSACTION_DOCTYPE, payment_id)


def transaction_payload(transaction) -> dict:
	"""Public view of a transaction. Never includes secrets or tokens."""
	return {
		"payment_id": transaction.name,
		"status": transaction.status,
		"amount": flt(transaction.amount),
		"currency": transaction.currency,
		"reference_doctype": transaction.reference_doctype,
		"reference_name": transaction.reference_name,
		"payment_request": transaction.payment_request,
		"payment_entry": transaction.payment_entry,
		"checkout_url": transaction.hosted_page_url,
		"paid_on": transaction.paid_on,
		"refund_id": transaction.refund_id,
		"refund_amount": flt(transaction.refund_amount),
		"refund_payment_entry": transaction.refund_payment_entry,
		"demo": True,
	}


@frappe.whitelist(
	allow_guest=True, methods=["POST"]
)  # nosemgrep: DEMO gateway endpoint, HMAC/token checked inside
def token(
	client_id: str | None = None, client_secret: str | None = None, grant_type: str = "client_credentials"
):
	"""OAuth2 client-credentials grant (DEMO). Returns a signed, time-limited bearer token."""
	settings = get_settings()
	_ensure_enabled(settings)
	if grant_type != "client_credentials":
		_unauthorized("unsupported_grant_type", "Only the client_credentials grant is supported")
	if not gateway.verify_client_credentials(
		client_id,
		client_secret,
		settings.client_id,
		settings.get_password("client_secret", raise_exception=False),
	):
		_unauthorized("invalid_client", "Invalid client credentials")
	return issue_access_token(settings)


@frappe.whitelist(
	allow_guest=True, methods=["POST"]
)  # nosemgrep: DEMO gateway endpoint, HMAC/token checked inside
def create_payment(
	amount: float | str | None = None,
	currency: str | None = None,
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
	description: str | None = None,
	payer_name: str | None = None,
	payer_email: str | None = None,
	order_id: str | None = None,
	access_token: str | None = None,
	**kwargs,
):
	"""Create a DEMO payment (requires a valid bearer token) and return the hosted page URL."""
	settings = get_settings()
	_ensure_enabled(settings)
	claims = require_bearer_token(settings, access_token)
	transaction = create_transaction(
		settings,
		claims,
		amount=amount,
		currency=currency,
		reference_doctype=reference_doctype,
		reference_docname=reference_docname,
		description=description,
		payer_name=payer_name,
		payer_email=payer_email,
		order_id=order_id,
	)
	return transaction_payload(transaction)


def create_transaction(settings, claims: dict, **kwargs):
	"""Shared by the API endpoint and ``DemoWalletSettings.get_payment_url``."""
	currency = kwargs.get("currency")
	settings.validate_transaction_currency(currency)

	amount = flt(kwargs.get("amount"))
	if amount <= 0:
		frappe.throw(_("Amount must be greater than zero"), frappe.ValidationError)

	if kwargs.get("reference_doctype") != "Payment Request":
		frappe.throw(_("Demo Wallet only accepts payments against a Payment Request"), frappe.ValidationError)

	payment_request = frappe.db.get_value(
		"Payment Request",
		kwargs.get("reference_docname"),
		["name", "company", "reference_doctype", "reference_name", "grand_total", "currency", "docstatus"],
		as_dict=True,
	)
	if not payment_request or payment_request.docstatus == 2:
		frappe.throw(
			_("Payment Request {0} not found").format(kwargs.get("reference_docname")),
			frappe.DoesNotExistError,
		)
	if payment_request.currency != currency or flt(payment_request.grand_total) != amount:
		frappe.throw(_("Amount or currency does not match Payment Request {0}").format(payment_request.name))

	# one payable transaction per Payment Request: reuse an open one, refuse a second capture of a paid one
	existing = frappe.db.get_value(
		TRANSACTION_DOCTYPE,
		{
			"payment_request": payment_request.name,
			"status": ("in", ("Created", "Pending", "Paid", "Refunded")),
		},
		["name", "status"],
		as_dict=True,
	)
	if existing and existing.status in ("Paid", "Refunded"):
		frappe.throw(
			_("Payment Request {0} was already paid by Demo Wallet payment {1}").format(
				payment_request.name, existing.name
			),
			frappe.ValidationError,
		)
	if existing:
		return frappe.get_doc(TRANSACTION_DOCTYPE, existing.name)

	transaction = frappe.get_doc(
		{
			"doctype": TRANSACTION_DOCTYPE,
			"payment_request": payment_request.name,
			"reference_doctype": payment_request.reference_doctype,
			"reference_name": payment_request.reference_name,
			"company": payment_request.company,
			"customer_name": kwargs.get("payer_name"),
			"payer_email": kwargs.get("payer_email"),
			"amount": amount,
			"currency": currency,
			"status": "Created",
			"token_id": claims.get("token_id"),
			"description": kwargs.get("description") or kwargs.get("order_id"),
		}
	)
	transaction.insert(ignore_permissions=True)
	return transaction


def build_callback_body(transaction, outcome: str) -> bytes:
	"""What the (mock) wallet would POST to ERPNext. Canonical JSON so the signature is reproducible."""
	body = {
		"event": EVENT_SUCCEEDED if outcome == "success" else EVENT_FAILED,
		"payment_id": transaction.name,
		"amount": flt(transaction.amount),
		"currency": transaction.currency,
		"reference_doctype": "Payment Request",
		"reference_docname": transaction.payment_request,
		"nonce": frappe.generate_hash(length=16),
		"timestamp": str(now_datetime()),
		"demo": True,
	}
	return json.dumps(body, sort_keys=True).encode("utf-8")


@frappe.whitelist(
	allow_guest=True, methods=["POST"]
)  # nosemgrep: DEMO gateway endpoint, HMAC/token checked inside
def complete_payment(payment_id: str | None = None, outcome: str = "success"):
	"""Hosted page button handler: simulates the wallet confirming or failing the payment and
	delivers the signed callback to ``process_callback`` exactly as a webhook would."""
	settings = get_settings()
	_ensure_enabled(settings)
	outcome = "failed" if outcome in ("fail", "failed", "failure") else outcome
	if outcome not in ("success", "failed"):
		frappe.throw(_("Outcome must be 'success' or 'fail'"), frappe.ValidationError)

	transaction = get_transaction(payment_id)
	if transaction.status not in ("Created", "Pending"):
		frappe.throw(
			_("This demo payment is already {0} and cannot be completed again").format(_(transaction.status))
		)

	raw_body = build_callback_body(transaction, outcome)
	result = process_callback(raw_body, gateway.sign(get_signing_key(settings), raw_body), settings)

	# land back on the DEMO-labelled hosted page (shows the final status) rather than the generic
	# ERPNext /payment-success page; the standard page stays reachable via ``standard_redirect_to``
	query = urlencode({"doctype": "Payment Request", "docname": transaction.payment_request})
	result["standard_redirect_to"] = (
		f"{SUCCESS_PATH}?{query}" if result["status"] == "Paid" else f"{FAILED_PATH}?{query}"
	)
	result["redirect_to"] = get_checkout_url(transaction.name) + "&result=" + result["status"].lower()
	return result


@frappe.whitelist(
	allow_guest=True, methods=["POST"]
)  # nosemgrep: DEMO gateway endpoint, HMAC/token checked inside
def callback():
	"""Gateway -> ERPNext webhook. Body: JSON; header ``X-Demo-Wallet-Signature``: hex HMAC-SHA256."""
	raw_body = frappe.request.data if getattr(frappe.local, "request", None) else b""
	signature = frappe.get_request_header(SIGNATURE_HEADER, "") if raw_body else ""
	return process_callback(raw_body, signature)


def process_callback(raw_body: bytes, signature: str, settings=None) -> dict:
	settings = settings or get_settings()
	if isinstance(raw_body, str):
		raw_body = raw_body.encode("utf-8")

	if not gateway.verify_signature(raw_body, signature, get_signing_key(settings)):
		# HTTP 401, nothing has been written
		_unauthorized("invalid_signature", "Demo Wallet signature verification failed")

	payload = frappe.parse_json(raw_body.decode("utf-8")) or {}
	event = payload.get("event")
	transaction = get_transaction(payload.get("payment_id"))

	if transaction.status in FINAL_STATUSES:
		# replay of an already processed callback: idempotent 200, no second Payment Entry
		return {"payment_id": transaction.name, "status": transaction.status, "replayed": True}

	if payload.get("currency") != transaction.currency or flt(payload.get("amount")) != flt(
		transaction.amount
	):
		frappe.throw(_("Callback amount or currency does not match payment {0}").format(transaction.name))

	received_on = now_datetime()
	if event == EVENT_SUCCEEDED:
		with _as_administrator():
			payment_entry = _mark_payment_request_paid(transaction)
		transaction.db_set(
			{
				"status": "Paid",
				"signature_verified": 1,
				"callback_received_on": received_on,
				"paid_on": received_on,
				"callback_payload": raw_body.decode("utf-8"),
				"payment_entry": payment_entry,
			}
		)
	elif event == EVENT_FAILED:
		with _as_administrator():
			_mark_payment_request_failed(transaction)
		transaction.db_set(
			{
				"status": "Failed",
				"signature_verified": 1,
				"callback_received_on": received_on,
				"callback_payload": raw_body.decode("utf-8"),
			}
		)
	else:
		frappe.throw(_("Unsupported Demo Wallet event {0}").format(event), frappe.ValidationError)

	return {"payment_id": transaction.name, "status": transaction.status, "replayed": False}


def _mark_payment_request_paid(transaction) -> str | None:
	"""Drive ERPNext's own Payment Request -> Payment Entry path (``set_as_paid``)."""
	payment_request = frappe.get_doc("Payment Request", transaction.payment_request)
	if payment_request.status == "Paid":
		if not transaction.payment_entry:
			frappe.throw(
				_("Payment Request {0} is already paid; refusing a second capture").format(
					payment_request.name
				),
				frappe.ValidationError,
			)
		return transaction.payment_entry
	if hasattr(payment_request, "on_payment_authorized"):
		payment_request.run_method("on_payment_authorized", "Completed")
	payment_entry = payment_request.set_as_paid()
	return payment_entry.name if payment_entry else None


@frappe.whitelist(allow_guest=True)  # nosemgrep: DEMO gateway endpoint, bearer token checked inside
def _mark_payment_request_failed(transaction: Document):
	"""ERPNext's ``PaymentRequest.set_failed`` is a no-op, so set the documented ``Failed`` status
	explicitly (only while no other attempt against the same request has succeeded)."""
	payment_request = frappe.get_doc("Payment Request", transaction.payment_request)
	payment_request.run_method("set_failed")
	if payment_request.docstatus == 1 and payment_request.status not in (
		"Paid",
		"Partially Paid",
		"Cancelled",
	):
		payment_request.db_set("status", "Failed")


def check_status(payment_id: str | None = None, access_token: str | None = None):
	settings = get_settings()
	_ensure_enabled(settings)
	require_bearer_token(settings, access_token)
	return transaction_payload(get_transaction(payment_id))


@frappe.whitelist(
	allow_guest=True, methods=["POST"]
)  # nosemgrep: DEMO gateway endpoint, HMAC/token checked inside
def refund(
	payment_id: str | None = None,
	amount: float | str | None = None,
	reason: str | None = None,
	access_token: str | None = None,
):
	"""Refund a paid DEMO payment (requires a valid bearer token)."""
	settings = get_settings()
	_ensure_enabled(settings)
	require_bearer_token(settings, access_token)
	return transaction_payload(refund_transaction(get_transaction(payment_id), amount, reason))


def refund_transaction(transaction, amount=None, reason: str | None = None):
	if transaction.status != "Paid":
		frappe.throw(
			_("Only paid Demo Wallet payments can be refunded (status is {0})").format(transaction.status)
		)

	refund_amount = flt(amount) if amount not in (None, "") else flt(transaction.amount)
	if refund_amount <= 0 or refund_amount > flt(transaction.amount):
		frappe.throw(
			_("Refund amount must be greater than 0 and at most {0} {1}").format(
				transaction.amount, transaction.currency
			)
		)

	refund_id = gateway.new_refund_id()
	with _as_administrator():
		refund_entry = create_refund_payment_entry(transaction, refund_amount, refund_id, reason)

	transaction.db_set(
		{
			"status": "Refunded",
			"refund_id": refund_id,
			"refund_amount": refund_amount,
			"refund_reason": reason,
			"refunded_on": now_datetime(),
			"refund_payment_entry": refund_entry.name if refund_entry else None,
		}
	)
	return transaction


def create_refund_payment_entry(transaction, refund_amount: float, refund_id: str, reason: str | None = None):
	"""Reversing document: a Payment Entry of type ``Pay`` to the customer, from the gateway bank
	account back to the receivable account (ERPNext's standard customer-refund posting)."""
	if (
		not transaction.payment_entry
		or frappe.db.get_value("Payment Entry", transaction.payment_entry, "docstatus") != 1
	):
		frappe.throw(
			_(
				"Cannot refund Demo Wallet payment {0}: its original Payment Entry is missing or not submitted"
			).format(transaction.name),
			frappe.ValidationError,
		)

	original = frappe.get_doc("Payment Entry", transaction.payment_entry)
	# transaction.amount is in the Payment Request / gateway bank-account currency (= paid_to on the
	# receipt); the receivable side (paid_from) may be in another currency, so scale each side separately
	gateway_side = (
		original.received_amount
		if original.paid_to_account_currency == transaction.currency
		else original.paid_amount
	)
	fraction = refund_amount / flt(gateway_side) if flt(gateway_side) else 1
	precision = original.precision("paid_amount")

	refund_entry = frappe.new_doc("Payment Entry")
	refund_entry.update(
		{
			"payment_type": "Pay",
			"company": original.company,
			"posting_date": nowdate(),
			"mode_of_payment": original.mode_of_payment,
			"party_type": original.party_type,
			"party": original.party,
			"paid_from": original.paid_to,
			"paid_from_account_currency": original.paid_to_account_currency,
			"paid_to": original.paid_from,
			"paid_to_account_currency": original.paid_from_account_currency,
			"paid_amount": flt(original.received_amount * fraction, precision),
			"received_amount": flt(original.paid_amount * fraction, precision),
			"source_exchange_rate": original.target_exchange_rate,
			"target_exchange_rate": original.source_exchange_rate,
			"reference_no": refund_id,
			"reference_date": nowdate(),
			"cost_center": original.cost_center,
			"remarks": _("DEMO refund {0} of Demo Wallet payment {1} ({2})").format(
				refund_id, transaction.name, reason or _("no reason given")
			),
		}
	)
	refund_entry.insert(ignore_permissions=True)
	refund_entry.submit()
	return refund_entry


def get_checkout_url(payment_id: str) -> str:
	return get_url(f"{CHECKOUT_PATH}?{urlencode({'payment_id': payment_id})}")
