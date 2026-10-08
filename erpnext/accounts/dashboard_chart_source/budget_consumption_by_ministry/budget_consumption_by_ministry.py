# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, nowdate
from frappe.utils.dashboard import cache_source

from erpnext.accounts.public_finance.budget_control import get_commitment_vs_actual
from erpnext.accounts.utils import get_fiscal_year


@frappe.whitelist()
@cache_source
def get(
	chart_name: str | None = None,
	chart: str | dict | None = None,
	no_cache: bool | None = None,
	filters: str | dict | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	timespan: str | None = None,
	time_interval: str | None = None,
	heatmap_year: str | None = None,
):
	filters = frappe._dict(frappe.parse_json(filters) or {})
	company = (
		filters.company
		or frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
		or frappe.db.get_value("Company", {}, "name")
	)
	fiscal_year = filters.fiscal_year or get_fiscal_year(nowdate(), company=company)[0]

	rows = get_commitment_vs_actual(
		{"company": company, "fiscal_year": fiscal_year, "dimension": filters.dimension or "Ministry"}
	)

	totals = {}
	for row in rows:
		t = totals.setdefault(row.dimension, frappe._dict(budget=0, committed=0, actual=0))
		t.budget += row.budget
		t.committed += row.committed
		t.actual += row.actual

	labels, values = [], []
	for dimension, t in sorted(totals.items()):
		if not t.budget:
			continue
		labels.append(dimension.replace("DEMO - Ministry of ", ""))
		values.append(flt((t.committed + t.actual) / t.budget * 100, 1))

	return {
		"labels": labels,
		"datasets": [{"name": _("% Consumed (Committed + Actual)"), "values": values}],
	}
