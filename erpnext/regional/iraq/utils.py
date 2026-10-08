# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import json
import os
import re

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.controllers.taxes_and_totals import get_itemised_tax

# DEMO ASSUMPTION - NOT AN OFFICIAL SPECIFICATION.
# Iraq's General Commission for Taxes introduced e-registration and a unified tax number, but no public
# format specification was available to us. For this demo the number is validated as exactly 10 digits,
# optionally prefixed with "IQ" (e.g. "IQ1234567890" or "1234567890"). Change this constant once the
# official format is published.
IRAQ_TAX_ID_PATTERN = re.compile(r"^(IQ)?\d{10}$")
IRAQ_TAX_ID_EXAMPLE = "IQ1234567890"

IRAQ_TAX_ID_FIELDS = {
	"Customer": ["iraq_tax_id"],
	"Supplier": ["iraq_tax_id"],
	"Company": ["iraq_tax_id"],
	"Sales Invoice": ["iraq_tax_id", "company_iraq_tax_id"],
	"Purchase Invoice": ["iraq_tax_id", "company_iraq_tax_id"],
}


def is_valid_iraq_tax_id(value) -> bool:
	"""Return True when `value` matches the (demo) unified tax number pattern."""
	if not value:
		return False
	return bool(IRAQ_TAX_ID_PATTERN.match(str(value).strip().upper()))


def validate_iraq_tax_id(value, fieldlabel=None, throw=True) -> bool:
	"""Validate a unified tax number. Empty values are allowed (the field is optional).

	Raises a bilingual (EN / AR) ValidationError when `throw` is True and the value is malformed.
	"""
	if not value:
		return True

	if is_valid_iraq_tax_id(value):
		return True

	if throw:
		label = fieldlabel or _("Unified Tax Number")
		frappe.throw(
			_(
				"{0} '{1}' is not a valid Unified Tax Number. Expected 10 digits, optionally prefixed with IQ (example: {2})."
			).format(label, frappe.bold(value), IRAQ_TAX_ID_EXAMPLE)
			+ "<br>"
			+ "الرقم الضريبي الموحد '{}' غير صالح. المطلوب 10 أرقام، مع بادئة IQ اختيارية (مثال: {}).".format(
				value, IRAQ_TAX_ID_EXAMPLE
			),
			title=_("Invalid Unified Tax Number / الرقم الضريبي الموحد غير صالح"),
		)

	return False


def validate_party_tax_id(doc, method=None):
	"""Validate the `iraq_tax_id` custom field on Customer / Supplier / Company.

	Intended to be wired as a `doc_events` validate hook by the integrator (this module only
	registers `regional_overrides`). Also reused by `validate_regional` for invoices.
	"""
	for fieldname in IRAQ_TAX_ID_FIELDS.get(doc.doctype, []):
		if not doc.meta.has_field(fieldname):
			continue
		validate_iraq_tax_id(doc.get(fieldname), fieldlabel=_(doc.meta.get_label(fieldname)))


def validate_regional(doc):
	"""Regional override of `erpnext.controllers.accounts_controller.validate_regional`.

	Runs for transactions of companies whose country is Iraq (see hooks.regional_overrides).
	"""
	if doc.doctype not in ("Sales Invoice", "Purchase Invoice"):
		return

	validate_party_tax_id(doc)


def update_itemised_tax_data(doc):
	"""Regional override of `erpnext.controllers.taxes_and_totals.update_itemised_tax_data`.

	Writes the item-wise tax rate, tax amount and total onto each item row so the Iraq Tax Invoice
	print format can show tax per line. Iraq has no VAT (only sales taxes on specific goods and
	services), so there is no zero-rated / export handling here.
	"""
	if not doc.items:
		return

	meta = frappe.get_meta(doc.items[0].doctype)
	if not meta.has_field("tax_rate"):
		return

	itemised_tax = get_itemised_tax(doc)

	for row in doc.items:
		tax_rate, tax_amount = 0.0, 0.0
		item_code = row.item_code or row.item_name
		for tax in (itemised_tax.get(item_code) or {}).values():
			tax_rate += flt(tax.get("tax_rate", 0))
			tax_amount += flt(tax.get("tax_amount", 0))

		row.tax_rate = flt(tax_rate, row.precision("tax_rate"))
		row.tax_amount = flt(tax_amount, row.precision("tax_amount"))
		row.total_amount = flt(row.net_amount + row.tax_amount, row.precision("total_amount"))


def get_governorates() -> list[dict]:
	"""Return the 18 Iraqi governorates (EN name + AR name) from governorates.json."""
	path = os.path.join(os.path.dirname(__file__), "governorates.json")
	with open(path, encoding="utf-8") as f:
		return json.load(f)


def get_root_territory() -> str:
	"""Return the root Territory, creating `All Territories` when the site has none yet."""
	root = _("All Territories")
	if frappe.db.exists("Territory", root):
		return root

	existing = frappe.db.get_value(
		"Territory", {"parent_territory": ("is", "not set"), "is_group": 1}, "name"
	)
	if existing:
		return existing

	territory = frappe.new_doc("Territory")
	territory.territory_name = root
	territory.is_group = 1
	territory.insert(ignore_permissions=True)
	return territory.name


def make_governorate_territories(parent=None) -> list[str]:
	"""Idempotently create one Territory per Iraqi governorate under `All Territories`.

	Requires the `territory_name_in_arabic` custom field (created by setup.make_custom_fields).
	Returns the list of territory names.
	"""
	parent = parent or get_root_territory()

	has_arabic_field = frappe.get_meta("Territory").has_field("territory_name_in_arabic")
	names = []
	for row in get_governorates():
		name = row["territory_name"]
		if frappe.db.exists("Territory", name):
			if has_arabic_field and not frappe.db.get_value("Territory", name, "territory_name_in_arabic"):
				frappe.db.set_value(
					"Territory", name, "territory_name_in_arabic", row["territory_name_in_arabic"]
				)
		else:
			territory = frappe.new_doc("Territory")
			territory.territory_name = name
			territory.parent_territory = parent
			territory.is_group = 0
			if has_arabic_field:
				territory.territory_name_in_arabic = row["territory_name_in_arabic"]
			territory.insert(ignore_permissions=True)
		names.append(name)

	return names
