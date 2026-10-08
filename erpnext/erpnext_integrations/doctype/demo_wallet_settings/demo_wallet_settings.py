# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Settings/controller for the DEMO Wallet mock payment gateway (demo data, not official)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import call_hook_method, cint

from erpnext.erpnext_integrations.demo_wallet.gateway import DEFAULT_TOKEN_TTL_SECONDS

GATEWAY_NAME = "Demo Wallet"
# DEMO ASSUMPTION: the mock wallet settles in Iraqi dinar and US dollar only.
SUPPORTED_CURRENCIES = ("IQD", "USD")


class DemoWalletSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		client_id: DF.Data | None
		client_secret: DF.Password | None
		company: DF.Link | None
		enabled: DF.Check
		hmac_secret: DF.Password | None
		token_ttl_seconds: DF.Int
	# end: auto-generated types

	supported_currencies = SUPPORTED_CURRENCIES

	def validate(self):
		if cint(self.token_ttl_seconds) <= 0:
			self.token_ttl_seconds = DEFAULT_TOKEN_TTL_SECONDS
		if self.enabled and not (self.client_id and self.client_secret and self.hmac_secret):
			frappe.throw(_("Client ID, Client Secret and HMAC Secret are required to enable the Demo Wallet"))

	def on_update(self):
		register_gateway(self.company)

	def validate_transaction_currency(self, currency):
		if currency not in self.supported_currencies:
			frappe.throw(
				_(
					"Please select another payment method. Demo Wallet does not support transactions in currency '{0}'"
				).format(currency)
			)

	def get_payment_url(self, **kwargs):
		"""Called by Payment Request: obtain a bearer token (OAuth2 client credentials, in-process)
		and create the gateway payment; return the hosted checkout page URL."""
		from erpnext.erpnext_integrations.demo_wallet import api

		if not self.enabled:
			frappe.throw(_("The Demo Wallet gateway is disabled. Enable it in Demo Wallet Settings."))

		token = api.issue_access_token(self)
		claims = api.require_bearer_token(self, token["access_token"])
		transaction = api.create_transaction(self, claims, **kwargs)
		return transaction.hosted_page_url

	def get_settings(self, data=None):
		return frappe._dict({"client_id": self.client_id})


def register_gateway(company=None):
	"""Runtime registration (no hooks): Payment Gateway + Payment Gateway Account."""
	from payments.utils import create_payment_gateway

	create_payment_gateway(GATEWAY_NAME, settings="Demo Wallet Settings", controller="Demo Wallet Settings")
	call_hook_method("payment_gateway_enabled", gateway=GATEWAY_NAME)
	if company:
		from erpnext.accounts.utils import create_payment_gateway_account

		create_payment_gateway_account(GATEWAY_NAME, company=company)


@frappe.whitelist()
def get_demo_credentials():
	"""Desk helper for the demo: shows the client id and a fresh token (secrets are never returned)."""
	from erpnext.erpnext_integrations.demo_wallet import api

	frappe.only_for(("System Manager", "Accounts Manager"))
	settings = frappe.get_single("Demo Wallet Settings")
	token = api.issue_access_token(settings)
	return {
		"client_id": settings.client_id,
		"token_type": token["token_type"],
		"expires_in": token["expires_in"],
		"access_token": token["access_token"],
		"endpoints": {
			name: f"/api/method/erpnext.erpnext_integrations.demo_wallet.api.{name}"
			for name in ("token", "create_payment", "callback", "check_status", "refund")
		},
	}
