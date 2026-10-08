frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Budget Consumption by Ministry"] = {
	method: "erpnext.accounts.dashboard_chart_source.budget_consumption_by_ministry.budget_consumption_by_ministry.get",
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
	],
};
