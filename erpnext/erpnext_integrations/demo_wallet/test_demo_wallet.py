# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Tests for the DEMO Wallet mock gateway. Run with
``bench --site test_site run-tests --app erpnext --module erpnext.erpnext_integrations.demo_wallet.test_demo_wallet``"""

import json
import time
from unittest.mock import patch

import frappe
from frappe.utils import flt

from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request
from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from erpnext.erpnext_integrations.demo_wallet import api, gateway
from erpnext.erpnext_integrations.doctype.demo_wallet_settings.demo_wallet_settings import GATEWAY_NAME
from erpnext.erpnext_integrations.report.demo_wallet_reconciliation.demo_wallet_reconciliation import (
	AMOUNT_MISMATCH,
	MATCHED,
	MISSING_PAYMENT_ENTRY,
	NOT_PAID,
	REFUNDED,
	execute,
)
from erpnext.setup.utils import get_exchange_rate
from erpnext.tests.utils import ERPNextTestSuite

# DEMO credentials for the test run only (demo data, not official)
CLIENT_ID = "demo-merchant-test"
CLIENT_SECRET = "demo-client-secret-test"
HMAC_SECRET = "demo-hmac-secret-test"
COMPANY = "_Test Company"
USD_GATEWAY_ACCOUNT = f"{GATEWAY_NAME} - USD - _TC"


class TestDemoWallet(ERPNextTestSuite):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Demo Wallet Settings")
		settings.update(
			{
				"enabled": 1,
				"company": COMPANY,
				"client_id": CLIENT_ID,
				"client_secret": CLIENT_SECRET,
				"hmac_secret": HMAC_SECRET,
				"token_ttl_seconds": 300,
			}
		)
		settings.save()

		if not frappe.db.exists(
			"Payment Gateway Account",
			{"payment_gateway": GATEWAY_NAME, "currency": "USD", "company": COMPANY},
		):
			frappe.get_doc(
				{
					"doctype": "Payment Gateway Account",
					"payment_gateway": GATEWAY_NAME,
					"payment_account": "_Test Bank USD - _TC",
					"currency": "USD",
					"company": COMPANY,
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep

	def setUp(self):
		self.settings = frappe.get_single("Demo Wallet Settings")

	# ---- helpers -------------------------------------------------------------------------------

	def make_sales_invoice(self, rate=100):
		return create_sales_invoice(
			customer="_Test Customer USD",
			debit_to="_Test Receivable USD - _TC",
			currency="USD",
			conversion_rate=get_exchange_rate("USD", "INR") or 50,
			rate=rate,
		)

	def make_payment_request(self, rate=100):
		si = self.make_sales_invoice(rate)
		pr = make_payment_request(
			dt="Sales Invoice",
			dn=si.name,
			recipient_id="demo-payer@example.com",
			payment_gateway_account=USD_GATEWAY_ACCOUNT,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)
		return si, pr

	def get_transaction(self, payment_request):
		name = frappe.db.get_value("Demo Wallet Transaction", {"payment_request": payment_request.name})
		self.assertTrue(name, "Demo Wallet Transaction was not created by the Payment Request")
		return frappe.get_doc("Demo Wallet Transaction", name)

	def signed(self, body: bytes) -> str:
		return gateway.sign(HMAC_SECRET, body)

	def callback_body(self, transaction, event=api.EVENT_SUCCEEDED, **overrides) -> bytes:
		body = {
			"event": event,
			"payment_id": transaction.name,
			"amount": flt(transaction.amount),
			"currency": transaction.currency,
			"reference_doctype": "Payment Request",
			"reference_docname": transaction.payment_request,
			"nonce": "n-" + transaction.name,
			"demo": True,
		}
		body.update(overrides)
		return json.dumps(body, sort_keys=True).encode("utf-8")

	def pay(self, transaction):
		body = self.callback_body(transaction)
		result = api.process_callback(body, self.signed(body))
		transaction.reload()
		return result

	# ---- token (OAuth2 client credentials) ---------------------------------------------------

	def test_token_with_valid_credentials(self):
		result = api.token(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
		self.assertEqual(result["token_type"], "Bearer")
		self.assertEqual(result["expires_in"], 300)
		self.assertTrue(result["access_token"].startswith(gateway.TOKEN_VERSION + "."))
		self.assertNotIn(CLIENT_SECRET, json.dumps(result))
		self.assertNotIn(HMAC_SECRET, json.dumps(result))

		claims = api.require_bearer_token(self.settings, result["access_token"])
		self.assertEqual(claims["client_id"], CLIENT_ID)
		self.assertTrue(claims["token_id"])

	def test_token_with_bad_credentials(self):
		self.assertRaises(frappe.AuthenticationError, api.token, client_id=CLIENT_ID, client_secret="wrong")
		self.assertRaises(
			frappe.AuthenticationError, api.token, client_id="nobody", client_secret=CLIENT_SECRET
		)
		self.assertRaises(frappe.AuthenticationError, api.token, client_id=None, client_secret=None)
		self.assertRaises(
			frappe.AuthenticationError,
			api.token,
			client_id=CLIENT_ID,
			client_secret=CLIENT_SECRET,
			grant_type="password",
		)

	def test_expired_token_is_rejected(self):
		token = gateway.issue_token(CLIENT_ID, HMAC_SECRET, ttl_seconds=60, now=1_000_000)
		self.assertIsNotNone(gateway.verify_token(token["access_token"], HMAC_SECRET, now=1_000_059))
		self.assertIsNone(gateway.verify_token(token["access_token"], HMAC_SECRET, now=1_000_060))

		with patch.object(time, "time", return_value=time.time() + 3600):
			live = api.issue_access_token(self.settings)["access_token"]
		# issued "an hour from now", expired relative to the real clock? no - issued in the future is
		# fine; make one that expired an hour ago instead
		with patch.object(time, "time", return_value=time.time() - 3600):
			stale = api.issue_access_token(self.settings)["access_token"]
		self.assertRaises(frappe.AuthenticationError, api.require_bearer_token, self.settings, stale)
		self.assertTrue(api.require_bearer_token(self.settings, live))

	def test_tampered_token_is_rejected(self):
		token = api.issue_access_token(self.settings)["access_token"]
		version, claims, sig = token.split(".")
		self.assertIsNone(gateway.verify_token(f"{version}.{claims}.{'0' * len(sig)}", HMAC_SECRET))
		self.assertIsNone(gateway.verify_token(token, "another-secret"))
		self.assertIsNone(gateway.verify_token("garbage", HMAC_SECRET))
		self.assertIsNone(gateway.verify_token(None, HMAC_SECRET))

	# ---- create_payment ----------------------------------------------------------------------

	def test_create_payment_requires_token(self):
		si, pr = self.make_payment_request()
		self.assertRaises(
			frappe.AuthenticationError,
			api.create_payment,
			amount=pr.grand_total,
			currency="USD",
			reference_doctype="Payment Request",
			reference_docname=pr.name,
		)

	def test_create_payment(self):
		si, pr = self.make_payment_request()
		token = api.token(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)["access_token"]
		result = api.create_payment(
			amount=pr.grand_total,
			currency="USD",
			reference_doctype="Payment Request",
			reference_docname=pr.name,
			payer_name="DEMO - Test Payer",
			access_token=token,
		)
		self.assertEqual(result["status"], "Created")
		self.assertEqual(result["currency"], "USD")
		self.assertEqual(result["amount"], flt(pr.grand_total))
		self.assertIn(f"{api.CHECKOUT_PATH}?payment_id={result['payment_id']}", result["checkout_url"])
		self.assertTrue(result["demo"])

		transaction = frappe.get_doc("Demo Wallet Transaction", result["payment_id"])
		self.assertEqual(transaction.reference_name, si.name)
		self.assertEqual(transaction.company, COMPANY)
		self.assertTrue(transaction.token_id)

	def test_create_payment_rejects_unsupported_currency(self):
		self.assertRaises(frappe.ValidationError, self.settings.validate_transaction_currency, "EUR")
		for currency in ("IQD", "USD"):
			self.settings.validate_transaction_currency(currency)

	# ---- Payment Request integration ---------------------------------------------------------

	def test_payment_request_generates_hosted_url(self):
		si, pr = self.make_payment_request()
		self.assertEqual(pr.payment_gateway, GATEWAY_NAME)
		transaction = self.get_transaction(pr)
		self.assertIn(f"{api.CHECKOUT_PATH}?payment_id={transaction.name}", pr.payment_url)
		self.assertEqual(transaction.status, "Created")
		self.assertEqual(flt(transaction.amount), flt(pr.grand_total))
		self.assertEqual(transaction.reference_name, si.name)

	def test_valid_callback_creates_payment_entry(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)

		result = self.pay(transaction)
		self.assertEqual(result["status"], "Paid")
		self.assertFalse(result["replayed"])

		transaction.reload()
		self.assertEqual(transaction.status, "Paid")
		self.assertTrue(transaction.signature_verified)
		self.assertTrue(transaction.payment_entry)
		self.assertTrue(transaction.callback_payload)

		pe = frappe.get_doc("Payment Entry", transaction.payment_entry)
		self.assertEqual(pe.docstatus, 1)
		self.assertEqual(pe.payment_type, "Receive")
		self.assertEqual(pe.paid_from, "_Test Receivable USD - _TC")
		self.assertEqual(pe.paid_to, "_Test Bank USD - _TC")
		self.assertEqual(flt(pe.paid_amount), flt(transaction.amount))
		self.assertEqual(
			[(r.reference_doctype, r.reference_name) for r in pe.references], [("Sales Invoice", si.name)]
		)

		self.assertEqual(frappe.db.get_value("Payment Request", pr.name, "status"), "Paid")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")), 0)

	def test_tampered_body_is_rejected(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		body = self.callback_body(transaction)
		signature = self.signed(body)
		tampered = body.replace(b'"amount": 100.0', b'"amount": 1.0')
		self.assertNotEqual(body, tampered)

		self.assertRaises(frappe.AuthenticationError, api.process_callback, tampered, signature)
		self.assertEqual(frappe.AuthenticationError.http_status_code, 401)
		transaction.reload()
		self.assertEqual(transaction.status, "Created")
		self.assertFalse(transaction.signature_verified)
		self.assertFalse(transaction.payment_entry)
		self.assertFalse(frappe.db.exists("Payment Entry Reference", {"reference_name": si.name}))

	def test_tampered_signature_is_rejected(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		body = self.callback_body(transaction)
		good = self.signed(body)

		for bad in (
			"",
			None,
			"deadbeef",
			good[:-1] + ("0" if good[-1] != "0" else "1"),
			gateway.sign("x", body),
		):
			self.assertRaises(frappe.AuthenticationError, api.process_callback, body, bad)

		transaction.reload()
		self.assertEqual(transaction.status, "Created")
		self.assertFalse(frappe.db.exists("Payment Entry Reference", {"reference_name": si.name}))

	def test_verify_signature_helper(self):
		body = b'{"a": 1}'
		self.assertTrue(gateway.verify_signature(body, gateway.sign("k", body), "k"))
		self.assertTrue(gateway.verify_signature(body, gateway.sign("k", body).upper(), "k"))
		self.assertFalse(gateway.verify_signature(body, gateway.sign("k", body), "other"))
		self.assertFalse(gateway.verify_signature(b'{"a": 2}', gateway.sign("k", body), "k"))
		self.assertFalse(gateway.verify_signature(body, "", "k"))
		self.assertFalse(gateway.verify_signature(body, gateway.sign("", body), ""))

	def test_replayed_callback_is_idempotent(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		body = self.callback_body(transaction)
		signature = self.signed(body)

		first = api.process_callback(body, signature)
		second = api.process_callback(body, signature)
		self.assertEqual(first["status"], "Paid")
		self.assertEqual(second, {"payment_id": transaction.name, "status": "Paid", "replayed": True})

		entries = frappe.get_all(
			"Payment Entry Reference", filters={"reference_name": si.name, "docstatus": 1}, pluck="parent"
		)
		self.assertEqual(len(set(entries)), 1)
		transaction.reload()
		self.assertEqual(transaction.payment_entry, entries[0])

	def test_failed_callback(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		body = self.callback_body(transaction, event=api.EVENT_FAILED)
		result = api.process_callback(body, self.signed(body))
		self.assertEqual(result["status"], "Failed")
		transaction.reload()
		self.assertEqual(transaction.status, "Failed")
		self.assertFalse(transaction.payment_entry)
		self.assertEqual(frappe.db.get_value("Payment Request", pr.name, "status"), "Failed")

	def test_second_capture_for_same_payment_request_is_refused(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		settings = frappe.get_single("Demo Wallet Settings")
		claims = api.require_bearer_token(settings, api.issue_access_token(settings)["access_token"])
		kwargs = dict(
			amount=transaction.amount,
			currency=transaction.currency,
			reference_doctype="Payment Request",
			reference_docname=pr.name,
		)
		# while the first attempt is open, create_payment hands back the same transaction
		self.assertEqual(api.create_transaction(settings, claims, **kwargs).name, transaction.name)
		self.pay(transaction)
		self.assertRaises(frappe.ValidationError, api.create_transaction, settings, claims, **kwargs)
		self.assertEqual(
			frappe.db.count("Payment Entry", {"reference_no": pr.name, "docstatus": 1})
			or frappe.db.count("Demo Wallet Transaction", {"payment_request": pr.name}),
			1,
		)

	def test_refund_without_payment_entry_is_refused(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		self.pay(transaction)
		transaction.db_set("payment_entry", None)
		transaction.reload()
		self.assertRaises(frappe.ValidationError, api.refund_transaction, transaction, None, "DEMO")
		transaction.reload()
		self.assertEqual(transaction.status, "Paid")
		self.assertFalse(transaction.refund_id)

	def test_complete_payment_from_hosted_page(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		result = api.complete_payment(payment_id=transaction.name, outcome="success")
		self.assertEqual(result["status"], "Paid")
		self.assertIn(api.SUCCESS_PATH, result["standard_redirect_to"])
		self.assertIn("/demo_wallet_checkout?payment_id=" + transaction.name, result["redirect_to"])
		self.assertIn(pr.name, result["standard_redirect_to"])
		# a second press on the hosted page is refused
		self.assertRaises(frappe.ValidationError, api.complete_payment, payment_id=transaction.name)

		si2, pr2 = self.make_payment_request()
		transaction2 = self.get_transaction(pr2)
		result = api.complete_payment(payment_id=transaction2.name, outcome="fail")
		self.assertEqual(result["status"], "Failed")
		self.assertIn(api.FAILED_PATH, result["standard_redirect_to"])
		self.assertIn("result=failed", result["redirect_to"])

	# ---- check_status / refund ---------------------------------------------------------------

	def test_check_status(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		token = api.token(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)["access_token"]
		self.assertRaises(frappe.AuthenticationError, api.check_status, payment_id=transaction.name)
		status = api.check_status(payment_id=transaction.name, access_token=token)
		self.assertEqual(status["status"], "Created")
		self.pay(transaction)
		status = api.check_status(payment_id=transaction.name, access_token=token)
		self.assertEqual(status["status"], "Paid")
		self.assertTrue(status["payment_entry"])
		self.assertRaises(
			frappe.DoesNotExistError, api.check_status, payment_id="dwp_nope", access_token=token
		)

	def test_refund(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		token = api.token(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)["access_token"]

		# cannot refund before payment
		self.assertRaises(frappe.ValidationError, api.refund, payment_id=transaction.name, access_token=token)
		self.pay(transaction)
		self.assertRaises(frappe.AuthenticationError, api.refund, payment_id=transaction.name)

		result = api.refund(
			payment_id=transaction.name, reason="DEMO - duplicate payment", access_token=token
		)
		self.assertEqual(result["status"], "Refunded")
		self.assertTrue(result["refund_id"].startswith(gateway.REFUND_ID_PREFIX))
		self.assertEqual(result["refund_amount"], flt(transaction.amount))
		self.assertTrue(result["refund_payment_entry"])

		refund_pe = frappe.get_doc("Payment Entry", result["refund_payment_entry"])
		original_pe = frappe.get_doc("Payment Entry", transaction.payment_entry)
		self.assertEqual(refund_pe.docstatus, 1)
		self.assertEqual(refund_pe.payment_type, "Pay")
		self.assertEqual(refund_pe.party, original_pe.party)
		self.assertEqual(refund_pe.paid_from, original_pe.paid_to)
		self.assertEqual(refund_pe.paid_to, original_pe.paid_from)
		self.assertEqual(refund_pe.reference_no, result["refund_id"])
		self.assertEqual(flt(refund_pe.received_amount), flt(transaction.amount))

		# refunding twice is refused
		self.assertRaises(frappe.ValidationError, api.refund, payment_id=transaction.name, access_token=token)

	def test_partial_refund_amount_validation(self):
		si, pr = self.make_payment_request()
		transaction = self.get_transaction(pr)
		self.pay(transaction)
		self.assertRaises(frappe.ValidationError, api.refund_transaction, transaction, amount=0)
		self.assertRaises(
			frappe.ValidationError, api.refund_transaction, transaction, amount=transaction.amount + 1
		)
		api.refund_transaction(transaction, amount=40, reason="DEMO - partial")
		transaction.reload()
		self.assertEqual(flt(transaction.refund_amount), 40)
		self.assertEqual(
			flt(frappe.db.get_value("Payment Entry", transaction.refund_payment_entry, "received_amount")), 40
		)

	# ---- reconciliation report ---------------------------------------------------------------

	def test_reconciliation_report(self):
		matched = self.get_transaction(self.make_payment_request()[1])
		self.pay(matched)

		missing = self.get_transaction(self.make_payment_request()[1])
		self.pay(missing)
		missing.db_set("payment_entry", None)  # simulate a lost ledger posting

		mismatch = self.get_transaction(self.make_payment_request()[1])
		self.pay(mismatch)
		mismatch.db_set("amount", flt(mismatch.amount) + 5)  # gateway says 105, ledger says 100

		refunded = self.get_transaction(self.make_payment_request()[1])
		self.pay(refunded)
		api.refund_transaction(refunded, reason="DEMO")

		unpaid = self.get_transaction(self.make_payment_request()[1])

		columns, rows = execute({"company": COMPANY})
		self.assertEqual(
			[
				c["fieldname"]
				for c in columns
				if c["fieldname"] in ("gateway_amount", "ledger_amount", "difference")
			],
			["gateway_amount", "ledger_amount", "difference"],
		)
		by_name = {row["transaction"]: row for row in rows}

		self.assertEqual(by_name[matched.name]["reconciliation_status"], MATCHED)
		self.assertEqual(by_name[matched.name]["difference"], 0)
		self.assertEqual(by_name[matched.name]["ledger_amount"], flt(matched.amount))

		self.assertEqual(by_name[missing.name]["reconciliation_status"], MISSING_PAYMENT_ENTRY)
		self.assertEqual(by_name[missing.name]["ledger_amount"], 0)
		self.assertEqual(by_name[missing.name]["difference"], flt(missing.amount))

		self.assertEqual(by_name[mismatch.name]["reconciliation_status"], AMOUNT_MISMATCH)
		self.assertEqual(by_name[mismatch.name]["difference"], 5)

		self.assertEqual(by_name[refunded.name]["reconciliation_status"], REFUNDED)
		self.assertEqual(by_name[unpaid.name]["reconciliation_status"], NOT_PAID)

		_, filtered = execute({"company": COMPANY, "status": MISSING_PAYMENT_ENTRY})
		self.assertIn(missing.name, [r["transaction"] for r in filtered])
		self.assertNotIn(matched.name, [r["transaction"] for r in filtered])

		_, none = execute({"company": COMPANY, "from_date": "2000-01-01", "to_date": "2000-01-02"})
		self.assertEqual(none, [])
		self.assertRaises(
			frappe.ValidationError, execute, {"from_date": "2026-02-01", "to_date": "2026-01-01"}
		)

	def test_gateway_registered_at_runtime(self):
		self.assertTrue(frappe.db.exists("Payment Gateway", GATEWAY_NAME))
		gateway_doc = frappe.get_doc("Payment Gateway", GATEWAY_NAME)
		self.assertEqual(gateway_doc.gateway_settings, "Demo Wallet Settings")
		self.assertEqual(gateway_doc.gateway_controller, "Demo Wallet Settings")
		self.assertTrue(
			frappe.db.exists("Payment Gateway Account", {"payment_gateway": GATEWAY_NAME, "company": COMPANY})
		)

	def test_disabled_gateway_rejects_requests(self):
		frappe.db.set_single_value("Demo Wallet Settings", "enabled", 0)
		try:
			self.assertRaises(
				frappe.ValidationError, api.token, client_id=CLIENT_ID, client_secret=CLIENT_SECRET
			)
		finally:
			frappe.db.set_single_value("Demo Wallet Settings", "enabled", 1)
