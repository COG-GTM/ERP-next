# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from erpnext.accounts.public_finance.budget_control import get_commitment_vs_actual


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_commitment_vs_actual(filters)
	return get_columns(filters), data, None, get_chart(filters, data)


def get_columns(filters):
	dimension = filters.dimension or "Ministry"
	return [
		{
			"fieldname": "dimension",
			"label": _(dimension),
			"fieldtype": "Link",
			"options": dimension,
			"width": 260,
		},
		{
			"fieldname": "dimension_name_in_arabic",
			"label": _("Name (Arabic)"),
			"fieldtype": "Data",
			"width": 220,
		},
		{
			"fieldname": "account",
			"label": _("Account"),
			"fieldtype": "Link",
			"options": "Account",
			"width": 220,
		},
		{
			"fieldname": "budget",
			"label": _("Budget"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"fieldname": "committed",
			"label": _("Committed"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"fieldname": "actual",
			"label": _("Actual"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"fieldname": "available",
			"label": _("Available"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{"fieldname": "percent_consumed", "label": _("% Consumed"), "fieldtype": "Percent", "width": 120},
	]


def get_chart(filters, data):
	if not data:
		return None
	labels = [row.dimension for row in data]
	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Budget"), "values": [row.budget for row in data]},
				{"name": _("Committed"), "values": [row.committed for row in data]},
				{"name": _("Actual"), "values": [row.actual for row in data]},
			],
		},
		"type": "bar",
		"fieldtype": "Currency",
		"options": "currency",
	}
