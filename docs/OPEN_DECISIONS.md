# Decisions for the owner

Things found during the improvement phases that are yours to decide. None
of them is urgent; nothing was changed for them.

| # | Found | Decision needed | Notes |
|---|---|---|---|
| 1 | Phase 3, 12 Nov 2026 | `data/json/master_list.json` (consignee and supplier names) is tracked in git and is on the pushed `main` branch | The repository is private, so it was left as it is. Options: keep it; or stop tracking it (`git rm --cached`, add it to `.gitignore`), so names stay out of future commits. The names already in the history would stay there unless the history is rewritten. Phase 5 housekeeping. |
| 2 | Phase 3 | Move the store of record to SQLite, with Excel as an export | Proposal and recommendation: [STORAGE_PROPOSAL.md](STORAGE_PROPOSAL.md). |
| 3 | Phase 2 | A version column in the MySQL `reports` table (the stricter guard) | [TWO_COPIES_ONE_DATABASE.md](TWO_COPIES_ONE_DATABASE.md), "Later option". A schema change. |
| 4 | Phase 2 | A second backup location (another drive) | [DATA_SAFETY.md](DATA_SAFETY.md), proposal 4.2. "Not now" so far. |

## The broad exception handlers that return a fallback value (Phase 4)

Left as they are, by decision of 13 November 2026. Each catches
`Exception` and carries on with a fallback instead of logging; narrowing
or logging them is a later tidy-up. (The 12 that passed silently were
dealt with in Phase 4.)

| Where | Function | What it does instead |
|---|---|---|
| db_mysql.py | check_connection (2) | returns "not connected" with the reason |
| db_mysql.py | sync_reports | adds the error to the list it returns |
| field_survey_report.py | refresh_mysql_numbers | forgets MySQL's Control #s |
| field_survey_report.py | free_number_for_new_report | keeps the number on the form |
| field_survey_report.py | refresh_mysql_waiting | shows 0 waiting |
| field_survey_report.py | waiting_conflicts | shows no conflicts |
| field_survey_report.py | build_window | dark theme not available: the light one |
| field_survey_report.py | build_window | the MySQL password stays in the file (this one does log) |
| field_survey_report.py | title_prefix | not "real database" in the title |
| field_survey_report.py | MySQL Settings > Test | shows the error text |
| field_survey_report.py | mysql_round_done | 0 left waiting |
| field_survey_report.py | closing window (show) | 0 being sent |
| field_survey_report.py | status check (worker) | "not working" with the error text |
| fsr_forms.py | convert_form_to_pdf (2) | tries the next way to make the PDF |
| fsr_import.py | import_master_data | PO lists rebuilt at the next save or start |
| fsr_mysql_guard.py | save_many | the report's error in the result |
| fsr_renumber.py | renumber_report | the PO lists' error in the result |
| fsr_save_journal.py | _send_only | no standing "replace" decision |
| warehouse_ui/theme.py | is_dark, register_day_theme | the light theme |
