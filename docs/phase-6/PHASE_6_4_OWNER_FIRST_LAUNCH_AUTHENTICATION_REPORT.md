# Phase 6.4 — Owner First-Launch Authentication Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Status:** **PASS** (authentication change implemented and tested) — with a **working-tree discrepancy** noted in §7.

The Owner edition no longer ships `auth_seed.json` (owner PII + PBKDF2 hash). On first launch the Owner creates the Owner account and password. No authentication logic beyond this focused change was touched; account recovery (users.json signing / recovery code) is unchanged.

---

## 1. Files inspected and modified

**Modified by me (Phase 6.4):**
| File | Change |
|---|---|
| `app_auth.py` | `import fsr_edition`; new `create_owner()` (role="owner"); `setup_page` now edition-aware (Owner → `create_owner`, User → `create_administrator`); docstring/comment updated |
| `build_installer.bat` | Owner `--add-data` no longer packages `auth_seed.json`; added Owner-edition guard that aborts the build if `auth_seed.json` is present |
| `tests/test_first_setup.py` | Rewrote the seed-packaging test (`test_installer_script_never_ships_the_seed`); added `test_owner_edition_first_run_creates_the_owner` and `test_create_owner_checks_the_account_like_a_sign_up` |
| `tests/test_login_gui.py` | Pinned the two Administrator-setup GUI tests to the User edition; added `test_fresh_owner_install_shows_the_owner_setup` |

**Inspected (read-only):** `fsr_edition.py`, `tests/test_auth_seed_cli.py`, `tests/test_auth_hashing.py`, `fsr_build_check.py`, `installer.iss`, `build/FieldSurveyReport.spec`.

**⚠️ NOT made by me — present in the working tree (preserved, not committed):** `warehouse/store.py`, `warehouse_ui/components.py`, `tests/test_warehouse_refresh.py` (new), `fsr_deletions.py`, `tests/test_deletions.py`, `tests/test_deletions_gui.py`, `docs/DELETED_REPORTS.md`, `fsr_open_dialog.py`. These form a separate "warehouse refresh / stale-read protection" feature. See §7.

## 2. Authentication flow — before vs after

**Before:** the Owner installer packaged `auth_seed.json` (owner name, email, salt, PBKDF2 hash). On first start `UserStore._open()` → `ensure_owner()` created the Owner account from the seed; the Owner signed in immediately with the pre-set password. (User edition: no seed → first account is the Administrator.)

**After:**
- **Owner edition:** no seed is packaged (`ensure_owner()` is a no-op without a seed file). On first launch `needs_setup` is true → the setup page shows **"Set Up This PC" / "Create Owner Account"** → `store.create_owner(...)` validates name/email/password(≥12)/confirm/initials and creates a **role="owner", status="approved"** account with a fresh PBKDF2 hash (`ITERATIONS = 600_000`). The recovery code is shown once; then Sign In.
- **User edition:** unchanged — first account is the Administrator (`create_administrator`).
- Existing installs (users.json already has an owner) are unaffected; the site-PC "old owner must set a new password" flow is untouched.

## 3. Security assessment
- **No owner PII or password hash is shipped** in either edition. ✅
- **No default/hardcoded/predictable password** — the Owner sets their own (≥12 chars, confirmation required). ✅
- **PBKDF2 unchanged** (`hash_password`, 600k iterations, per-account salt). ✅
- **Incomplete setup cannot bypass auth:** `create_owner` requires `needs_setup` and validates all fields before writing; `_mark_set_up()` records setup (fsr_secrets) so a deleted users.json does not re-offer setup. ✅
- **Repeated initialization prevented:** second `create_owner`/`create_administrator` raises "already has an account". ✅
- **Login/authorization preserved:** Owner role and its protections intact; Admin (User edition) unchanged. ✅

## 4. Tests executed and exact results
| Suite | Command | Result |
|---|---|---|
| Focused auth (offline) | `pytest tests/test_first_setup.py tests/test_auth_seed_cli.py tests/test_auth_hashing.py tests/test_auth_signature.py tests/test_auth_throttle.py tests/test_auth_update.py tests/test_auth_owner_on_site.py -q` | **128 passed, 0 failed, 0 skipped** (149 s) |
| GUI login (interactive) | `pytest tests/test_login_gui.py tests/test_user_edition_gui.py -q` | **13 passed, 0 failed, 0 skipped** (27 s) |
| Offline regression | `pytest -m "not gui" -q -rs` (env vars removed) | **1144 passed, 33 skipped (real-MySQL, env removed), 319 GUI deselected, 0 failed** (9:25) |
| Ruff | `ruff check app_auth.py tests/test_first_setup.py tests/test_login_gui.py` | **All checks passed!** |

The 33 skips are the real-MySQL tests (env vars removed so no DB connection). No real-MySQL tests were run.

## 5. Owner/User edition packaging verification
- `build_installer.bat` Owner `EXTRA` now: `--collect-submodules mysql.connector --add-data …installer_defaults\db_config.json…` — **no `auth_seed.json`**.
- Added Owner guard: `if /i "%ED%"=="Owner" if exist "dist\Owner\...\_internal\data\json\private\auth_seed.json" exit /b 1`.
- User edition unchanged (`fsr_build_check.py` still forbids `auth_seed.json`/`users.json`/`db_config.json`/etc.).
- **Result: neither edition ships `auth_seed.json` or an embedded password verifier.** ✅

## 6. Remaining risks and limitations
- **No rebuild was performed** (per restrictions). The next `build_installer.bat` run will produce installers with the new first-launch flow; verify the Owner installer contains no `auth_seed.json`.
- The development seed `data/json/private/auth_seed.json` still exists locally (git-ignored) for `make_seed`/dev use; it is **not** packaged.
- Existing owner accounts (users.json) and the "old owner on a site PC" flow are untouched.
- `test_login_gui.py` Administrator-setup tests are now explicitly User-edition; the Owner setup path is covered by the new `test_fresh_owner_install_shows_the_owner_setup`.

## 7. ⚠️ Working-tree discrepancy (not mine)
During this phase the working tree gained a **separate feature I did not author**:
- `warehouse/store.py` (+`active_reports()` filtering deleted controls), `warehouse_ui/components.py` (`DataService.revision` stale-read guard), new `tests/test_warehouse_refresh.py`, and refinements to `fsr_deletions.py` (+`active_deleted_controls`?), `tests/test_deletions*.py`, `docs/DELETED_REPORTS.md`, `fsr_open_dialog.py`.
- These were **not** made or modified by me. I preserved them untouched. The offline regression (1144 passed) ran **with them present** and was green, so the combined tree is consistent.
- **Action:** these belong to a different change group and should be reviewed/committed **separately** by their author. Do not bundle them with the Phase 6.4 auth commit.

**My Phase 6.4 changes are exactly:** `app_auth.py`, `build_installer.bat`, `tests/test_first_setup.py`, `tests/test_login_gui.py`.

## 8. Status
**PASS** — the Owner first-launch authentication change is implemented, secure, and tested (128 auth + 13 GUI + 1144 offline regression, Ruff clean). No broader auth redesign, DB migration, or account-recovery change was required.

---

**STOP — Phase 6.4 complete.** No commit, no push, no rebuild, no production/DB/Excel changes. Awaiting your review (and separate handling of the unexpected warehouse/deletions changes).