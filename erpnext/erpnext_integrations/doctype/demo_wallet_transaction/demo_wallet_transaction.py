# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.erpnext_integrations.demo_wallet import gateway


class DemoWalletTransaction(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		callback_payload: DF.Code | None
		callback_received_on: DF.Datetime | None
		company: DF.Link | None
		currency: DF.Link
		customer_name: DF.Data | None
		description: DF.SmallText | None
		hosted_page_url: DF.SmallText | None
		paid_on: DF.Datetime | None
		payer_email: DF.Data | None
		payment_entry: DF.Link | None
		payment_request: DF.Link
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		refund_amount: DF.Currency
		refund_id: DF.Data | None
		refund_payment_entry: DF.Link | None
		refund_reason: DF.SmallText | None
		refunded_on: DF.Datetime | None
		signature_verified: DF.Check
		status: DF.Literal["Created", "Pending", "Paid", "Failed", "Refunded", "Expired"]
		token_id: DF.Data | None
	# end: auto-generated types

	def autoname(self):
		from erpnext.erpnext_integrations.demo_wallet.api import get_checkout_url

		self.name = gateway.new_payment_id()
		self.hosted_page_url = get_checkout_url(self.name)


@frappe.whitelist()
def refund_from_desk(payment_id: str, amount=None, reason: str | None = None):
	"""Desk button: same as the ``refund`` API, but authorised by the logged-in user's role."""
	from erpnext.erpnext_integrations.demo_wallet.api import get_transaction, refund_transaction

	frappe.only_for(("System Manager", "Accounts Manager"))
	transaction = refund_transaction(get_transaction(payment_id), amount, reason)
	frappe.msgprint(_("DEMO refund {0} recorded").format(transaction.refund_id), alert=True)
	return transaction.as_dict()
