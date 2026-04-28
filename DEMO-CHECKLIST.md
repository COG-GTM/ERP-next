# DEMO-CHECKLIST

Internal checklist for running a live Devin demonstration against this repo. Use this as the
run sheet for the presenter; everything else lives in the fork of the Frappe ERPNext README.

---

## Pre-demo setup

**Branches to have locally (all pushed to origin):**
- `develop` — clean baseline.
- `demo/ap-aging-bug` — primary path. Off-by-one planted in
  `erpnext/accounts/report/accounts_receivable/accounts_receivable.py::get_ageing_data()`.
  Do NOT reveal the bug location to the Devin session.
- `demo/po-threshold-task` — backup path. Same code as `develop`; no pre-work beyond the
  branch itself.

**Environment state before the room walks in:**
- Browser tab 1: DeepWiki view for `COG-GTM/ERP-next` (expand architecture map + GL-posting
  call graph).
- Browser tab 2: Ask Devin, repo scoped to `COG-GTM/ERP-next`, pre-test answered at least
  once this morning to warm the cache.
- Browser tab 3: a fresh Devin session, authenticated, repo access confirmed.
- Terminal / screen share window positioned. Notifications muted.
- Backup recording downloaded locally (do not rely on streaming).

---

## Beat 1 — DeepWiki (~3 min)

Open the DeepWiki view. Show:

- Top-level modules: `accounts`, `buying`, `manufacturing`, `stock`, `selling`, `assets`.
- Source / call graph for the GL posting flow:
  `JournalEntry.make_gl_entries()` → `general_ledger.save_entries()` → `make_entry()` →
  `GL Entry` creation.
- Module dependency visualization.

Land the line:
> "This is what happens on day one when we point Devin at your codebase. What takes a new
> engineer six weeks of ramp-up, Devin gives you in twenty minutes."

---

## Beat 2 — Ask Devin (~3 min)

Prompt (copy/paste exactly):

> How does the general ledger posting workflow work? Trace it from a journal entry being
> created through to the financial statements. Show me the code paths.

Expected citations:
- `erpnext/accounts/doctype/journal_entry/journal_entry.py` — `JournalEntry` class,
  `make_gl_entries` method (around line 1205).
- `erpnext/accounts/general_ledger.py` — `make_gl_entries`, `save_entries`, `make_entry`
  (lines 28, 407, 425).
- `erpnext/accounts/report/financial_statements.py` — `get_accounting_entries`,
  `calculate_values`.

If Ask Devin returns something different, don't fight it live — narrate the code paths from
the tabs you already have up.

---

## Beat 3 — Devin Session (~7 min)

Pick ONE option before the demo starts. Do not switch mid-demo.

### Option C (primary) — AP-aging bug on `demo/ap-aging-bug`

Point Devin at `COG-GTM/ERP-next`, branch `demo/ap-aging-bug`. Give it this prompt:

> Users are reporting that the AP-aging report shows incorrect totals for the >90-day bucket.
> Reproduce the bug, identify the root cause, fix it, and add a regression test.

What you should see Devin do:
1. Read `accounts_receivable.py`, identify `get_ageing_data()`.
2. Notice the strict `<` comparison and explain how invoices at exactly 30 / 60 / 90 / 120
   days fall into the next bucket.
3. Flip the comparison back to `<=`.
4. Add a regression test asserting that an invoice aged exactly 90 days lands in the 60–90
   bucket, not the 90–120 bucket.
5. Run the test, show green.
6. Open a PR with a clean description.

### Option A (backup) — PO spending threshold on `demo/po-threshold-task`

Use only if Option C stalls. Point Devin at branch `demo/po-threshold-task`. Prompt:

> Add a validation rule to the purchase-order approval workflow that enforces a per-department
> spending threshold. If the PO total exceeds the department's threshold, block submission and
> surface a clear error to the user. Add unit tests covering the threshold-met,
> threshold-just-over, and threshold-exempt cases. Update the relevant docstrings.

Files Devin will touch:
- `erpnext/buying/doctype/purchase_order/purchase_order.py` (add validation in `validate()`)
- `erpnext/buying/doctype/purchase_order/test_purchase_order.py` (add tests)

---

## Fallbacks

**If the live Devin session stalls, errors, or gets stuck on dependency install:**
- Pause it. Don't troubleshoot live.
- Switch the screen share to the backup recording. Narrate over it the same way you would
  have narrated the live session. The audience cares about the outcome, not which
  electrons moved.
- If the recording is also unavailable, switch branches to `demo/po-threshold-task` and run
  Option A — it's a clean branch so Devin won't inherit any mid-session state.

**If DeepWiki hasn't indexed the repo when you open the tab:**
- Skip to Beat 2 (Ask Devin) and come back to DeepWiki at the end if time allows. Don't wait
  on indexing live.

**If Ask Devin returns sparse or wrong citations:**
- Narrate the GL-posting flow from an already-open editor tab pointed at
  `general_ledger.py`. Hit line 28, 59, 407, 425 — that's the tour.

---

## Post-demo cleanup

After the room clears:

1. Close / decline any PRs Devin opened during the live session (don't merge into `develop`).
2. Leave `demo/ap-aging-bug` and `demo/po-threshold-task` in place for the next rehearsal.
3. If a merge happened by accident, revert on `develop` immediately — the off-by-one bug must
   not ship.
4. Log which option was run, which fallback (if any) was used, and anything that surprised
   you, in the prep directory's `Demo-After-Action.md`.

---

## File references for the presenter

- Bugged function: `erpnext/accounts/report/accounts_receivable/accounts_receivable.py`
  around line 905 (`get_ageing_data` method).
- Clean branch for PO workflow: `demo/po-threshold-task` at `erpnext/buying/doctype/purchase_order/`.
- GL posting files for narration: `erpnext/accounts/doctype/journal_entry/journal_entry.py`,
  `erpnext/accounts/general_ledger.py`, `erpnext/accounts/report/financial_statements.py`.
