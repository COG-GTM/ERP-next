// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Demo Wallet Settings", {
	refresh(frm) {
		frm.set_intro(
			__(
				"DEMO mock gateway: saving registers the Payment Gateway 'Demo Wallet' and its Payment Gateway Account."
			),
			"orange"
		);
		if (frm.doc.enabled) {
			frm.add_custom_button(__("Issue Demo Token"), () => {
				frappe.call({
					method: "erpnext.erpnext_integrations.doctype.demo_wallet_settings.demo_wallet_settings.get_demo_credentials",
					callback(r) {
						if (!r.message) return;
						frappe.msgprint({
							title: __("DEMO bearer token"),
							indicator: "orange",
							message: `<pre style="white-space:pre-wrap">${frappe.utils.escape_html(
								JSON.stringify(r.message, null, 2)
							)}</pre>`,
						});
					},
				});
			});
		}
	},
});
