# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Open-data export of the Budget Commitment vs Actual figures (DEMO data)."""

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from frappe.utils.csvutils import to_csv

from erpnext.accounts.public_finance.budget_control import get_commitment_vs_actual

DEMO_DISCLAIMER = "DEMO data - not official figures. / بيانات تجريبية - ليست أرقاماً رسمية."

# (json key, "English / Arabic" header)
EXPORT_COLUMNS = [
	("dimension_type", "Dimension Type / نوع البعد"),
	("dimension", "Dimension / البعد"),
	("dimension_name_in_arabic", "Dimension Name (Arabic) / اسم البعد بالعربية"),
	("account", "Account / الحساب"),
	("budget", "Budget / الميزانية"),
	("committed", "Committed / الالتزامات"),
	("actual", "Actual / الفعلي"),
	("available", "Available / المتاح"),
	("percent_consumed", "% Consumed / نسبة الاستهلاك"),
]


def build_export(company, fiscal_year, dimension, account=None):
	rows = get_commitment_vs_actual(
		{"company": company, "fiscal_year": fiscal_year, "dimension": dimension, "account": account}
	)
	meta = {
		"generated_at": now_datetime().isoformat(),
		"company": company,
		"fiscal_year": fiscal_year,
		"dimension": dimension,
		"account": account,
		"currency": frappe.get_cached_value("Company", company, "default_currency"),
		"disclaimer": DEMO_DISCLAIMER,
		"source": "ERPNext Budget Commitment vs Actual",
	}
	return meta, rows


def rows_to_csv(rows):
	data = [[header for _key, header in EXPORT_COLUMNS]]
	for row in rows:
		data.append(
			[
				flt(row.get(key), 2)
				if key == "percent_consumed" and row.get(key) is not None
				else row.get(key)
				for key, _header in EXPORT_COLUMNS
			]
		)
	return "\ufeff" + to_csv(data)


def rows_to_json(meta, rows):
	return json.dumps(
		{
			"meta": meta,
			"columns": [{"key": key, "label": header} for key, header in EXPORT_COLUMNS],
			"data": [{key: row.get(key) for key, _header in EXPORT_COLUMNS} for row in rows],
		},
		ensure_ascii=False,
		indent=1,
		default=str,
	)


@frappe.whitelist()
def export_budget_vs_actual(
	company: str, fiscal_year: str, dimension: str, fmt: str = "csv", account: str | None = None
):
	frappe.has_permission("Budget", "read", throw=True)
	frappe.has_permission("Company", "read", doc=company, throw=True)
	fmt = (fmt or "csv").lower()
	if fmt not in ("csv", "json"):
		frappe.throw(_("Format must be csv or json"))

	meta, rows = build_export(company, fiscal_year, dimension, account)
	slug = frappe.scrub(f"{company} {fiscal_year} {dimension}")
	frappe.response["filename"] = f"demo_budget_vs_actual_{slug}.{fmt}"
	frappe.response["filecontent"] = rows_to_csv(rows) if fmt == "csv" else rows_to_json(meta, rows)
	frappe.response["type"] = "download"
