# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import flt, fmt_money, nowdate

from erpnext.regional.iraq.setup import PRINT_FORMAT, setup
from erpnext.regional.iraq.utils import (
	get_governorates,
	is_valid_iraq_tax_id,
	validate_iraq_tax_id,
	validate_party_tax_id,
)
from erpnext.tests.utils import ERPNextTestSuite
from erpnext.utilities.regional import temporary_flag

COMPANY = "DEMO - Iraq Test Company"
COMPANY_ABBR = "DIQT"
COMPANY_TAX_ID = "IQ0000000001"
CUSTOMER_TAX_ID = "IQ1234567890"
COMPANY_NAME_AR = "تجريبي - شركة العراق للاختبار"
CUSTOMER = "DEMO - Iraq Test Customer"
PRICE_LIST = "DEMO - Iraq Selling (IQD)"
DEFAULT_TAX_TEMPLATE = "DEMO - Iraq Sales Tax 10% (Deluxe/First-class Hotels and Restaurants)"

VALID_TAX_IDS = ["IQ1234567890", "1234567890", "iq0987654321"]
INVALID_TAX_IDS = ["123", "IQ12345", "ABCDEFGHIJ", "IQ-1234567890", "12345678901"]


class TestIraq(ERPNextTestSuite):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = make_iraq_company()
		cls.customer = make_iraq_customer()
		make_iraq_price_list()
		frappe.db.commit()  # nosemgrep

	def test_company_creation_runs_regional_setup(self):
		"""Creating a Company with country Iraq triggers erpnext.regional.iraq.setup.setup."""
		self.assertEqual(frappe.db.get_value("Company", COMPANY, "country"), "Iraq")
		for dt, fieldname in (
			("Company", "iraq_tax_id"),
			("Company", "company_name_in_arabic"),
			("Customer", "iraq_tax_id"),
			("Customer", "customer_name_in_arabic"),
			("Supplier", "iraq_tax_id"),
			("Supplier", "supplier_name_in_arabic"),
			("Territory", "territory_name_in_arabic"),
			("Sales Invoice", "iraq_tax_id"),
			("Sales Invoice", "company_iraq_tax_id"),
			("Sales Invoice", "customer_name_in_arabic"),
			("Purchase Invoice", "iraq_tax_id"),
			("Purchase Invoice", "supplier_name_in_arabic"),
			("Sales Invoice Item", "tax_rate"),
			("Purchase Invoice Item", "total_amount"),
		):
			self.assertTrue(
				frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}),
				f"Custom Field {dt}.{fieldname} missing",
			)

		self.assertEqual(frappe.db.get_value("Currency", "IQD", "enabled"), 1)

	def test_governorates_created_and_idempotent(self):
		governorates = get_governorates()
		self.assertEqual(len(governorates), 18)

		root = frappe.db.get_value("Territory", {"is_group": 1, "parent_territory": ("is", "not set")})
		for row in governorates:
			self.assertTrue(frappe.db.exists("Territory", row["territory_name"]), row["territory_name"])
			parent, arabic = frappe.db.get_value(
				"Territory", row["territory_name"], ["parent_territory", "territory_name_in_arabic"]
			)
			self.assertEqual(parent, root)
			self.assertEqual(arabic, row["territory_name_in_arabic"])

		names = [row["territory_name"] for row in governorates]
		before = frappe.db.count("Territory", {"name": ("in", names)})

		# re-running the whole regional setup must not duplicate anything
		setup(COMPANY)
		after = frappe.db.count("Territory", {"name": ("in", names)})
		self.assertEqual(before, after, 18)
		self.assertEqual(
			frappe.db.count("Custom Field", {"dt": "Territory", "fieldname": "territory_name_in_arabic"}), 1
		)

	def test_tax_id_validation(self):
		for value in VALID_TAX_IDS:
			self.assertTrue(is_valid_iraq_tax_id(value), value)
			self.assertTrue(validate_iraq_tax_id(value), value)

		for value in INVALID_TAX_IDS:
			self.assertFalse(is_valid_iraq_tax_id(value), value)
			self.assertFalse(validate_iraq_tax_id(value, throw=False), value)
			self.assertRaises(frappe.ValidationError, validate_iraq_tax_id, value)

		# empty is allowed (optional field)
		self.assertTrue(validate_iraq_tax_id(None))
		self.assertTrue(validate_iraq_tax_id(""))

	def test_party_tax_id_hook(self):
		customer = frappe.get_doc("Customer", CUSTOMER)
		customer.iraq_tax_id = "IQ1234567890"
		validate_party_tax_id(customer)

		customer.iraq_tax_id = "bad-id"
		self.assertRaises(frappe.ValidationError, validate_party_tax_id, customer)

		company = frappe.get_doc("Company", COMPANY)
		company.iraq_tax_id = "12"
		self.assertRaises(frappe.ValidationError, validate_party_tax_id, company)

	def test_invoice_validate_regional_rejects_bad_tax_id(self):
		# bypass document validation to seed a malformed id on the customer
		frappe.db.set_value("Customer", CUSTOMER, "iraq_tax_id", "NOT-VALID")
		si = make_iraq_sales_invoice(do_not_insert=True)
		self.assertRaises(frappe.ValidationError, si.insert)

	def test_print_format_installed_and_enabled(self):
		self.assertTrue(frappe.db.exists("Print Format", PRINT_FORMAT))
		pf = frappe.get_doc("Print Format", PRINT_FORMAT)
		self.assertEqual(pf.disabled, 0)
		self.assertEqual(pf.doc_type, "Sales Invoice")
		self.assertEqual(pf.print_format_type, "Jinja")
		self.assertIn('dir="rtl"', pf.html)
		self.assertIn("فاتورة ضريبية", pf.html)

	def test_tax_templates_created(self):
		for doctype in ("Sales Taxes and Charges Template", "Purchase Taxes and Charges Template"):
			name = frappe.db.get_value(doctype, {"title": DEFAULT_TAX_TEMPLATE, "company": COMPANY})
			self.assertTrue(name, f"{doctype} '{DEFAULT_TAX_TEMPLATE}' missing")
			template = frappe.get_doc(doctype, name)
			self.assertEqual(template.is_default, 1)
			self.assertEqual(len(template.taxes), 1)
			self.assertEqual(flt(template.taxes[0].rate), 10.0)
			self.assertEqual(template.taxes[0].account_head, f"Sales Tax 10% - {COMPANY_ABBR}")

		titles = frappe.get_all(
			"Sales Taxes and Charges Template",
			filters={"company": COMPANY, "title": ("like", "DEMO - Iraq Sales Tax%")},
			pluck="title",
		)
		self.assertEqual(len(titles), 4)
		self.assertTrue(
			frappe.db.exists("Item Tax Template", {"title": DEFAULT_TAX_TEMPLATE, "company": COMPANY})
		)

	def test_update_itemised_tax_data_and_print(self):
		si = make_iraq_sales_invoice()
		si.reload()

		item = si.items[0]
		self.assertEqual(flt(item.tax_rate), 10.0)
		self.assertEqual(flt(item.tax_amount, 3), flt(item.net_amount * 0.10, 3))
		self.assertEqual(flt(item.total_amount, 3), flt(item.net_amount + item.tax_amount, 3))
		self.assertEqual(si.iraq_tax_id, "IQ1234567890")
		self.assertEqual(si.company_iraq_tax_id, COMPANY_TAX_ID)
		self.assertEqual(si.customer_name_in_arabic, "تجريبي - عميل العراق")

		# recalculating the (reloaded) invoice re-runs the regional override
		item.tax_rate = item.tax_amount = item.total_amount = 0
		si.calculate_taxes_and_totals()
		self.assertEqual(flt(si.items[0].tax_rate), 10.0)

		html = frappe.get_print("Sales Invoice", si.name, PRINT_FORMAT)
		self.assertIn('dir="rtl"', html)
		self.assertIn("IQ1234567890", html)
		self.assertIn(COMPANY_TAX_ID, html)
		self.assertIn("تجريبي - عميل العراق", html)
		# IQD renders with 3 decimals (fils) even though the site currency_precision is 2
		self.assertIn(fmt_money(si.grand_total, 3, "IQD"), html)
		self.assertIn(fmt_money(si.items[0].net_rate, 3, "IQD"), html)

	def test_itemised_tax_per_row_currency_and_reset(self):
		with (
			self.change_settings("Selling Settings", {"allow_multiple_items": 1}),
			self.change_settings(
				"Accounts Settings", {"allow_multi_currency_invoices_against_single_party_account": 1}
			),
		):
			frappe.clear_cache(doctype="Selling Settings")
			# two rows with the same item code must not be double counted; amounts are in invoice currency
			si = make_iraq_sales_invoice(do_not_insert=True)
			si.append("items", si.items[0].as_dict(no_default_fields=True) | {"qty": 1, "rate": 50000})
			si.currency = "USD"
			si.price_list_currency = "USD"
			si.conversion_rate = si.plc_conversion_rate = 1300
			si.insert()

			for row in si.items:
				self.assertEqual(flt(row.tax_rate), 10.0)
				self.assertEqual(flt(row.tax_amount, 2), flt(row.net_amount * 0.10, 2))
				self.assertEqual(flt(row.total_amount, 2), flt(row.net_amount + row.tax_amount, 2))
			self.assertEqual(
				flt(sum(row.tax_amount for row in si.items), 2), flt(si.total_taxes_and_charges, 2)
			)

			# removing every tax row resets the per-item fields
			si.taxes = []
			si.save()
			for row in si.items:
				self.assertEqual(flt(row.tax_rate), 0.0)
				self.assertEqual(flt(row.tax_amount), 0.0)
				self.assertEqual(flt(row.total_amount), flt(row.net_amount))

	def test_allocate_tax_row_edge_cases(self):
		from erpnext.regional.iraq.utils import _allocate_tax_row

		def detail(net_amount, rate, amount):
			item = frappe._dict(net_amount=net_amount, qty=1, precision=lambda field: 3)
			return frappe._dict(item=item, rate=rate, amount=amount)

		doc = frappe._dict(conversion_rate=1.0)

		# zero-rated item next to a taxed one: the exempt row must get no tax
		tax = frappe._dict(charge_type="On Net Total", tax_amount_after_discount_amount=10.0)
		allocated = [a for _, _, a in _allocate_tax_row(doc, tax, [detail(100, 10, 10), detail(100, 0, 0)])]
		self.assertEqual(allocated, [10.0, 0.0])

		# fixed (Actual) charge on a balanced invoice: sale and return cancel, charge lands on the last row
		tax = frappe._dict(charge_type="Actual", tax_amount_after_discount_amount=10.0)
		allocated = [a for _, _, a in _allocate_tax_row(doc, tax, [detail(100, 0, 10), detail(-100, 0, 0)])]
		self.assertEqual(allocated, [0.0, 10.0])
		self.assertEqual(sum(allocated), 10.0)

		# Actual charge spread by net amount (rate is not a percentage here)
		allocated = [a for _, _, a in _allocate_tax_row(doc, tax, [detail(300, 0, 7.5), detail(100, 0, 2.5)])]
		self.assertEqual(allocated, [7.5, 2.5])

		# tax wiped out by a Grand Total discount stays zero on every row
		tax = frappe._dict(charge_type="On Net Total", tax_amount_after_discount_amount=0.0)
		allocated = [a for _, _, a in _allocate_tax_row(doc, tax, [detail(100, 10, 10), detail(100, 10, 10)])]
		self.assertEqual(allocated, [0.0, 0.0])


def make_iraq_company():
	if not frappe.db.exists("Company", COMPANY):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": COMPANY,
				"abbr": COMPANY_ABBR,
				"country": "Iraq",
				"default_currency": "IQD",
				"chart_of_accounts": "Standard",
				"default_holiday_list": "_Test Holiday List",
			}
		).insert()

	# The Iraq custom fields are created by the regional setup in Company.on_update, so a doc instance
	# built before insert() still carries the pre-setup meta; load a fresh instance before writing them.
	company = frappe.get_doc("Company", COMPANY)
	if company.iraq_tax_id != COMPANY_TAX_ID or company.company_name_in_arabic != COMPANY_NAME_AR:
		company.company_name_in_arabic = COMPANY_NAME_AR
		company.iraq_tax_id = COMPANY_TAX_ID
		company.save()
	return company


def make_iraq_customer():
	if frappe.db.exists("Customer", CUSTOMER):
		customer = frappe.get_doc("Customer", CUSTOMER)
		if customer.iraq_tax_id != CUSTOMER_TAX_ID:
			frappe.db.set_value("Customer", CUSTOMER, "iraq_tax_id", CUSTOMER_TAX_ID)
			customer.reload()
		return customer

	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": CUSTOMER,
			"customer_type": "Company",
			"customer_group": "_Test Customer Group",
			"territory": "Baghdad",
			"customer_name_in_arabic": "تجريبي - عميل العراق",
			"iraq_tax_id": CUSTOMER_TAX_ID,
		}
	)
	customer.insert()
	return customer


def make_iraq_price_list():
	if frappe.db.exists("Price List", PRICE_LIST):
		return
	frappe.get_doc(
		{
			"doctype": "Price List",
			"price_list_name": PRICE_LIST,
			"currency": "IQD",
			"selling": 1,
			"enabled": 1,
		}
	).insert()


def make_iraq_sales_invoice(do_not_insert=False):
	company = frappe.get_doc("Company", COMPANY)
	si = frappe.new_doc("Sales Invoice")
	si.company = COMPANY
	si.customer = CUSTOMER
	si.posting_date = nowdate()
	si.currency = "IQD"
	si.conversion_rate = 1
	si.selling_price_list = PRICE_LIST
	si.price_list_currency = "IQD"
	si.plc_conversion_rate = 1
	si.debit_to = company.default_receivable_account
	si.cost_center = company.cost_center
	si.append(
		"items",
		{
			"item_code": "_Test Item",
			"qty": 2,
			"rate": 125000,
			"income_account": f"Sales - {COMPANY_ABBR}",
			"cost_center": company.cost_center,
		},
	)
	si.append(
		"taxes",
		{
			"charge_type": "On Net Total",
			"account_head": f"Sales Tax 10% - {COMPANY_ABBR}",
			"description": "DEMO - Sales Tax 10%",
			"rate": 10,
			"cost_center": company.cost_center,
		},
	)
	if not do_not_insert:
		si.insert()
	return si
