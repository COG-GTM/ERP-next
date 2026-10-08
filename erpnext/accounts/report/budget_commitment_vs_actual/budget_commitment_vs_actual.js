// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Budget Commitment vs Actual"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today()),
			reqd: 1,
		},
		{
			fieldname: "dimension",
			label: __("Dimension"),
			fieldtype: "Select",
			options: ["Ministry", "Governorate", "Cost Center", "Project"],
			default: "Ministry",
			reqd: 1,
		},
		{
			fieldname: "account",
			label: __("Account"),
			fieldtype: "Link",
			options: "Account",
			get_query: function () {
				const company = frappe.query_report.get_filter_value("company");
				return { filters: { company: company, is_group: 0, root_type: "Expense" } };
			},
		},
	],

	onload: function (report) {
		const download = (fmt) => {
			const filters = report.get_values();
			if (!filters.company || !filters.fiscal_year || !filters.dimension) {
				frappe.msgprint(__("Please set Company, Fiscal Year and Dimension first"));
				return;
			}
			open_url_post("/api/method/erpnext.accounts.public_finance.open_data.export_budget_vs_actual", {
				company: filters.company,
				fiscal_year: filters.fiscal_year,
				dimension: filters.dimension,
				account: filters.account || "",
				fmt: fmt,
			});
		};
		report.page.add_inner_button(__("Download CSV"), () => download("csv"), __("Open Data"));
		report.page.add_inner_button(__("Download JSON"), () => download("json"), __("Open Data"));
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "available" && data.available < 0) {
			value = `<span style="color: var(--red-500)">${value}</span>`;
		}
		if (data && column.fieldname === "percent_consumed" && data.percent_consumed > 100) {
			value = `<span style="color: var(--red-500); font-weight: bold">${value}</span>`;
		}
		return value;
	},
};
