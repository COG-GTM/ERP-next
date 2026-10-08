# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""
Iraq Public Finance Pack (DEMO) - setup helpers.

Everything created here is demo data, not official. Ministry names are prefixed with
``DEMO -`` / ``تجريبي -``. Governorate names use the canonical EN/AR spellings shared by the
three demo sessions so that records link across the pack; each master carries a
"demo data, not official" description.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	make_dimension_in_accounting_doctypes,
)

DEMO_DESCRIPTION = "Demo data, not official. / بيانات تجريبية، غير رسمية."

# Accounting Dimension name -> (document type, fieldname injected into accounting doctypes)
PUBLIC_FINANCE_DIMENSIONS = {
	"Ministry": ("Ministry", "ministry"),
	"Governorate": ("Governorate", "governorate"),
}

# (english name, arabic name, demo annual budget in company currency)
# Amounts are arbitrary demo figures, not official allocations.
DEMO_MINISTRIES = [
	("DEMO - Ministry of Finance", "تجريبي - وزارة المالية", 5_000_000),
	("DEMO - Ministry of Health", "تجريبي - وزارة الصحة", 4_000_000),
	("DEMO - Ministry of Education", "تجريبي - وزارة التربية", 3_500_000),
	("DEMO - Ministry of Electricity", "تجريبي - وزارة الكهرباء", 3_000_000),
	("DEMO - Ministry of Oil", "تجريبي - وزارة النفط", 6_000_000),
	("DEMO - Ministry of Interior", "تجريبي - وزارة الداخلية", 2_500_000),
	("DEMO - Ministry of Planning", "تجريبي - وزارة التخطيط", 1_500_000),
	("DEMO - Ministry of Higher Education", "تجريبي - وزارة التعليم العالي", 2_000_000),
]

# Canonical 18 governorates (EN / AR) shared across the Iraq Public Finance Pack sessions.
GOVERNORATES = [
	("Baghdad", "بغداد"),
	("Basra", "البصرة"),
	("Nineveh", "نينوى"),
	("Erbil", "أربيل"),
	("Sulaymaniyah", "السليمانية"),
	("Dohuk", "دهوك"),
	("Kirkuk", "كركوك"),
	("Anbar", "الأنبار"),
	("Diyala", "ديالى"),
	("Salah al-Din", "صلاح الدين"),
	("Babil", "بابل"),
	("Karbala", "كربلاء"),
	("Najaf", "النجف"),
	("Wasit", "واسط"),
	("Maysan", "ميسان"),
	("Dhi Qar", "ذي قار"),
	("Muthanna", "المثنى"),
	("Qadisiyyah", "القادسية"),
]

DEMO_EXPENSE_ACCOUNT = "DEMO - Public Expenditure"
DEMO_SUPPLIER = "DEMO - Supplier / تجريبي - مورد"
DEMO_CUSTOMER = "DEMO - Taxpayer / تجريبي - مكلف"
DEMO_ITEM = "DEMO - Public Service / تجريبي - خدمة عامة"

# ministry -> share of its budget committed via a submitted Purchase Order
DEMO_COMMITMENTS = {
	"DEMO - Ministry of Health": 0.40,
	"DEMO - Ministry of Education": 0.30,
	"DEMO - Ministry of Electricity": 0.50,
	"DEMO - Ministry of Planning": 0.20,
}
# ministry -> share of its budget booked as actual expense via a standalone Purchase Invoice
DEMO_ACTUALS = {
	"DEMO - Ministry of Finance": 0.35,
	"DEMO - Ministry of Oil": 0.60,
	"DEMO - Ministry of Interior": 0.45,
	"DEMO - Ministry of Higher Education": 0.25,
}
# ministries whose Purchase Order is fully billed (commitment moves to actual)
DEMO_BILLED_COMMITMENTS = ["DEMO - Ministry of Health"]

# governorate -> demo collections received via Payment Entry
DEMO_COLLECTIONS = {
	"Baghdad": 900_000,
	"Basra": 750_000,
	"Nineveh": 320_000,
	"Erbil": 410_000,
	"Sulaymaniyah": 280_000,
	"Kirkuk": 190_000,
	"Najaf": 150_000,
	"Karbala": 140_000,
	"Anbar": 110_000,
	"Dhi Qar": 95_000,
}


def setup_public_finance_dimensions(company=None):
	"""Create the Ministry / Governorate Accounting Dimensions and the DEMO masters. Idempotent."""
	if company and not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist").format(company))

	created = {"dimensions": [], "ministries": [], "governorates": []}

	for dimension_name, (document_type, fieldname) in PUBLIC_FINANCE_DIMENSIONS.items():
		dimension = ensure_accounting_dimension(dimension_name, document_type, fieldname)
		if dimension:
			created["dimensions"].append(dimension.name)

	for name, arabic, _amount in DEMO_MINISTRIES:
		if ensure_master("Ministry", "ministry_name", name, arabic):
			created["ministries"].append(name)

	for name, arabic in GOVERNORATES:
		if ensure_master("Governorate", "governorate_name", name, arabic):
			created["governorates"].append(name)

	frappe.clear_cache()
	return created


def ensure_accounting_dimension(dimension_name, document_type, fieldname):
	existing = frappe.db.get_value("Accounting Dimension", {"document_type": document_type}, "name")
	if existing:
		doc = frappe.get_doc("Accounting Dimension", existing)
		if not frappe.db.exists("Custom Field", {"dt": "GL Entry", "fieldname": doc.fieldname}):
			make_dimension_in_accounting_doctypes(doc)
		return None

	doc = frappe.get_doc(
		{
			"doctype": "Accounting Dimension",
			"document_type": document_type,
			"label": dimension_name,
			"fieldname": fieldname,
			"disabled": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	if not frappe.db.exists("Custom Field", {"dt": "GL Entry", "fieldname": doc.fieldname}):
		make_dimension_in_accounting_doctypes(doc)
	return doc


def ensure_master(doctype, name_field, name, arabic_name):
	if frappe.db.exists(doctype, name):
		return None
	frappe.get_doc(
		{
			"doctype": doctype,
			name_field: name,
			f"{name_field}_in_arabic": arabic_name,
			"description": DEMO_DESCRIPTION,
		}
	).insert(ignore_permissions=True)
	return name


def get_dimension_fieldname(document_type):
	return frappe.db.get_value("Accounting Dimension", {"document_type": document_type}, "fieldname")


def ensure_default_company(company):
	"""The workspace charts resolve their Company filter from the global default; set it once if unset."""
	global_defaults = frappe.get_doc("Global Defaults")
	if not global_defaults.default_company:
		global_defaults.default_company = company
		global_defaults.save(ignore_permissions=True)


def load_demo_budget_data(company, fiscal_year):
	"""
	Create DEMO budgets (Stop actions) per ministry, submitted Purchase Orders (commitments),
	Purchase Invoices (actuals) and received Payment Entries tagged with governorates. Idempotent.
	"""
	setup_public_finance_dimensions(company)
	ensure_default_company(company)
	fy = frappe.get_doc("Fiscal Year", fiscal_year)
	posting_date = get_demo_posting_date(fy)

	expense_account = ensure_demo_expense_account(company)
	cost_center = get_demo_cost_center(company)
	supplier = ensure_demo_supplier()
	customer = ensure_demo_customer()
	item = ensure_demo_item()

	summary = frappe._dict(budgets=[], purchase_orders=[], purchase_invoices=[], payment_entries=[])

	for ministry, _arabic, amount in DEMO_MINISTRIES:
		budget = ensure_demo_budget(company, fiscal_year, ministry, expense_account, amount)
		if budget:
			summary.budgets.append(budget)

	ministry_field = get_dimension_fieldname("Ministry")
	governorate_field = get_dimension_fieldname("Governorate")

	for ministry, _arabic, amount in DEMO_MINISTRIES:
		share = DEMO_COMMITMENTS.get(ministry)
		if not share or demo_vouchers_exist(
			"Purchase Order", company, supplier, fy, {ministry_field: ministry}
		):
			continue
		po = make_demo_purchase_order(
			company, supplier, item, expense_account, cost_center, ministry, posting_date, amount * share
		)
		summary.purchase_orders.append(po.name)
		if ministry in DEMO_BILLED_COMMITMENTS:
			pi = bill_demo_purchase_order(po, posting_date)
			summary.purchase_invoices.append(pi.name)

	for ministry, _arabic, amount in DEMO_MINISTRIES:
		share = DEMO_ACTUALS.get(ministry)
		if not share or demo_vouchers_exist(
			"Purchase Invoice", company, supplier, fy, {ministry_field: ministry}, exclude_po_linked=True
		):
			continue
		pi = make_demo_purchase_invoice(
			company, supplier, item, expense_account, cost_center, ministry, posting_date, amount * share
		)
		summary.purchase_invoices.append(pi.name)

	for governorate, amount in DEMO_COLLECTIONS.items():
		if demo_payment_entries_exist(company, customer, fy, {governorate_field: governorate}):
			continue
		pe = make_demo_collection(company, customer, governorate, posting_date, amount)
		summary.payment_entries.append(pe.name)

	return summary


def get_demo_posting_date(fy):
	today = getdate(nowdate())
	if getdate(fy.year_start_date) <= today <= getdate(fy.year_end_date):
		return nowdate()
	return str(getdate(fy.year_start_date))


def ensure_demo_expense_account(company):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	account_name = f"{DEMO_EXPENSE_ACCOUNT} - {abbr}"
	if frappe.db.exists("Account", account_name):
		return account_name

	parent = frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Expense", "is_group": 1, "account_name": "Indirect Expenses"},
		"name",
	) or frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Expense", "is_group": 1},
		"name",
		order_by="lft asc",
	)
	if not parent:
		frappe.throw(_("No Expense group account found for company {0}").format(company))

	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": DEMO_EXPENSE_ACCOUNT,
			"parent_account": parent,
			"company": company,
			"root_type": "Expense",
			"account_type": "Expense Account",
		}
	)
	account.insert(ignore_permissions=True)
	return account.name


def get_demo_cost_center(company):
	cost_center = frappe.get_cached_value("Company", company, "cost_center")
	if not cost_center:
		cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
	return cost_center


def ensure_demo_supplier():
	if frappe.db.exists("Supplier", DEMO_SUPPLIER):
		return DEMO_SUPPLIER
	frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": DEMO_SUPPLIER,
			"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
			or frappe.db.get_value("Supplier Group", {}, "name"),
			"supplier_type": "Company",
			"supplier_details": DEMO_DESCRIPTION,
		}
	).insert(ignore_permissions=True)
	return DEMO_SUPPLIER


def ensure_demo_customer():
	if frappe.db.exists("Customer", DEMO_CUSTOMER):
		return DEMO_CUSTOMER
	frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": DEMO_CUSTOMER,
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
			or frappe.db.get_value("Customer Group", {}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name")
			or frappe.db.get_value("Territory", {}, "name"),
			"customer_details": DEMO_DESCRIPTION,
		}
	).insert(ignore_permissions=True)
	return DEMO_CUSTOMER


def ensure_demo_item():
	if frappe.db.exists("Item", DEMO_ITEM):
		return DEMO_ITEM
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": DEMO_ITEM,
			"item_name": DEMO_ITEM,
			"description": DEMO_DESCRIPTION,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name")
			or frappe.db.get_value("Item Group", {}, "name"),
			"stock_uom": frappe.db.get_value("UOM", "Nos", "name") or frappe.db.get_value("UOM", {}, "name"),
			"is_stock_item": 0,
			"include_item_in_manufacturing": 0,
		}
	).insert(ignore_permissions=True)
	return DEMO_ITEM


def ensure_demo_budget(company, fiscal_year, ministry, account, amount, governorate=None):
	fieldname = get_dimension_fieldname("Ministry")
	filters = {
		"company": company,
		"budget_against": "Ministry",
		fieldname: ministry,
		"account": account,
		"docstatus": 1,
		"from_fiscal_year": ("<=", fiscal_year),
		"to_fiscal_year": (">=", fiscal_year),
	}
	if frappe.db.exists("Budget", filters):
		return None

	budget = frappe.new_doc("Budget")
	budget.company = company
	budget.budget_against = "Ministry"
	budget.set(fieldname, ministry)
	budget.from_fiscal_year = fiscal_year
	budget.to_fiscal_year = fiscal_year
	budget.account = account
	budget.budget_amount = flt(amount)
	budget.distribution_frequency = "Yearly"
	budget.distribute_equally = 1
	budget.applicable_on_purchase_order = 1
	budget.action_if_annual_budget_exceeded_on_po = "Stop"
	budget.action_if_accumulated_monthly_budget_exceeded_on_po = "Ignore"
	budget.applicable_on_booking_actual_expenses = 1
	budget.action_if_annual_budget_exceeded = "Stop"
	budget.action_if_accumulated_monthly_budget_exceeded = "Ignore"
	budget.applicable_on_cumulative_expense = 1
	budget.action_if_annual_exceeded_on_cumulative_expense = "Stop"
	budget.action_if_accumulated_monthly_exceeded_on_cumulative_expense = "Ignore"
	budget.insert(ignore_permissions=True)
	budget.submit()
	return budget.name


def demo_vouchers_exist(doctype, company, supplier, fy, extra_filters=None, exclude_po_linked=False):
	filters = {
		**(extra_filters or {}),
		"company": company,
		"supplier": supplier,
		"docstatus": 1,
		"transaction_date" if doctype == "Purchase Order" else "posting_date": (
			"between",
			[fy.year_start_date, fy.year_end_date],
		),
	}
	names = frappe.get_all(doctype, filters=filters, pluck="name")
	if not names:
		return False
	if exclude_po_linked:
		linked = frappe.get_all(
			"Purchase Invoice Item",
			filters={"parent": ("in", names), "purchase_order": ("is", "set")},
			pluck="parent",
		)
		return bool(set(names) - set(linked))
	return True


def demo_payment_entries_exist(company, customer, fy, extra_filters=None):
	return bool(
		frappe.db.exists(
			"Payment Entry",
			{
				**(extra_filters or {}),
				"company": company,
				"party_type": "Customer",
				"party": customer,
				"payment_type": "Receive",
				"docstatus": 1,
				"posting_date": ("between", [fy.year_start_date, fy.year_end_date]),
			},
		)
	)


def set_dimensions(doc, ministry=None, governorate=None):
	ministry_field = get_dimension_fieldname("Ministry")
	governorate_field = get_dimension_fieldname("Governorate")
	for row in [doc, *(doc.get("items") or [])]:
		if ministry and row.meta.has_field(ministry_field):
			row.set(ministry_field, ministry)
		if governorate and row.meta.has_field(governorate_field):
			row.set(governorate_field, governorate)


def make_demo_purchase_order(company, supplier, item, expense_account, cost_center, ministry, date, amount):
	po = frappe.new_doc("Purchase Order")
	po.company = company
	po.supplier = supplier
	po.transaction_date = date
	po.schedule_date = add_days(date, 7)
	po.currency = frappe.get_cached_value("Company", company, "default_currency")
	po.conversion_rate = 1
	po.append(
		"items",
		{
			"item_code": item,
			"qty": 1,
			"rate": flt(amount),
			"schedule_date": add_days(date, 7),
			"expense_account": expense_account,
			"cost_center": cost_center,
			"description": DEMO_DESCRIPTION,
		},
	)
	set_dimensions(po, ministry=ministry, governorate="Baghdad")
	po.insert(ignore_permissions=True)
	po.submit()
	return po


def bill_demo_purchase_order(po, posting_date):
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

	pi = make_purchase_invoice(po.name)
	pi.posting_date = posting_date
	pi.set_posting_time = 1
	pi.bill_no = f"DEMO-{po.name}"
	pi.bill_date = posting_date
	pi.insert(ignore_permissions=True)
	pi.submit()
	return pi


def make_demo_purchase_invoice(
	company, supplier, item, expense_account, cost_center, ministry, posting_date, amount
):
	pi = frappe.new_doc("Purchase Invoice")
	pi.company = company
	pi.supplier = supplier
	pi.posting_date = posting_date
	pi.set_posting_time = 1
	pi.currency = frappe.get_cached_value("Company", company, "default_currency")
	pi.conversion_rate = 1
	pi.bill_no = f"DEMO-{ministry}-{posting_date}"
	pi.bill_date = posting_date
	pi.append(
		"items",
		{
			"item_code": item,
			"qty": 1,
			"rate": flt(amount),
			"expense_account": expense_account,
			"cost_center": cost_center,
			"description": DEMO_DESCRIPTION,
		},
	)
	set_dimensions(pi, ministry=ministry, governorate="Baghdad")
	pi.insert(ignore_permissions=True)
	pi.submit()
	return pi


def get_demo_collection_account(company):
	account = frappe.get_cached_value("Company", company, "default_cash_account")
	if not account:
		account = frappe.db.get_value(
			"Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
		)
	if not account:
		account = frappe.db.get_value(
			"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
		)
	if not account:
		frappe.throw(_("No Cash or Bank account found for company {0}").format(company))
	return account


def make_demo_collection(company, customer, governorate, posting_date, amount):
	pe = frappe.new_doc("Payment Entry")
	pe.company = company
	pe.posting_date = posting_date
	pe.payment_type = "Receive"
	pe.party_type = "Customer"
	pe.party = customer
	pe.paid_to = get_demo_collection_account(company)
	pe.paid_amount = flt(amount)
	pe.received_amount = flt(amount)
	pe.reference_no = f"DEMO-{governorate}-{posting_date}"
	pe.reference_date = posting_date
	pe.remarks = DEMO_DESCRIPTION
	pe.setup_party_account_field()
	pe.set_missing_values()
	pe.set_exchange_rate()
	pe.received_amount = pe.paid_amount / (pe.target_exchange_rate or 1)
	set_dimensions(pe, governorate=governorate)
	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe
