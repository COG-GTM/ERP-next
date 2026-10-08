// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Demo Wallet Transaction", {
	refresh(frm) {
		if (frm.doc.hosted_page_url && ["Created", "Pending"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Open Hosted Page (DEMO)"), () => {
				window.open(frm.doc.hosted_page_url, "_blank");
			});
		}
		if (frm.doc.status === "Paid") {
			frm.add_custom_button(__("Refund (DEMO)"), () => {
				frappe.prompt(
					[
						{
							fieldname: "amount",
							fieldtype: "Currency",
							label: __("Refund Amount"),
							default: frm.doc.amount,
							options: frm.doc.currency,
							reqd: 1,
						},
						{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason") },
					],
					(values) => {
						frappe.call({
							method: "erpnext.erpnext_integrations.doctype.demo_wallet_transaction.demo_wallet_transaction.refund_from_desk",
							args: { payment_id: frm.doc.name, amount: values.amount, reason: values.reason },
							callback: () => frm.reload_doc(),
						});
					},
					__("DEMO refund"),
					__("Refund")
				);
			});
		}
	},
});
