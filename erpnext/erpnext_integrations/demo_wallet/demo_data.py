# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""DEMO data for the Demo Wallet gateway walkthrough (demo data, not official).

	bench --site <site> execute erpnext.erpnext_integrations.demo_wallet.demo_data.setup

Creates (idempotently) a DEMO company in IQD, a DEMO customer and item, enables the gateway with
DEMO credentials, and seeds Demo Wallet Transactions in every reconciliation state so the
``Demo Wallet Reconciliation`` report has mixed data. Nothing here refers to a real organisation.
"""

import frappe
from frappe.utils import flt

from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request
from erpnext.erpnext_integrations.demo_wallet import api

# DEMO ASSUMPTION: all names below are fictitious placeholders (EN / AR) for a public-finance demo.
COMPANY = "DEMO - Public Finance Co"
COMPANY_ABBR = "DEMO"
CURRENCY = "IQD"
COUNTRY = "Iraq"
CUSTOMER = "DEMO - Citizen Payer / تجريبي - دافع"
CUSTOMER_GROUP = "DEMO - Citizens"
TERRITORY = "DEMO - Baghdad / بغداد"
ITEM = "DEMO - Service Fee / تجريبي - رسم خدمة"
ITEM_GROUP = "DEMO - Fees"
DEMO_CLIENT_ID = "demo-merchant"
DEMO_CLIENT_SECRET = "demo-client-secret-not-real"
DEMO_HMAC_SECRET = "demo-hmac-secret-not-real"

# (amount in IQD, reconciliation state to seed)
SEED = [
	(150000, "Matched"),
	(275000, "Matched"),
	(90000, "Missing Payment Entry"),
	(120000, "Amount Mismatch"),
	(60000, "Refunded"),
	(45000, "Not Paid"),
	(30000, "Failed"),
]


def setup(seed_transactions=True):
	company = ensure_company()
	ensure_settings(company)
	ensure_customer()
	ensure_item()
	if seed_transactions:
		for amount, state in SEED:
			seed_transaction(amount, state)
	frappe.db.commit()  # nosemgrep
	return {"company": company, "customer": CUSTOMER, "item": ITEM, "client_id": DEMO_CLIENT_ID}


def ensure_company():
	if frappe.db.exists("Company", COMPANY):
		return COMPANY
	frappe.db.set_value("Currency", CURRENCY, "enabled", 1)
	company = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": COMPANY,
			"abbr": COMPANY_ABBR,
			"default_currency": CURRENCY,
			"country": COUNTRY,
			"chart_of_accounts": "Standard",
			"company_description": "DEMO company for the Demo Wallet walkthrough (demo data, not official)",
		}
	)
	company.insert(ignore_permissions=True)
	ensure_fiscal_year()
	return company.name


def ensure_fiscal_year():
	from frappe.utils import getdate

	today = getdate()
	if frappe.db.exists("Fiscal Year", {"year_start_date": ("<=", today), "year_end_date": (">=", today)}):
		return
	frappe.get_doc(
		{
			"doctype": "Fiscal Year",
			"year": f"DEMO {today.year}",
			"year_start_date": f"{today.year}-01-01",
			"year_end_date": f"{today.year}-12-31",
		}
	).insert(ignore_permissions=True)


def ensure_settings(company):
	settings = frappe.get_single("Demo Wallet Settings")
	settings.update(
		{
			"enabled": 1,
			"company": company,
			"client_id": DEMO_CLIENT_ID,
			"client_secret": DEMO_CLIENT_SECRET,
			"hmac_secret": DEMO_HMAC_SECRET,
			"token_ttl_seconds": 300,
		}
	)
	settings.save(ignore_permissions=True)
	return settings


def _ensure_group(doctype, name, parent_field, root_filter):
	if frappe.db.exists(doctype, name):
		return name
	root = frappe.db.get_value(doctype, {"is_group": 1, parent_field: ("in", ("", None))}, "name")
	doc = frappe.get_doc({"doctype": doctype, root_filter: name, parent_field: root, "is_group": 0})
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_customer():
	if frappe.db.exists("Customer", CUSTOMER):
		return CUSTOMER
	_ensure_group("Customer Group", CUSTOMER_GROUP, "parent_customer_group", "customer_group_name")
	_ensure_group("Territory", TERRITORY, "parent_territory", "territory_name")
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": CUSTOMER,
			"customer_type": "Individual",
			"customer_group": CUSTOMER_GROUP,
			"territory": TERRITORY,
			"customer_details": "DEMO customer (demo data, not official)",
		}
	)
	customer.insert(ignore_permissions=True)
	return customer.name


def ensure_item():
	if frappe.db.exists("Item", ITEM):
		return ITEM
	_ensure_group("Item Group", ITEM_GROUP, "parent_item_group", "item_group_name")
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": ITEM,
			"item_name": ITEM,
			"item_group": ITEM_GROUP,
			"stock_uom": "Nos",
			"is_stock_item": 0,
			"is_sales_item": 1,
			"description": "DEMO service fee line (demo data, not official)",
		}
	)
	item.insert(ignore_permissions=True)
	return item.name


def make_demo_invoice(amount):
	invoice = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": COMPANY,
			"customer": CUSTOMER,
			"currency": CURRENCY,
			"remarks": "DEMO invoice for the Demo Wallet walkthrough (demo data, not official)",
			"items": [{"item_code": ITEM, "qty": 1, "rate": amount}],
		}
	)
	invoice.insert(ignore_permissions=True)
	invoice.submit()
	return invoice


def make_demo_payment_request(amount):
	invoice = make_demo_invoice(amount)
	gateway_account = frappe.db.get_value(
		"Payment Gateway Account",
		{"payment_gateway": "Demo Wallet", "company": COMPANY, "currency": CURRENCY},
	)
	if not gateway_account:
		frappe.throw(f"No Demo Wallet Payment Gateway Account for {COMPANY} in {CURRENCY}")
	payment_request = make_payment_request(
		dt="Sales Invoice",
		dn=invoice.name,
		recipient_id="demo-payer@example.com",
		payment_gateway_account=gateway_account,
		mute_email=1,
		submit_doc=1,
		return_doc=1,
	)
	transaction_name = frappe.db.get_value(
		"Demo Wallet Transaction", {"payment_request": payment_request.name}
	)
	return invoice, payment_request, frappe.get_doc("Demo Wallet Transaction", transaction_name)


def seed_transaction(amount, state):
	"""Create one DEMO transaction and drive it into the requested reconciliation state."""
	invoice, payment_request, transaction = make_demo_payment_request(amount)
	if state == "Not Paid":
		return transaction

	outcome = "fail" if state == "Failed" else "success"
	api.complete_payment(payment_id=transaction.name, outcome=outcome)
	transaction.reload()

	if state == "Missing Payment Entry":
		# simulate a callback that was recorded on the gateway side but whose ledger posting is gone
		transaction.db_set("payment_entry", None)
	elif state == "Amount Mismatch":
		# simulate the gateway reporting a different captured amount than the ledger
		transaction.db_set("amount", flt(transaction.amount) + 2500)
	elif state == "Refunded":
		api.refund_transaction(transaction, reason="DEMO - citizen requested refund / تجريبي")
	return transaction
