# Phase 6.2 — Windows Installer Validation Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Mode:** Read-only inspection. **No rebuild, no install/upgrade/uninstall, no source/schema changes, nothing staged/committed/pushed. Existing installers were not overwritten.**

---

## 1. Existing installer inventory

| Item | Detail |
|---|---|
| `Installer/` | Owner + User setups. Latest: `FieldSurveyReport_Owner_Setup_2026.11.22.043636-60249d…exe` (41.2 MB) and `FieldSurveyReport_User_Setup_2026.11.22.043636-60249d…exe` (37.9 MB), from build `2026.11.22.043636` (files written 05:04–05:07). ~18 prior versioned pairs (2026.11.11 → 2026.11.19). |
| `dist/Owner/FieldSurveyReport/` | PyInstaller onedir (FieldSurveyReport.exe + `_internal/`) |
| `dist/User/FieldSurveyReport/` | PyInstaller onedir |
| `build/` | `edition_Owner/`, `edition_User/`, `work_Owner/`, `work_User/`, `FieldSurveyReport.spec` |
| Build log | `installer_build_20261122.log` — last build **completed successfully** ("Build complete", "Your installers … are in the Installer folder") |

**Result: PASS** — both editions present, versioned, last build succeeded.

## 2. Build configuration

- **PyInstaller** (`build/FieldSurveyReport.spec` = User; Owner uses the DB spec that includes MySQL). Bundles: Excel templates (`First_Page`, `Cargo_Details`, `Containerized_Loading_Form`, `Incident_Report`), `master_list.json`, `edition.json`, `logo.png`/`logo.ico`. Hidden imports: `matplotlib.backends.backend_tkagg`, `win32com.client`, `win32cred`, `win32timezone`, `warehouse*`, `ttkbootstrap`. Excludes `mysql`/`mysql.connector` for the **User** edition only.
- **Inno Setup** (`installer.iss`): per-edition `AppId` (Owner `{6F0C…}`, User `{B3E1…}`), `OutputDir=Installer`, versioned `OutputBaseFilename`, `PrivilegesRequired=admin`, `ArchitecturesInstallIn64BitMode=x64compatible`, `CloseApplications=yes`. Ships `dist\{Edition}\FieldSurveyReport\*`, `GO_BACK_TO_WORKBOOK.bat`, `docs/DELETED_REPORTS.md`, and (Owner) `sql\field_survey_schema.sql` + `sql\migrations\*.sql`. Registers `.fsrhandover` / `.fsrshipment`; `[InstallDelete]` removes `{app}\_internal`.
- **Guard:** `fsr_build_check.py` scans the **User** edition for forbidden files (`auth_seed.json`, `users.json`, `db_config.json`, `settings.json`, `secrets.json`) and any account email/salt/hash, aborting the build if found.

**Result: PASS.**

## 4. Packaged-resource verification (from `dist/` + `installer.iss`)

| Resource | Owner | User |
|---|---|---|
| 4 Excel templates (`.xlsx`) | ✅ | ✅ |
| `master_list.json` | ✅ | ✅ |
| `edition.json` | ✅ (empty) | ✅ `{"edition":"user"}` |
| `logo.ico` / `logo.png` | ✅ | ✅ |
| `auth_seed.json` (owner seed) | ✅ (see §9) | ❌ (clean) |
| `installer_defaults/db_config.json` | ✅ (enabled=false, no password) | — |
| `GO_BACK_TO_WORKBOOK.bat`, `docs/DELETED_REPORTS.md` | ✅ (installer) | ✅ (installer) |
| `sql/` schema + migrations | ✅ (Owner only, installer) | ❌ |
| `users.json` / real `db_config.json` / `*.sqlite3` / `*.log` | ❌ absent | ❌ absent |

**Result: PASS** (all required resources present; no real private files packaged). **NOT TESTED:** packaged-schema *currency* — no `7z`/`innounp` is available to extract the installer, so I could not confirm the embedded `field_survey_schema.sql` includes the Phase 5.6 columns. Timestamp inference only: the 04:36 build postdates the Phase 5.6 schema edit, so it likely includes it.

## 5. Dependency verification

- **Owner:** `libmysql.dll` present (MySQL client) + `mysql-connector` (pure-Python in the PYZ); `python314.dll`; `matplotlib`, `PIL`, `numpy`, `ttkbootstrap`, `pywin32` bundled; `win_amd64` (x64). ✅
- **User:** no `libmysql.dll`; `mysql` excluded. ✅ (correct — no MySQL)
- **Result: PASS.**

## 6. Owner vs User comparison

| Aspect | Owner | User |
|---|---|---|
| MySQL | Yes (`libmysql.dll`) | No |
| Owner seed | Yes (`auth_seed.json`) | No (clean) |
| `edition.json` | empty | `user` |
| AppId | `{6F0C…}` | `{B3E1…}` |
| Excel templates / master_list | Yes | Yes |
| `sql/` schema | Yes | No |
| Install dir | `C:\Program Files\Field Survey Report` | `…\Field Survey Report (User)` |
| Data (kept on update/uninstall) | `Documents\Field Survey Report\`, `%APPDATA%\FieldSurveyReport\` | same |

**Result: PASS.**

## 7. Installation and upgrade risks

- **Not code-signed** → Windows SmartScreen "unknown publisher" (documented). *Low–Medium.*
- `PrivilegesRequired=admin` (with override dialog) → admin needed to install. Expected.
- `CloseApplications=yes` → closes a running instance; unsaved form edits could be lost (drafts autosave). *Low.*
- `[InstallDelete] {app}\_internal` → removes only within the install dir; user data is elsewhere. *Low.*
- Upgrade uses the same `AppId` → in-place update; `Documents`/`AppData`/`Databases` preserved. *Low.*
- **Fresh install / upgrade / uninstall: NOT TESTED** — would modify the registry/Start menu of your working PC; requires a disposable VM (not available). No destructive install was performed.

## 8. Uninstall and data-preservation assessment

- Inno Setup uninstaller removes `{app}`; `[Registry]` uses `uninsdeletevalue` for file associations.
- Per `installer.iss` comments (and the 14 Nov scratch-install test noted there), data in `Documents\Field Survey Report\`, `%APPDATA%\FieldSurveyReport\` (users, settings, MySQL settings, log) and the reports database is **outside `{app}` and preserved** on uninstall/upgrade.
- **Result: PASS (by inspection) / NOT TESTED (no uninstall executed).**

## 9. Security findings

- **S1 (Medium) — Owner installer embeds the owner's real identity and password hash.** `dist/Owner/.../data/json/private/auth_seed.json` contains `first_name/last_name/email` and a PBKDF2 `salt`+`hash` (600,000 iterations). Anyone with the Owner setup can read the owner's email and attempt offline password cracking. This is by design (Owner first-run sign-in) but should be treated as sensitive; consider whether real PII/hash belongs in a distributable, and protect the Owner installer accordingly. The **User** edition is clean (fsr_build_check enforces this). 
- **S2 (Low–Medium) — Not code-signed** → authenticity not verifiable; SmartScreen warning.
- **S3 (PASS)** — `installer_defaults/db_config.json` is `enabled:false` with no password; no `users.json`, real `db_config.json`, `*.sqlite3`, or logs are packaged.
- **S4 (PASS)** — no secrets in the packaged User edition; no credentials in the repo installer config.

## 10. Outstanding defects

- **D1 (Medium)** — Owner installer ships owner PII + password hash (S1).
- **D2 (Low)** — Not code-signed.
- **D3 (Low)** — Packaged-schema currency not verified by extraction (no tool); recommend rebuilding after the Phase 5.6 fix and extracting/verifying, or trusting the 04:36 build timestamp.
- **D4 (Low)** — No automated install/upgrade/uninstall smoke test; no CI installer build.

## 11. Overall release-readiness assessment

The installer is **buildable and reproducible** (PyInstaller 6.22.3 + Inno Setup 6 present, scripted via `build_installer.bat`, last build succeeded), packages **all required runtime resources** with the correct **Owner (Excel+MySQL) / User (Excel-only)** split, and is **data-preserving** on upgrade/uninstall by design. No packaging defects were found.

However, this review did **not** rebuild, install, or extract (to avoid overwriting installers and modifying the system), and the Owner installer contains owner credentials.

**Overall: READY WITH CONDITIONS** — conditions before release:
1. Rebuild after the Phase 5.6 schema fix and verify the packaged `field_survey_schema.sql` contains `packing_list_no`/`origin_line` (extract or rebuild).
2. Decide on the Owner-installer credential exposure (S1) — accept with handling instructions, or change the seeding approach.
4. Code-sign the installers for production (removes SmartScreen warning).
5. Perform a clean install → launch → upgrade → uninstall test in a disposable Windows VM.

---

**STOP — report complete.** No files were rebuilt, installed, or modified; nothing staged/committed/pushed.