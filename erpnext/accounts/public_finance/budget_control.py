# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""
Commitment vs actual calculation and overspend block for the Iraq Public Finance Pack (DEMO).

Committed  = submitted, not closed Purchase Orders that are not yet billed (amount - billed_amt),
             mirroring ``erpnext.controllers.budget_controller.BudgetValidation.get_ordered_amount``.
Actual     = GL Entry debit - credit on expense accounts for the dimension, mirroring
             ``BudgetValidation.get_actual_expense``.
Available  = Budget - Committed - Actual.

DEMO ASSUMPTION (no public spec): a supplier Payment Entry tagged with a Ministry / Governorate and
not allocated against any invoice is treated as a direct disbursement and is checked against the
total available budget of that dimension across all budgeted accounts. Payments allocated against
invoices are skipped because the invoice already consumed the budget.
"""

import frappe
from frappe import _, qb
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import escape_html, flt, fmt_money, getdate

from erpnext.accounts.utils import get_fiscal_year

PUBLIC_FINANCE_DIMENSION_TYPES = ("Ministry", "Governorate")

DIMENSION_LABELS_AR = {
	"Ministry": "الوزارة",
	"Governorate": "المحافظة",
	"Cost Center": "مركز التكلفة",
	"Project": "المشروع",
}

STANDARD_DIMENSION_FIELDS = {"Cost Center": "cost_center", "Project": "project"}


class PublicFinanceBudgetExceededError(frappe.ValidationError):
	pass


def get_dimension_fieldname(dimension):
	if dimension in STANDARD_DIMENSION_FIELDS:
		return STANDARD_DIMENSION_FIELDS[dimension]
	fieldname = frappe.db.get_value("Accounting Dimension", {"document_type": dimension}, "fieldname")
	if not fieldname:
		frappe.throw(_("Accounting Dimension for {0} is not set up").format(dimension))
	return fieldname


def get_arabic_name_field(dimension):
	meta = frappe.get_meta(dimension)
	for df in meta.fields:
		if df.fieldname.endswith("_in_arabic"):
			return df.fieldname
	return None


def get_fiscal_year_dates(fiscal_year):
	return frappe.db.get_value("Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"])


def get_commitment_vs_actual(filters: dict | str | None):
	"""
	Return one row per (dimension value, account) with budget, committed, actual, available and
	percent_consumed. ``filters``: company, fiscal_year, dimension (Ministry / Governorate /
	Cost Center / Project), optional account and dimension_value.
	"""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	filters = frappe._dict(filters or {})

	if not (filters.company and filters.fiscal_year and filters.dimension):
		frappe.throw(_("Company, Fiscal Year and Dimension are required"))

	fieldname = get_dimension_fieldname(filters.dimension)
	fy_start, fy_end = get_fiscal_year_dates(filters.fiscal_year)

	budgets = get_budget_amounts(filters, fieldname, fy_start, fy_end)
	committed = get_committed_amounts(filters, fieldname, fy_start, fy_end)
	actual = get_actual_amounts(filters, fieldname, fy_start, fy_end)

	is_tree = frappe.get_meta(filters.dimension).is_tree
	if is_tree:
		committed = roll_up_tree(filters.dimension, budgets, committed)
		actual = roll_up_tree(filters.dimension, budgets, actual)

	keys = set(budgets) | set(committed) | set(actual)
	if filters.dimension_value:
		keys = {k for k in keys if k[0] == filters.dimension_value}

	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	arabic_field = get_arabic_name_field(filters.dimension)
	arabic_names = {}
	if arabic_field and keys:
		arabic_names = dict(
			frappe.get_all(
				filters.dimension,
				filters={"name": ("in", [k[0] for k in keys])},
				fields=["name", arabic_field],
				as_list=True,
			)
		)

	rows = []
	for dimension_value, account in sorted(keys, key=lambda k: (k[0] or "", k[1] or "")):
		budget = flt(budgets.get((dimension_value, account)))
		committed_amt = flt(committed.get((dimension_value, account)))
		actual_amt = flt(actual.get((dimension_value, account)))
		consumed = committed_amt + actual_amt
		rows.append(
			frappe._dict(
				dimension_type=filters.dimension,
				dimension=dimension_value,
				dimension_name_in_arabic=arabic_names.get(dimension_value),
				account=account,
				budget=budget,
				committed=committed_amt,
				actual=actual_amt,
				available=budget - consumed,
				percent_consumed=(consumed / budget * 100.0) if budget else None,
				currency=currency,
			)
		)
	return rows


def get_budget_amounts(filters, fieldname, fy_start, fy_end):
	bud = qb.DocType("Budget")
	query = (
		qb.from_(bud)
		.select(bud[fieldname], bud.account, Sum(bud.budget_amount).as_("amount"))
		.where(
			(bud.docstatus == 1)
			& (bud.company == filters.company)
			& (bud.budget_against == filters.dimension)
			& (bud.budget_start_date <= fy_end)
			& (bud.budget_end_date >= fy_start)
			& (IfNull(bud[fieldname], "") != "")
		)
		.groupby(bud[fieldname], bud.account)
	)
	if filters.account:
		query = query.where(bud.account == filters.account)
	return {(r[0], r[1]): flt(r[2]) for r in query.run()}


def get_committed_amounts(filters, fieldname, fy_start, fy_end):
	po = qb.DocType("Purchase Order")
	poi = qb.DocType("Purchase Order Item")
	query = (
		qb.from_(po)
		.inner_join(poi)
		.on(poi.parent == po.name)
		.select(
			poi[fieldname],
			poi.expense_account,
			Sum((IfNull(poi.amount, 0) - IfNull(poi.billed_amt, 0)) * IfNull(po.conversion_rate, 1)).as_(
				"amount"
			),
		)
		.where(
			(po.docstatus == 1)
			& (po.status != "Closed")
			& (po.company == filters.company)
			& (po.transaction_date[fy_start:fy_end])
			& (poi.amount > IfNull(poi.billed_amt, 0))
			& (IfNull(poi[fieldname], "") != "")
			& (IfNull(poi.expense_account, "") != "")
		)
		.groupby(poi[fieldname], poi.expense_account)
	)
	if filters.account:
		query = query.where(poi.expense_account == filters.account)
	return {(r[0], r[1]): flt(r[2]) for r in query.run()}


def get_actual_amounts(filters, fieldname, fy_start, fy_end):
	gl = qb.DocType("GL Entry")
	acc = qb.DocType("Account")
	query = (
		qb.from_(gl)
		.inner_join(acc)
		.on(acc.name == gl.account)
		.select(gl[fieldname], gl.account, (Sum(gl.debit) - Sum(gl.credit)).as_("amount"))
		.where(
			(gl.is_cancelled == 0)
			& (gl.company == filters.company)
			& (gl.posting_date[fy_start:fy_end])
			& (IfNull(gl[fieldname], "") != "")
			& (acc.root_type == "Expense")
			& (gl.voucher_type != "Period Closing Voucher")
		)
		.groupby(gl[fieldname], gl.account)
	)
	if filters.account:
		query = query.where(gl.account == filters.account)
	return {(r[0], r[1]): flt(r[2]) for r in query.run()}


def roll_up_tree(dimension, budgets, amounts):
	"""For tree dimensions, add descendants' amounts to budget rows held at group nodes."""
	budgeted = {k[0] for k in budgets}
	if not budgeted:
		return amounts
	group_nodes = set(
		frappe.get_all(dimension, filters={"name": ("in", list(budgeted)), "is_group": 1}, pluck="name")
	)
	if not group_nodes:
		return amounts
	nodes = frappe.get_all(
		dimension,
		filters={"name": ("in", list(group_nodes | {k[0] for k in amounts}))},
		fields=["name", "lft", "rgt"],
	)
	bounds = {n.name: (n.lft, n.rgt) for n in nodes}
	rolled = dict(amounts)
	for group in group_nodes:
		lft, rgt = bounds.get(group, (None, None))
		if lft is None:
			continue
		for (node, account), amount in amounts.items():
			if node == group:
				continue
			node_lft, node_rgt = bounds.get(node, (None, None))
			if node_lft is not None and lft < node_lft and node_rgt < rgt:
				rolled[(group, account)] = flt(rolled.get((group, account))) + amount
	return rolled


def get_public_finance_dimensions():
	return frappe.get_all(
		"Accounting Dimension",
		filters={"document_type": ("in", PUBLIC_FINANCE_DIMENSION_TYPES), "disabled": 0},
		fields=["document_type", "fieldname"],
	)


def validate_purchase_invoice_budget(doc, method=None):
	"""Block submission of a Purchase Invoice that would push Committed + Actual over the Budget."""
	if doc.docstatus != 1 or doc.is_return or frappe.flags.in_install or frappe.flags.in_migrate:
		return
	dimensions = get_public_finance_dimensions()
	if not dimensions:
		return

	fiscal_year = get_fiscal_year(doc.posting_date, company=doc.company)[0]
	requested = {}
	already_committed = {}
	for item in doc.items:
		if not item.expense_account:
			continue
		for dim in dimensions:
			value = item.get(dim.fieldname) or doc.get(dim.fieldname)
			if not value:
				continue
			key = (dim.document_type, value, item.expense_account)
			requested[key] = flt(requested.get(key)) + flt(item.base_net_amount)
			if item.get("po_detail"):
				released = get_released_po_commitment(item, dim.fieldname, value)
				if released:
					already_committed[key] = flt(already_committed.get(key)) + released

	for (dimension, value, account), amount in requested.items():
		rows = get_commitment_vs_actual(
			{
				"company": doc.company,
				"fiscal_year": fiscal_year,
				"dimension": dimension,
				"account": account,
				"dimension_value": value,
			}
		)
		row = next((r for r in rows if r.dimension == value and r.account == account), None)
		if not row or not row.budget:
			continue
		committed = max(row.committed - flt(already_committed.get((dimension, value, account))), 0.0)
		raise_if_exceeded(doc.company, dimension, value, row, committed, amount)


def get_released_po_commitment(item, fieldname, value):
	"""Commitment (company currency, at the PO's own exchange rate) that billing this invoice row releases.

	Only counted when the linked PO row carries the same dimension value and expense account, and capped
	at the PO row's remaining unbilled amount so a mismatched or over-billed PO cannot free unrelated budget.
	"""
	po_item = frappe.db.get_value(
		"Purchase Order Item",
		item.po_detail,
		[fieldname, "expense_account", "parent", "amount", "billed_amt"],
		as_dict=True,
	)
	if not po_item or po_item.get(fieldname) != value or po_item.expense_account != item.expense_account:
		return 0.0
	po_rate = flt(frappe.db.get_value("Purchase Order", po_item.parent, "conversion_rate")) or 1.0
	remaining = max(flt(po_item.amount) - flt(po_item.billed_amt), 0.0)
	return min(flt(item.net_amount), remaining) * po_rate


def get_direct_disbursement(pe):
	"""Part of a supplier payment not allocated against a Purchase Invoice or Purchase Order (company currency).

	Allocations to a Purchase Invoice are already in Actual; advances allocated to a Purchase Order are already
	in Committed (``get_committed_amounts``), so neither consumes additional budget here.
	"""
	allocated = sum(
		flt(ref.allocated_amount)
		for ref in (pe.get("references") or [])
		if ref.reference_doctype in ("Purchase Invoice", "Purchase Order")
	)
	rate = flt(pe.base_paid_amount) / flt(pe.paid_amount) if flt(pe.paid_amount) else 1.0
	return max(flt(pe.base_paid_amount) - allocated * rate, 0.0)


def get_prior_direct_disbursements(company, fieldname, value, fiscal_year, exclude=None):
	fy_start, fy_end = get_fiscal_year_dates(fiscal_year)
	names = frappe.get_all(
		"Payment Entry",
		filters={
			"company": company,
			"docstatus": 1,
			"payment_type": "Pay",
			"party_type": "Supplier",
			fieldname: value,
			"posting_date": ("between", [fy_start, fy_end]),
			"name": ("!=", exclude or ""),
		},
		pluck="name",
	)
	return sum(get_direct_disbursement(frappe.get_doc("Payment Entry", name)) for name in names)


def validate_payment_entry_budget(doc, method=None):
	"""
	DEMO ASSUMPTION: the part of a supplier payment that is not allocated against a Purchase Invoice is a
	direct disbursement; together with earlier direct disbursements for the same dimension it is checked
	against the dimension's total available budget (committed + actual + disbursed + requested <= budget).
	"""
	if doc.docstatus != 1 or doc.payment_type != "Pay" or doc.party_type != "Supplier":
		return
	requested = get_direct_disbursement(doc)
	if requested <= 0:
		return
	dimensions = get_public_finance_dimensions()
	if not dimensions:
		return

	fiscal_year = get_fiscal_year(doc.posting_date, company=doc.company)[0]
	for dim in dimensions:
		value = doc.get(dim.fieldname)
		if not value:
			continue
		rows = get_commitment_vs_actual(
			{
				"company": doc.company,
				"fiscal_year": fiscal_year,
				"dimension": dim.document_type,
				"dimension_value": value,
			}
		)
		total = frappe._dict(
			dimension=value,
			dimension_name_in_arabic=rows[0].dimension_name_in_arabic if rows else None,
			budget=sum(r.budget for r in rows),
			committed=sum(r.committed for r in rows),
			actual=sum(r.actual for r in rows),
		)
		if not total.budget:
			continue
		disbursed = get_prior_direct_disbursements(doc.company, dim.fieldname, value, fiscal_year, doc.name)
		raise_if_exceeded(
			doc.company, dim.document_type, value, total, total.committed + disbursed, requested
		)


def raise_if_exceeded(company, dimension, value, row, committed, requested):
	consumed = flt(committed) + flt(row.actual)
	if consumed + flt(requested) <= flt(row.budget) + 0.005:
		return

	currency = frappe.get_cached_value("Company", company, "default_currency")
	money = lambda amount: fmt_money(amount, currency=currency)  # noqa: E731
	available = flt(row.budget) - consumed
	value = escape_html(value)
	arabic_value = escape_html(row.get("dimension_name_in_arabic") or value)
	dimension_ar = DIMENSION_LABELS_AR.get(dimension, dimension)

	message_en = _(
		"Budget exceeded for {0} {1}: Budget {2}, Consumed {3} (Committed {4} + Actual {5}), "
		"Requested {6}, Available {7}."
	).format(
		_(dimension),
		frappe.bold(value),
		money(row.budget),
		money(consumed),
		money(committed),
		money(row.actual),
		frappe.bold(money(requested)),
		money(available),
	)
	message_ar = (
		f"تم تجاوز الميزانية لـ{dimension_ar} {frappe.bold(arabic_value)}: الميزانية {money(row.budget)}، "
		f"المستهلك {money(consumed)} (الالتزامات {money(committed)} + الفعلي {money(row.actual)})، "
		f"المطلوب {frappe.bold(money(requested))}، المتاح {money(available)}."
	)
	frappe.throw(
		f"{message_en}<br><div dir='rtl'>{message_ar}</div>",
		PublicFinanceBudgetExceededError,
		title=_("Budget Exceeded") + " / تم تجاوز الميزانية",
	)
