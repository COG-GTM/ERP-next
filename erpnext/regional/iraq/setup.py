# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from erpnext.regional.iraq.utils import make_governorate_territories

PRINT_FORMAT = "Iraq Tax Invoice"
CURRENCY = "IQD"


def setup(company=None, patch=True):
	"""Called by `install_country_fixtures` when a Company with country Iraq is created."""
	make_custom_fields()
	add_print_formats()
	enable_currency()
	make_governorate_territories()


def make_custom_fields(update=True):
	tax_id_label = "Unified Tax Number / الرقم الضريبي الموحد"
	company_tax_id_label = "Company Unified Tax Number / الرقم الضريبي الموحد للشركة"

	invoice_item_fields = [
		dict(
			fieldname="tax_rate",
			label="Tax Rate",
			fieldtype="Float",
			insert_after="description",
			print_hide=1,
			hidden=1,
			read_only=1,
		),
		dict(
			fieldname="tax_amount",
			label="Tax Amount",
			fieldtype="Currency",
			insert_after="tax_rate",
			print_hide=1,
			hidden=1,
			read_only=1,
			options="currency",
		),
		dict(
			fieldname="total_amount",
			label="Total Amount",
			fieldtype="Currency",
			insert_after="tax_amount",
			print_hide=1,
			hidden=1,
			read_only=1,
			options="currency",
		),
	]

	custom_fields = {
		"Company": [
			dict(
				fieldname="company_name_in_arabic",
				label="Company Name in Arabic / اسم الشركة بالعربية",
				fieldtype="Data",
				insert_after="company_name",
				translatable=0,
			),
			dict(
				fieldname="iraq_tax_id",
				label=tax_id_label,
				fieldtype="Data",
				insert_after="tax_id",
				description="Demo rule: 10 digits, optional IQ prefix (not an official format)",
			),
		],
		"Customer": [
			dict(
				fieldname="customer_name_in_arabic",
				label="Customer Name in Arabic / اسم العميل بالعربية",
				fieldtype="Data",
				insert_after="customer_name",
				translatable=0,
			),
			dict(
				fieldname="iraq_tax_id",
				label=tax_id_label,
				fieldtype="Data",
				insert_after="tax_id",
				description="Demo rule: 10 digits, optional IQ prefix (not an official format)",
			),
		],
		"Supplier": [
			dict(
				fieldname="supplier_name_in_arabic",
				label="Supplier Name in Arabic / اسم المورد بالعربية",
				fieldtype="Data",
				insert_after="supplier_name",
				translatable=0,
			),
			dict(
				fieldname="iraq_tax_id",
				label=tax_id_label,
				fieldtype="Data",
				insert_after="tax_id",
				description="Demo rule: 10 digits, optional IQ prefix (not an official format)",
			),
		],
		"Territory": [
			dict(
				fieldname="territory_name_in_arabic",
				label="Territory Name in Arabic / اسم المنطقة بالعربية",
				fieldtype="Data",
				insert_after="territory_name",
				translatable=0,
			),
		],
		"Sales Invoice": [
			dict(
				fieldname="customer_name_in_arabic",
				label="Customer Name in Arabic / اسم العميل بالعربية",
				fieldtype="Read Only",
				insert_after="customer_name",
				fetch_from="customer.customer_name_in_arabic",
				print_hide=1,
			),
			dict(
				fieldname="iraq_tax_id",
				label=tax_id_label,
				fieldtype="Read Only",
				insert_after="tax_id",
				fetch_from="customer.iraq_tax_id",
				print_hide=1,
			),
			dict(
				fieldname="company_iraq_tax_id",
				label=company_tax_id_label,
				fieldtype="Read Only",
				insert_after="company_tax_id",
				fetch_from="company.iraq_tax_id",
				print_hide=1,
			),
		],
		"Purchase Invoice": [
			dict(
				fieldname="supplier_name_in_arabic",
				label="Supplier Name in Arabic / اسم المورد بالعربية",
				fieldtype="Read Only",
				insert_after="supplier_name",
				fetch_from="supplier.supplier_name_in_arabic",
				print_hide=1,
			),
			dict(
				fieldname="iraq_tax_id",
				label=tax_id_label,
				fieldtype="Read Only",
				insert_after="tax_id",
				fetch_from="supplier.iraq_tax_id",
				print_hide=1,
			),
			dict(
				fieldname="company_iraq_tax_id",
				label=company_tax_id_label,
				fieldtype="Read Only",
				insert_after="company",
				fetch_from="company.iraq_tax_id",
				print_hide=1,
			),
		],
		"Sales Invoice Item": invoice_item_fields,
		"Purchase Invoice Item": invoice_item_fields,
	}

	create_custom_fields(custom_fields, ignore_validate=True, update=update)


def add_print_formats():
	frappe.reload_doc("regional", "print_format", "iraq_tax_invoice")
	frappe.db.set_value("Print Format", PRINT_FORMAT, "disabled", 0)


def enable_currency():
	"""IQD ships with Frappe (geo/country_info.json: Fils, 1000 units, #,###.###) but is disabled by default."""
	if frappe.db.exists("Currency", CURRENCY):
		frappe.db.set_value("Currency", CURRENCY, "enabled", 1)
