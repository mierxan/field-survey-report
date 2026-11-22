# Phase 6.5 — Changeset Audit Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`  **HEAD:** `8102d372db1ec82fe060044c1c2de84a61a72bec`
**Mode:** Read-only audit. **No source/test/schema/config/doc modified, nothing staged/committed/pushed, no DB connection, no rebuild.**

---

## 1. Working-tree inventory

- `git diff --cached --stat` → **empty** (nothing staged).
- `git diff --stat` → **17 files changed, 399 insertions(+), 102 deletions(-)**.
- Untracked (non-ignored): `.coverage`, `data/schema/fsr_phase5_isolated_test_schema.sql`, `data/schema/fsr_phase5_phase5_7_item_lines_migration.sql`, `docs/phase-5/` (21 files), `docs/phase-6/` (5 files), `mobile_update_staging/` (11 files), `tests/test_phase5_harness.py`, `tests/test_schema_completeness.py`, `tests/test_warehouse_refresh.py`.
- Recent commits (unchanged): `8102d37` (CI) ← `8fa92f9` (delete/restore) ← `b684a1a` … — **no new commits; no history rewrite.**

**Key point:** the working tree contains **three distinct bodies of work** (Phase 6.4 auth = mine; a parallel warehouse-refresh/deletions feature; an Android mobile update) plus pre-existing Phase 5/6 changes. They are **not** all from Phase 6.4.

## 2. File-by-file classification

### A. Phase 6.4 authentication (authored by Kilo this phase)
| File | Git | Tracked | Change | Origin evidence |
|---|---|---|---|---|
| `app_auth.py` | M | yes | `create_owner()`; edition-aware `setup_page`; docstring/seed comment | `docs/phase-6/PHASE_6_4_…` |
| `build_installer.bat` | M | yes | no `auth_seed.json` packaging; Owner guard | same |
| `tests/test_first_setup.py` | M | yes | `create_owner` tests; seed-packaging test rewrite | same |
| `tests/test_login_gui.py` | M | yes | Owner-setup GUI test; User-edition pins | same |

Dependencies: `app_auth.py` now imports `fsr_edition` (pre-existing module, unchanged). No other file depends on these.

### B. Warehouse refresh / stale-read + deletions refinements (NOT authored by Kilo)
| File | Git | Tracked | Change |
|---|---|---|---|
| `warehouse/store.py` | M | yes (committed 8fa92f9? no — pre-existing tracked) | `active_reports()` filters deleted controls in `load_reports`/`load_snapshot` |
| `warehouse_ui/components.py` | M | yes | `DataService.revision` stale-read guard |
| `tests/test_warehouse_refresh.py` | ?? | **untracked** | stale-read protection test |
| `fsr_deletions.py` | M | yes (committed 8fa92f9) | `active_deleted_controls()` |
| `tests/test_deletions.py` | M | yes (committed 8fa92f9) | +35 lines |
| `tests/test_deletions_gui.py` | M | yes (committed 8fa92f9) | +36 lines |
| `docs/DELETED_REPORTS.md` | M | yes (committed 8fa92f9) | +5 lines (visibility doc) |
| `fsr_open_dialog.py` | M | yes (committed 8fa92f9) | `refresh_live_views()` after delete/restore |

Provenance: **not Kilo's.** These files were **absent from the Phase 6.3 working tree** and appeared during Phase 6.4. The deletions files were committed in `8fa92f9` and are now **further modified** (post-commit, not by Kilo). Origin = owner/parallel development; exact author/time not established from Git history. Dependencies: `warehouse/store.py` → `fsr_deletions.active_deleted_controls`; `fsr_open_dialog.py` → `DataService.invalidate`; `test_warehouse_refresh.py` → both.

### C. Pre-existing Phase 5/6 changes (authored by Kilo in earlier phases)
| File | Git | Tracked | Origin |
|---|---|---|---|
| `data/schema/field_survey_schema.sql` | M | yes | Phase 5.6 (+2 shipment columns) |
| `data/schema/field_survey_test_schema.sql` | M | yes | Phase 5.6 (regenerated) |
| `fsr_test_db_script.py` | M | yes | Phase 5.2/5.6 (`build_for`/`build_isolated`) |
| `tests/real_mysql.py` | M | yes | Phase 5.2 (fail-closed harness) |
| `tests/test_db_mysql_real.py` | M | yes | Phase 5.2 (`NAME_PREFIX`) |
| `tests/test_real_mysql.py` | M | yes | Phase 5.2 (DB name) |
| `data/schema/fsr_phase5_isolated_test_schema.sql` | ?? | no | Phase 5.6 (generated) |
| `data/schema/fsr_phase5_phase5_7_item_lines_migration.sql` | ?? | no | Phase 5.7 (migration) |
| `tests/test_phase5_harness.py` | ?? | no | Phase 5.2 (offline tests) |
| `tests/test_schema_completeness.py` | ?? | no | Phase 5.6 (tests) |
| `docs/phase-5/` (21 files) | ?? | no | Phase 5.x reports (Kilo) |
| `docs/phase-6/` (5 files) | ?? | no | Phase 6.x reports (Kilo) |
| `.coverage` | ?? | no | coverage data (stray; not Kilo-authored content) |

Dependencies: `fsr_test_db_script.py` ↔ `data/schema/*`; `tests/real_mysql.py` ↔ `tests/test_real_mysql*.py`, `tests/test_db_mysql_real.py`.

### D. Other / unidentified
| Item | Git | Tracked | Assessment |
|---|---|---|---|
| `mobile_update_staging/` (11 files) | ?? | **untracked** | Android (Kotlin) app update **1.14.0 "Recoverable deletion"** — `DeletedReportEntity.kt`, `DeletionTest.kt`, `ReportDao.kt`, `AppDatabase.kt` (DB v4), `ReportRepository.kt`, `update_sources.py`, `CHANGELOG.md`, `build.gradle.kts`, `Installation_Guide.md`. **Not Kilo's**; provenance owner/parallel; it is the mobile counterpart of the deletions feature but is a **separate Android project**, not part of the Windows tree. |

## 3. Authentication implementation review (Phase 6.4 diff)
- ✅ **Owner setup creates `role="owner"`** — `create_owner()` → `_add_account(role="owner", status="approved")`; `needs_setup` gate.
- ✅ **User edition Administrator setup unchanged** — `setup_page` uses `create_administrator` when `fsr_edition.IS_OWNER_EDITION` is False; text/button identical to before for User.
- ✅ **`auth_seed.json` no longer packaged** — removed from `build_installer.bat` Owner `EXTRA`; Owner guard aborts if `_internal/data/json/private/auth_seed.json` exists; User edition still guarded by `fsr_build_check.py`.
- ✅ **No other packaged owner PII/verifier** — `installer_defaults/db_config.json` (no PII, disabled), `edition.json` (no PII); repo `data/json/private/auth_seed.json` is git-ignored and not packaged.
- ✅ **Existing auth/recovery compatible** — users.json HMAC signing, recovery code, `new_password_page` (site-PC old owner) untouched; `create_owner` uses the same `_add_account`/PBKDF2 path.
- ✅ **No silent bypass** — `create_owner` requires `needs_setup`, validates name/email/≥12/confirm/initials, and `_mark_set_up()` records setup (fsr_secrets) so a deleted users.json does not re-offer setup.
- ✅ **No unintended authz changes** — roles/`is_admin`/status rules unchanged; only `create_owner` added and `setup_page` made edition-aware.
- **No passwords/hashes/PII printed** in this review.

**Category A verdict: PASS.**

## 4. Warehouse feature review (Category B, independent)
- **Intended behavior:** deleted reports (and their lines/quantities) are excluded from Dashboard, Receiving, Withdrawal, Warehouse Monitoring, Analytics, and exports until restoration completes; Delete/Restore refresh live views.
- **Data consistency / stale-read protection:** `warehouse/store.py:active_reports()` filters controls in `fsr_deletions.active_deleted_controls()` (archive `state != 'restored'`); applied in `load_reports` (Excel + MySQL) and `load_snapshot`. `warehouse_ui/components.py:DataService` adds a `revision` counter; a background read that started before an `invalidate()` discards its stale snapshot and re-requests — so a slow read cannot repopulate deleted reports.
- **Threading/UI safety:** revision guard + re-request pattern; covered by `tests/test_warehouse_refresh.py` (in-flight snapshot discarded; final snapshot = post-delete).
- **Interaction with deletions:** `fsr_open_dialog.py:refresh_live_views()` calls `shell.service.invalidate()` after delete and after Deleted History actions; `fsr_deletions.active_deleted_controls()` is the shared predicate.
- **Test coverage:** `test_warehouse_refresh.py` (stale-read) + `test_deletions*.py` additions (visibility). Runs green in the Phase 6.4 offline regression.
- **Potential regressions (low):** `active_reports()` opens the archive SQLite on each `load_reports`/`load_snapshot` (fast early-return when no archive exists; minor cost when it does). If a restore failed to set `state='restored'`, a report could stay hidden — but restore sets that state. No data-loss risk; filtering is read-only.
- **Not modified by Kilo.**

**Category B verdict: PASS WITH CONDITIONS** — sound and tested, but it is a **separate change group** that must be reviewed/committed by its author, not bundled with the Phase 6.4 auth change.

## 5. Unidentified changes / unresolved provenance
- **`mobile_update_staging/`** — Android app update (Kotlin), untracked, not Kilo's, provenance owner/parallel. It is a separate deliverable (mobile), not part of the Windows build; it should be committed to its own repository/branch, not this one.
- **`.coverage`** — stray coverage data file (untracked, git-ignored? no — not in `.gitignore`). Should be removed or git-ignored; not part of any change group.
- No other unidentified files.

## 7. Test evidence comparison
| Run | Scope | Passed | Failed | Skipped | Notes |
|---|---|---|---|---|---|
| Phase 6.1 (baseline) | full suite, env removed | 1,460 | 0 | 33 | 86.5% coverage; 33 = real-MySQL (env removed) |
| Phase 6.4 | focused auth (offline) | 128 | 0 | 0 | `test_first_setup`, `test_auth_*` |
| Phase 6.4 | GUI login | 13 | 0 | 0 | `test_login_gui`, `test_user_edition_gui` |
| Phase 6.4 | non-GUI regression | 1,144 | 0 | 33 | 319 GUI **deselected** (non-GUI run) |

**Explanation of the counts:** the Phase 6.4 regression was **non-GUI only** (`-m "not gui"` → 319 GUI deselected), so its "passed" (1,144) is not directly comparable to Phase 6.1's full-suite 1,460. I reran the **13 auth-relevant GUI tests** separately (all passed); the other GUI tests are unrelated to the auth change and were not rerun (per "do not rerun expensive full regression unless a discrepancy requires it"). The **33 skips** in both runs are the real-MySQL tests (env vars removed so no DB connection). **No failures or errors in any run.** No MySQL was contacted.

## 8. Release risks
- **Mixed working tree:** three unrelated bodies of work (auth, warehouse/deletions, Android) are uncommitted together. Committing with `git add -A` would combine them — **do not**. Commit each group separately.
- **Phase 6.4 auth is not yet packaged/verified in an installer** (no rebuild) — build + verify the Owner installer contains no `auth_seed.json` and the first-launch Owner setup works.
- **Warehouse/deletions feature** is untested by Kilo beyond the offline suite; needs its author's review + a manual GUI pass.
- **Android `mobile_update_staging/`** is a separate project; ensure it is not committed to this Windows repo.
- **`.coverage`** stray file should be git-ignored or removed.

## 9. Recommended next actions
1. Commit **Category A** (auth) alone: `app_auth.py`, `build_installer.bat`, `tests/test_first_setup.py`, `tests/test_login_gui.py`.
2. Separately review/commit **Category B** (warehouse/deletions) by its author; run a manual GUI pass for delete→dashboard-hide→restore.
9. Handle `mobile_update_staging/` in its own Android repository/branch; do not commit here.
4. Add `.coverage` to `.gitignore` (or delete it).
5. Rebuild the installer (approved) and verify the Owner first-launch flow + absence of `auth_seed.json`.

## Category verdicts
| Category | Verdict |
|---|---|
| A — Phase 6.4 authentication | **PASS** |
| B — Warehouse refresh / deletions | **PASS WITH CONDITIONS** (separate change group; author review/commit) |
| C — Pre-existing Phase 5/6 | **PASS** |
| D — `mobile_update_staging/` (Android) | **BLOCKED** (separate project; provenance owner; not for this repo) |
| Overall changeset | **PASS WITH CONDITIONS** — Kilo's auth work is clean and tested; the tree also holds separate uncommitted work that must be committed by its owners, not combined |

---

**STOP — audit complete.** No files modified, staged, committed, or pushed; no DB connection; no rebuild. Awaiting owner review.