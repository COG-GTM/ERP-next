# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""DEMO Wallet Reconciliation: one row per Demo Wallet Transaction joined to its Payment Request
and Payment Entry, comparing the gateway amount with the ledger amount."""

import frappe
from frappe import _
from frappe.query_builder import Criterion
from frappe.utils import add_days, flt, get_datetime, getdate

MATCHED = "Matched"
MISSING_PAYMENT_ENTRY = "Missing Payment Entry"
AMOUNT_MISMATCH = "Amount Mismatch"
REFUNDED = "Refunded"
NOT_PAID = "Not Paid"

RECONCILIATION_STATUSES = (MATCHED, MISSING_PAYMENT_ENTRY, AMOUNT_MISMATCH, REFUNDED, NOT_PAID)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	rows = [build_row(d) for d in get_transactions(filters)]
	if filters.get("status"):
		rows = [row for row in rows if row["reconciliation_status"] == filters.status]
	return get_columns(), rows


def validate_filters(filters):
	if filters.get("from_date") and filters.get("to_date"):
		if getdate(filters.from_date) > getdate(filters.to_date):
			frappe.throw(_("From Date must be before To Date"))
	if filters.get("status") and filters.status not in RECONCILIATION_STATUSES:
		frappe.throw(_("Unknown reconciliation status {0}").format(filters.status))


def get_columns():
	return [
		{
			"fieldname": "transaction",
			"label": _("Demo Wallet Transaction"),
			"fieldtype": "Link",
			"options": "Demo Wallet Transaction",
			"width": 190,
		},
		{"fieldname": "creation", "label": _("Created On"), "fieldtype": "Datetime", "width": 160},
		{
			"fieldname": "payment_request",
			"label": _("Payment Request"),
			"fieldtype": "Link",
			"options": "Payment Request",
			"width": 160,
		},
		{
			"fieldname": "reference_doctype",
			"label": _("Reference Type"),
			"fieldtype": "Link",
			"options": "DocType",
			"width": 120,
		},
		{
			"fieldname": "reference_name",
			"label": _("Reference"),
			"fieldtype": "Dynamic Link",
			"options": "reference_doctype",
			"width": 160,
		},
		{"fieldname": "customer_name", "label": _("Payer"), "fieldtype": "Data", "width": 150},
		{"fieldname": "gateway_status", "label": _("Gateway Status"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 80,
		},
		{
			"fieldname": "gateway_amount",
			"label": _("Gateway Amount"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"fieldname": "payment_entry",
			"label": _("Payment Entry"),
			"fieldtype": "Link",
			"options": "Payment Entry",
			"width": 160,
		},
		{
			"fieldname": "ledger_amount",
			"label": _("Ledger Amount"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"fieldname": "difference",
			"label": _("Difference"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"fieldname": "reconciliation_status",
			"label": _("Reconciliation Status"),
			"fieldtype": "Data",
			"width": 170,
		},
		{"fieldname": "refund_id", "label": _("Refund ID"), "fieldtype": "Data", "width": 170},
		{
			"fieldname": "refund_amount",
			"label": _("Refund Amount"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"fieldname": "signature_verified",
			"label": _("Signature Verified"),
			"fieldtype": "Check",
			"width": 90,
		},
	]


def get_transactions(filters):
	transaction = frappe.qb.DocType("Demo Wallet Transaction")
	payment_request = frappe.qb.DocType("Payment Request")
	payment_entry = frappe.qb.DocType("Payment Entry")

	conditions = []
	if filters.get("company"):
		conditions.append(transaction.company == filters.company)
	if filters.get("from_date"):
		conditions.append(transaction.creation >= get_datetime(filters.from_date))
	if filters.get("to_date"):
		conditions.append(transaction.creation < get_datetime(add_days(getdate(filters.to_date), 1)))

	query = (
		frappe.qb.from_(transaction)
		.left_join(payment_request)
		.on(payment_request.name == transaction.payment_request)
		.left_join(payment_entry)
		.on(payment_entry.name == transaction.payment_entry)
		.select(
			transaction.name.as_("transaction"),
			transaction.creation,
			transaction.payment_request,
			transaction.reference_doctype,
			transaction.reference_name,
			transaction.customer_name,
			transaction.status.as_("gateway_status"),
			transaction.currency,
			transaction.amount.as_("gateway_amount"),
			transaction.payment_entry,
			transaction.refund_id,
			transaction.refund_amount,
			transaction.signature_verified,
			payment_request.status.as_("payment_request_status"),
			payment_entry.paid_amount,
			payment_entry.docstatus.as_("payment_entry_docstatus"),
		)
		.orderby(transaction.creation, order=frappe.qb.desc)
	)
	if conditions:
		query = query.where(Criterion.all(conditions))
	return query.run(as_dict=True)


def build_row(d):
	row = dict(d)
	ledger_amount = flt(d.paid_amount) if d.payment_entry and d.payment_entry_docstatus == 1 else 0
	row["ledger_amount"] = ledger_amount
	row["difference"] = flt(d.gateway_amount) - ledger_amount
	row["reconciliation_status"] = reconciliation_status(d, ledger_amount)
	if not ledger_amount:
		row["payment_entry"] = d.payment_entry if d.payment_entry_docstatus == 1 else None
	return row


def reconciliation_status(d, ledger_amount):
	if d.gateway_status == REFUNDED:
		return REFUNDED
	if d.gateway_status != "Paid":
		return NOT_PAID
	if not ledger_amount:
		return MISSING_PAYMENT_ENTRY
	if flt(d.gateway_amount, 2) != flt(ledger_amount, 2):
		return AMOUNT_MISMATCH
	return MATCHED
