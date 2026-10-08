# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.utils import flt, nowdate

from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_payment_entry
from erpnext.accounts.public_finance.budget_control import (
	PublicFinanceBudgetExceededError,
	get_commitment_vs_actual,
	roll_up_tree,
)
from erpnext.accounts.public_finance.open_data import (
	DEMO_DISCLAIMER,
	build_export,
	export_budget_vs_actual,
	rows_to_csv,
)
from erpnext.accounts.public_finance.setup import (
	DEMO_COLLECTIONS,
	DEMO_MINISTRIES,
	GOVERNORATES,
	PUBLIC_FINANCE_DIMENSIONS,
	bill_demo_purchase_order,
	ensure_demo_budget,
	ensure_demo_item,
	load_demo_budget_data,
	make_demo_purchase_invoice,
	make_demo_purchase_order,
	setup_public_finance_dimensions,
)
from erpnext.accounts.utils import get_fiscal_year
from erpnext.tests.utils import ERPNextTestSuite

COMPANY = "_Test Company"
SUPPLIER = "_Test Supplier"
ACCOUNT = "_Test Account Cost for Goods Sold - _TC"
COST_CENTER = "_Test Cost Center - _TC"
MINISTRY = "DEMO - Ministry of Health"
DIMENSION_DOCTYPES = ["GL Entry", "Budget", "Purchase Invoice", "Payment Entry", "Journal Entry Account"]


class TestPublicFinance(ERPNextTestSuite):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.db.set_single_value("Accounts Settings", "use_legacy_budget_controller", False)
		setup_public_finance_dimensions(COMPANY)
		cls.item = ensure_demo_item()
		frappe.db.commit()  # nosemgrep
		cls.fiscal_year = get_fiscal_year(nowdate(), company=COMPANY)[0]

	def get_row(self, ministry=MINISTRY, account=ACCOUNT):
		rows = get_commitment_vs_actual(
			{
				"company": COMPANY,
				"fiscal_year": self.fiscal_year,
				"dimension": "Ministry",
				"account": account,
				"dimension_value": ministry,
			}
		)
		return rows[0] if rows else frappe._dict(budget=0, committed=0, actual=0, available=0)

	def make_budget(self, amount, ministry=MINISTRY):
		name = ensure_demo_budget(COMPANY, self.fiscal_year, ministry, ACCOUNT, amount)
		self.assertTrue(name)
		return name

	def make_po(self, amount, ministry=MINISTRY):
		return make_demo_purchase_order(
			COMPANY, SUPPLIER, self.item, ACCOUNT, COST_CENTER, ministry, nowdate(), amount
		)

	def make_pi(self, amount, ministry=MINISTRY):
		return make_demo_purchase_invoice(
			COMPANY, SUPPLIER, self.item, ACCOUNT, COST_CENTER, ministry, nowdate(), amount
		)

	def test_dimensions_and_masters_created(self):
		for dimension_name, (document_type, fieldname) in PUBLIC_FINANCE_DIMENSIONS.items():
			self.assertEqual(
				frappe.db.get_value("Accounting Dimension", {"document_type": document_type}, "fieldname"),
				fieldname,
			)
			for doctype in DIMENSION_DOCTYPES:
				self.assertTrue(
					frappe.get_meta(doctype).has_field(fieldname), f"{fieldname} missing on {doctype}"
				)
			self.assertIn(dimension_name, frappe.get_meta("Budget").get_field("budget_against").options)

		# idempotent
		created = setup_public_finance_dimensions(COMPANY)
		self.assertEqual(created, {"dimensions": [], "ministries": [], "governorates": []})

		for name, arabic, _amount in DEMO_MINISTRIES:
			self.assertTrue(name.startswith("DEMO - "))
			self.assertEqual(frappe.db.get_value("Ministry", name, "ministry_name_in_arabic"), arabic)
		self.assertEqual(len(GOVERNORATES), 18)
		for name, arabic in GOVERNORATES:
			self.assertEqual(frappe.db.get_value("Governorate", name, "governorate_name_in_arabic"), arabic)

	def test_commitment_moves_to_actual_when_billed(self):
		self.make_budget(100_000)
		base = self.get_row()
		self.assertEqual(base.budget, 100_000)

		po = self.make_po(30_000)
		after_po = self.get_row()
		self.assertAlmostEqual(after_po.committed, base.committed + 30_000)
		self.assertAlmostEqual(after_po.actual, base.actual)
		self.assertAlmostEqual(after_po.available, 100_000 - after_po.committed - after_po.actual)
		self.assertAlmostEqual(after_po.percent_consumed, (after_po.committed + after_po.actual) / 1000)

		pi = bill_demo_purchase_order(po, nowdate())
		self.assertEqual(pi.docstatus, 1)
		self.assertEqual(pi.items[0].get("ministry"), MINISTRY)
		after_pi = self.get_row()
		self.assertAlmostEqual(after_pi.committed, base.committed)
		self.assertAlmostEqual(after_pi.actual, base.actual + 30_000)

	def test_purchase_invoice_overspend_is_blocked(self):
		self.make_budget(50_000)
		self.make_po(30_000)

		within = self.make_pi(15_000)
		self.assertEqual(within.docstatus, 1)

		# committed 30,000 + actual 15,000 + requested 10,000 > budget 50,000
		with self.assertRaises(PublicFinanceBudgetExceededError) as ctx:
			self.make_pi(10_000)
		message = str(ctx.exception)
		self.assertIn(MINISTRY, message)
		self.assertIn("تم تجاوز الميزانية", message)
		self.assertIn("تجريبي - وزارة الصحة", message)
		self.assertIn("Budget exceeded", message)

		row = self.get_row()
		self.assertAlmostEqual(row.committed, 30_000)
		self.assertAlmostEqual(row.actual, 15_000)

	def test_billing_a_committed_po_is_not_double_counted(self):
		self.make_budget(50_000)
		po = self.make_po(45_000)
		pi = bill_demo_purchase_order(po, nowdate())
		self.assertEqual(pi.docstatus, 1)
		row = self.get_row()
		self.assertAlmostEqual(row.committed, 0)
		self.assertAlmostEqual(row.actual, 45_000)

	def test_payment_entry_overspend_is_blocked(self):
		self.make_budget(50_000)
		self.make_pi(30_000)

		def make_pe(amount):
			pe = create_payment_entry(
				company=COMPANY,
				payment_type="Pay",
				party_type="Supplier",
				party=SUPPLIER,
				paid_from="_Test Bank - _TC",
				paid_to="Creditors - _TC",
				paid_amount=amount,
			)
			pe.set("ministry", MINISTRY)
			pe.insert()
			pe.submit()
			return pe

		within = make_pe(10_000)
		self.assertEqual(within.docstatus, 1)

		with self.assertRaises(PublicFinanceBudgetExceededError) as ctx:
			make_pe(25_000)
		self.assertIn("تم تجاوز الميزانية", str(ctx.exception))

		# earlier unallocated disbursements count as consumed: 30k invoice + 10k paid = 40k of 50k
		self.assertRaises(PublicFinanceBudgetExceededError, make_pe, 15_000)
		self.assertEqual(make_pe(10_000).docstatus, 1)

	def test_roll_up_tree_keeps_parent_direct_amounts(self):
		parent = frappe.db.get_value("Cost Center", COST_CENTER, "parent_cost_center")
		rolled = roll_up_tree(
			"Cost Center",
			{(parent, ACCOUNT): 100},
			{(parent, ACCOUNT): 20, (COST_CENTER, ACCOUNT): 90},
		)
		self.assertAlmostEqual(rolled[(parent, ACCOUNT)], 110)
		self.assertAlmostEqual(rolled[(COST_CENTER, ACCOUNT)], 90)

	def test_budget_data_requires_budget_permission(self):
		filters = {"company": COMPANY, "fiscal_year": self.fiscal_year, "dimension": "Ministry"}
		with self.set_user("test@example.com"):
			self.assertRaises(frappe.PermissionError, get_commitment_vs_actual, filters)
			self.assertRaises(
				frappe.PermissionError, export_budget_vs_actual, COMPANY, self.fiscal_year, "Ministry"
			)

	def test_open_data_export_csv_and_json(self):
		self.make_budget(100_000)
		self.make_po(30_000)
		self.make_pi(20_000)

		meta, rows = build_export(COMPANY, self.fiscal_year, "Ministry", ACCOUNT)
		row = next(r for r in rows if r.dimension == MINISTRY)
		self.assertAlmostEqual(row.budget, 100_000)
		self.assertAlmostEqual(row.committed, 30_000)
		self.assertAlmostEqual(row.actual, 20_000)
		self.assertAlmostEqual(row.available, 50_000)
		self.assertAlmostEqual(row.percent_consumed, 50)
		self.assertEqual(meta["disclaimer"], DEMO_DISCLAIMER)

		csv_content = rows_to_csv(rows)
		header, *lines = csv_content.lstrip("\ufeff").splitlines()
		self.assertIn("Budget / الميزانية", header)
		self.assertIn("Committed / الالتزامات", header)
		self.assertTrue(any(MINISTRY in line and "تجريبي - وزارة الصحة" in line for line in lines))

		export_budget_vs_actual(COMPANY, self.fiscal_year, "Ministry", fmt="csv", account=ACCOUNT)
		self.assertEqual(frappe.response["type"], "download")
		self.assertTrue(frappe.response["filename"].endswith(".csv"))
		self.assertIn(MINISTRY, frappe.response["filecontent"])

		export_budget_vs_actual(COMPANY, self.fiscal_year, "Ministry", fmt="json", account=ACCOUNT)
		self.assertEqual(frappe.response["type"], "download")
		payload = json.loads(frappe.response["filecontent"])
		for key in ("generated_at", "company", "fiscal_year", "dimension", "disclaimer"):
			self.assertIn(key, payload["meta"])
		self.assertIn("DEMO", payload["meta"]["disclaimer"])
		self.assertEqual(payload["meta"]["company"], COMPANY)
		self.assertEqual(payload["meta"]["fiscal_year"], self.fiscal_year)
		self.assertEqual(payload["meta"]["dimension"], "Ministry")
		data_row = next(r for r in payload["data"] if r["dimension"] == MINISTRY)
		self.assertEqual(flt(data_row["budget"]), 100_000)
		self.assertEqual(flt(data_row["committed"]), 30_000)
		self.assertEqual(flt(data_row["actual"]), 20_000)

	def test_load_demo_budget_data_is_idempotent(self):
		summary = load_demo_budget_data(COMPANY, self.fiscal_year)
		self.assertEqual(len(summary.budgets), len(DEMO_MINISTRIES))
		self.assertTrue(summary.purchase_orders)
		self.assertTrue(summary.purchase_invoices)
		self.assertEqual(len(summary.payment_entries), len(DEMO_COLLECTIONS))

		again = load_demo_budget_data(COMPANY, self.fiscal_year)
		self.assertEqual(
			(again.budgets, again.purchase_orders, again.purchase_invoices, again.payment_entries),
			([], [], [], []),
		)

		rows = get_commitment_vs_actual(
			{"company": COMPANY, "fiscal_year": self.fiscal_year, "dimension": "Ministry"}
		)
		budgeted = [r for r in rows if r.budget]
		self.assertEqual(len(budgeted), len(DEMO_MINISTRIES))
		self.assertTrue(any(r.committed for r in rows))
		self.assertTrue(any(r.actual for r in rows))

		collections = frappe.get_all(
			"Payment Entry",
			filters={
				"company": COMPANY,
				"payment_type": "Receive",
				"docstatus": 1,
				"governorate": ("is", "set"),
			},
			fields=["governorate", "base_received_amount"],
		)
		self.assertTrue({c.governorate for c in collections} >= set(DEMO_COLLECTIONS))
		self.assertTrue(all(c.base_received_amount > 0 for c in collections))
