// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Demo Wallet Reconciliation"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "status",
			label: __("Reconciliation Status"),
			fieldtype: "Select",
			options: ["", "Matched", "Missing Payment Entry", "Amount Mismatch", "Refunded", "Not Paid"],
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "reconciliation_status" && data) {
			const colors = {
				Matched: "green",
				"Missing Payment Entry": "red",
				"Amount Mismatch": "orange",
				Refunded: "blue",
				"Not Paid": "gray",
			};
			value = `<span class="indicator-pill ${colors[data.reconciliation_status] || "gray"}">${__(
				data.reconciliation_status
			)}</span>`;
		}
		return value;
	},
};
