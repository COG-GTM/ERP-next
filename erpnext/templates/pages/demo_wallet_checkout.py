# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Hosted checkout page of the DEMO Wallet mock gateway: /demo_wallet_checkout?payment_id=..."""

import frappe
from frappe import _
from frappe.utils import fmt_money

no_cache = 1


def get_context(context):
	payment_id = frappe.form_dict.get("payment_id")
	if not payment_id:
		frappe.throw(_("Missing payment_id"), frappe.DoesNotExistError)

	if not frappe.db.exists("Demo Wallet Transaction", payment_id):
		frappe.throw(_("Unknown Demo Wallet payment"), frappe.DoesNotExistError)

	transaction = frappe.get_doc("Demo Wallet Transaction", payment_id)
	enabled = frappe.db.get_single_value("Demo Wallet Settings", "enabled")

	context.no_cache = 1
	context.show_sidebar = False
	context.payment_id = transaction.name
	context.status = transaction.status
	context.is_open = bool(enabled) and transaction.status in ("Created", "Pending")
	context.gateway_enabled = bool(enabled)
	context.amount = transaction.amount
	context.currency = transaction.currency
	context.formatted_amount = fmt_money(transaction.amount, currency=transaction.currency)
	context.description = transaction.description
	context.payer_name = transaction.customer_name
	context.payment_request = transaction.payment_request
	context.reference_name = transaction.reference_name
	context.complete_url = "/api/method/erpnext.erpnext_integrations.demo_wallet.api.complete_payment"
	return context
