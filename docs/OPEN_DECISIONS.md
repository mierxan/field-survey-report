# Decisions for the owner

Things found during the improvement phases that are yours to decide. None
of them is urgent; nothing was changed for them.

| # | Found | Decision needed | Notes |
|---|---|---|---|
| 1 | Phase 3, 12 Nov 2026 | `data/json/master_list.json` (consignee and supplier names) is tracked in git and is on the pushed `main` branch | The repository is private, so it was left as it is. Options: keep it; or stop tracking it (`git rm --cached`, add it to `.gitignore`), so names stay out of future commits. The names already in the history would stay there unless the history is rewritten. Phase 5 housekeeping. |
| 2 | Phase 3 | Move the store of record to SQLite, with Excel as an export | Proposal and recommendation: [STORAGE_PROPOSAL.md](STORAGE_PROPOSAL.md). |
| 3 | Phase 2 | A version column in the MySQL `reports` table (the stricter guard) | [TWO_COPIES_ONE_DATABASE.md](TWO_COPIES_ONE_DATABASE.md), "Later option". A schema change. |
| 4 | Phase 2 | A second backup location (another drive) | [DATA_SAFETY.md](DATA_SAFETY.md), proposal 4.2. "Not now" so far. |
