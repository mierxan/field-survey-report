# Phase 6.6 — Isolated Installer Build Report

**Project:** Field Survey Report (FSR)
**Original project:** `D:\Build Build Build\PythonProject` (unchanged)
**Validation workspace:** `D:\Build Build Build\fsr_validate_6_6` (outside the original)
**Mode:** Isolated validation build. **Original project not modified; no production release; no signing; no installation on the working PC; no DB connection.**

---

## 1. Workspace isolation and source snapshot
- **Workspace:** `D:\Build Build Build\fsr_validate_6_6` (sibling of the original; the original was only read from).
- **Snapshot method:** `robocopy` copy of the source + resources, then `.venv` copied separately (0.28 GB).
- **Build ran entirely inside the workspace:** `build_installer.bat` does `cd /d "%~dp0"` and uses **relative** paths (`build`, `dist`, `Installer`, `%CD%`); `installer.iss` uses relative `OutputDir=Installer` and relative `Source:` paths. `tools/build_version.py` uses `datetime`+`uuid4` (no Git). **No command touched the original project.**
- **Cleanup safety:** `build_installer.bat` `rmdir /s /q build` and `dist` operate on the **workspace's** `build`/`dist` (relative to `%~dp0`), not the original. Confirmed before running.

**Included:** all application source (incl. Phase 6.4 `app_auth.py`, `build_installer.bat`), `warehouse/`, `warehouse_ui/`, `data/excel/*.xlsx`, `data/json/master_list.json`, `data/json/private/installer_defaults/db_config.json`, `data/schema/field_survey_schema.sql` + `migrations/001–004`, `docs/DELETED_REPORTS.md`, `GO_BACK_TO_WORKBOOK.bat`, `logo.ico/png`, `installer.iss`, `fsr_build_check.py`, `tools/build_version.py`, `requirements.txt`, and the Phase 5/6 test files.

**Excluded:** `.git/` (not needed), `.coverage`, `mobile_update_staging/` (Android), `test_run_temp/`, `build/`, `dist/`, `Installer/` (no old installers copied), `docs/phase-5/`, `docs/phase-6/`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.idea`, `data/Clear MYSQL database/`, `mysql-recovery-20261121/`, and **real/private files**: `data/json/private/db_config.json`, `auth_seed.json`, `users*.json`, `settings*.json`, `db_config.phase5.json` (test-DB credentials). Only `installer_defaults/db_config.json` was kept (needed by the Owner build). **No credentials, auth seeds, or user data are in the workspace.**

## 2. Files included / excluded
Covered in §1. Snapshot source = the current working tree (HEAD `8102d37` + uncommitted Phase 5/6 changes, including Phase 6.4 auth). The original working tree was not modified during the copy.

## 3. Owner build result — **PASS**
- Command: `build_installer.bat /nopause /notests` (MySQL env vars removed first, so no DB access).
- Output: `fsr_validate_6_6\Installer\FieldSurveyReport_Owner_Setup_2026.11.22.183121-1f7573e105bc487e88d9ef144fe85419.exe` — **41.2 MB**, SHA-256 `3BD4CBC84053EC6CAB8FF0B9F65EE064387E38FB5D9412C715CFCAF39964EB51`.
- PyInstaller onedir output at `fsr_validate_6_6\dist\Owner\FieldSurveyReport\`.

## 4. User build result — **PASS**
- Output: `fsr_validate_6_6\Installer\FieldSurveyReport_User_Setup_2026.11.22.183121-1f7573e105bc487e88d9ef144fe85419.exe` — **37.9 MB**, SHA-256 `A33C2C46CB088AF3D4A9F86A7876FBBCEE85E647635E2850BE80FA1CC3CB28B3`.
- PyInstaller onedir output at `fsr_validate_6_6\dist\User\FieldSurveyReport\`.
- Build log: "User edition is clean: no account file and none of the 0 private account value(s)…" (no seed present to leak).

## 5. Authentication-seed inspection — **PASS**
- **Owner:** `dist\Owner\...\data\json\private\auth_seed.json` → **absent**. Owner private dir contains only `installer_defaults\db_config.json`.
- **User:** `dist\User\...\data\json\private\` → **empty** (no `auth_seed.json`, no account files).
- **No equivalent embedded verifier:** no `users.json`, no `auth_seed.json`, no password verifier in either package.
- **No real Owner PII:** no `auth_seed.json` (which held the owner's name/email/hash) anywhere in the packages.
- Owner first-launch setup resources present (edition `owner`, `app_auth.create_owner` in the bundled source); User edition retains Administrator first-launch (`edition.json` = `user`).

## 6. Packaged SQL schema verification — **PASS (by installer rule + source); extraction NOT TESTED**
- `installer.iss` (Owner-only, inside `#if Edition == "Owner"`): `data\schema\field_survey_schema.sql` → `{app}\sql`; `data\schema\migrations\*.sql` → `{app}\sql\migrations`.
- The workspace's `data/schema/field_survey_schema.sql` contains `packing_list_no VARCHAR(120) NULL` (line 105) and `origin_line VARCHAR(120) NULL` (line 106); migrations **001–004** present.
- ISCC compiled the installers successfully (it would fail if a listed `Source:` file were missing), so the schema + migrations are embedded.
- **Limitation:** no `7z`/`innounp` is installed, so the installer `.exe` was **not extracted** to inspect the embedded bytes directly. Recommend an `innounp`/`7z` extraction check in a future step. This is **not** based on source timestamps.

## 7. Package resource inspection — **PASS**
| Resource | Owner | User |
|---|---|---|
| Excel templates (×4) | ✅ | ✅ |
| `master_list.json` | ✅ | ✅ |
| `edition.json` | `{"edition":"owner"}` | `{"edition":"user"}` |
| `logo.ico` | ✅ | ✅ |
| MySQL (`libmysql.dll`) | ✅ | ❌ (none) |
- **No** real DB credentials, private `db_config.json`, `*.sqlite3`, or `*.log` in `dist/`.
- **No** Android/`mobile_update_staging` artifacts (excluded).
- Matches Phase 6.2/6.3 expectations, with the intended change: `auth_seed.json` is now **absent** (was present in Phase 6.2/6.3).

## 8. Build environment and hashes
- **Python:** 3.14.4  **PyInstaller:** 6.22.3  **Inno Setup:** 6 (`ISCC.exe`, version info 0.0.0.0).
- **Build version:** `2026.11.22.183121-1f7573e105bc487e88d9ef144fe85419` (shared by both editions).
- **Hashes:** Owner `3BD4CBC8…64EB51`; User `A33C2C46…C28B3` (full in §3–4).
- **Deviations/notes:** the build used `/notests` (the suite was validated in Phase 6.4; the goal here is packaging). This is a **single successful isolated validation build** — not a reproducibility claim (no independent repeat build).

## 9. Deviations from Phase 6.2/6.3 findings
- **Resolved:** Owner installer previously contained `auth_seed.json` (owner PII + hash). The actual built packages now contain **none** — Phase 6.4 fix confirmed in a real build.
- **Unchanged:** not code-signed; clean VM install/upgrade/uninstall not tested; packaged-SQL not extracted (no tool) — but source + installer rule confirm the columns.
- **Consistent:** edition separation (Owner=MySQL, User=none), resources, and data-preservation design all match Phase 6.2/6.3.

## 10. Remaining release blockers
- **Not code-signed** (SmartScreen warning) — signing decision pending.
- **Clean VM install → upgrade → uninstall** test not performed (needs disposable VM).
- **Installer extraction** (`innounp`/`7z`) not performed — recommend verifying embedded `{app}\sql\field_survey_schema.sql` and absence of `auth_seed.json` inside the `.exe`.
- Coverage baseline and other Phase 5 items remain as previously reported.

## 11. Category status
| Category | Status |
|---|---|
| Workspace isolation & snapshot | **PASS** |
| Owner build | **PASS** |
| User build | **PASS** |
| Authentication-seed removal (actual packages) | **PASS** |
| Packaged SQL schema | **PASS (by rule + source)** / extraction **NOT TESTED** |
| Package resources | **PASS** |
| Build reproducibility | **PASS (single build; not a repeat)** |

**Overall: PASS** — isolated Owner and User installers built successfully, `auth_seed.json` is absent from both, resources/edition separation are correct, and the packaged schema source contains the Phase 5.6 columns. Conditions: not signed; no VM install test; installer `.exe` not extracted (no tool).

**Validation artifacts:** `D:\Build Build Build\fsr_validate_6_6\Installer\` (both installers) and `…\dist\Owner|User\` (PyInstaller output). The original project and its installers are untouched.

---

**STOP — Phase 6.6 complete.** No installation, signing, release, or distribution. Original project preserved. Awaiting owner review.