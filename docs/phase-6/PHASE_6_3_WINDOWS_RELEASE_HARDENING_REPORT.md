# Phase 6.3 — Windows Release Hardening Report

**Project:** Field Survey Report (FSR)
**Branch:** `improvements/excel-dashboard`
**Mode:** Investigation + recommendations. **No authentication logic changed, no rebuild/install performed, no existing installer overwritten, no secret/hash printed, nothing staged/committed/pushed.**

---

## 1. Authentication-seed investigation

- **`auth_seed.json`** (`data/json/private/auth_seed.json`, 327 bytes, git-ignored) is the **owner account seed**: `first_name`, `middle_name`, `last_name`, `initials`, `email`, a `salt`, and a PBKDF2 `hash` (600,000 iterations). *(Values intentionally not reproduced here.)*
- **Creation:** `app_auth.py` (`write_auth_seed`, ~lines 1777–1828) writes the owner's names + the **hash** of a password; a CLI (`tests/test_auth_seed_cli.py`) and `tests/test_first_setup.py`/`test_auth_hashing.py` cover it. The seed is **not** in source control.
- **Consumption:** on first launch the app seeds the owner account from `auth_seed.json` so the owner can sign in immediately (`app_auth.py:73-78`).
- **Why it is packaged:** `build_installer.bat:138` adds `--add-data data/json/private/auth_seed.json;data/json/private` **only for the Owner edition**. The **User** edition excludes it and is checked by `fsr_build_check.py` (no account/hash). So the **Owner installer bakes the owner's real identity + password hash** to pre-seed the owner account on the owner's PC.
- **Risk:** anyone with the Owner setup can read the owner's email and attempt **offline cracking** of the PBKDF2 hash. By design for the owner's PC, but sensitive if the Owner installer is ever shared.

### Alternatives evaluated
| Option | Assessment |
|---|---|
| **A. Create owner account during installation** | Inno Setup cannot easily run the bundled Python to hash/seed; brittle. Not recommended. |
| **B. Create owner account on first launch** | **Recommended.** Ship no `auth_seed.json`; on first launch the owner sets a password (reuse the existing first-run account flow the User edition already uses, pre-filled with owner name). No hash is ever packaged. |
| **C. Secure first-run init requiring the owner to set a password** | Same as B; the safest. |

### Recommendation: **Option B/C**
Remove `auth_seed.json` from the Owner package (drop the `--add-data …auth_seed.json…` from `build_installer.bat:138`) and make the **first launch require the owner to establish a password** (extend the existing first-run flow; pre-fill owner name/initials, require a new password). This eliminates the shipped hash while keeping the owner's name.

**Impact if implemented:** owner first launch gains one "set password" step; no shipped hash; `app_auth.py` first-run tests (`test_first_setup.py`, `test_auth_seed_cli.py`, `test_auth_hashing.py`) would need updating. **This changes authentication behavior — per the stop condition, I have NOT modified it; I present the recommendation for approval.**

## 2. Security recommendations

- **S1 (High/Med)** — Owner installer embeds owner PII + PBKDF2 hash → implement Option B/C (§1). Until then, treat the Owner setup as sensitive.
- **S2 (Low–Med)** — Installers are **not code-signed** → see §6.
- **S3 (PASS)** — User edition is clean (no account/hash); `fsr_build_check.py` enforces it.
- **S4 (PASS)** — No real `db_config.json`/`users.json`/`*.sqlite3`/logs packaged; `installer_defaults/db_config.json` is `enabled:false` with no password; archive (`*.sqlite3`) is git-ignored.

## 3. Canonical schema verification

- **Source is current:** `data/schema/field_survey_schema.sql:105-106` defines `packing_list_no VARCHAR(120) NULL` and `origin_line VARCHAR(120) NULL`. ✅
- **Installer includes it:** `installer.iss:68-69` ships `data/schema/field_survey_schema.sql` and `data/schema/migrations/*.sql` (001–004) to Owner `{app}\sql`. ✅
- **Packaged SQL (existing installer):** **NOT TESTED** — no `7z`/`innounp` is available to extract the installer, and per instruction I do **not** assume the 04:36 build contains the fix from its timestamp. A rebuild (which packages the current source) + extraction is required to confirm.

## 4. Installer packaging findings

- **Owner:** 4 Excel templates, `master_list.json`, `edition.json` (owner), logos, `auth_seed.json` (S1), `installer_defaults/db_config.json` (disabled), MySQL (`libmysql.dll` + `mysql-connector`), and (via installer) `sql/` schema+migrations. ✅
- **User:** 4 Excel templates, `master_list.json`, `edition.json` (user), logos; **no** `auth_seed.json`, **no** MySQL. ✅
- `fsr_build_check.py` guards the User edition; no real private files packaged. ✅
- **Result: PASS** (packaging correct) / **NOT TESTED** (packaged-schema currency, §3).

## 5. Rebuild procedure (isolated; does not overwrite existing installers)

- `build_installer.bat` **deletes `build/` and `dist/`** (lines 87–88) but **not `Installer/`** — new builds get a new timestamp-based filename, so **existing installers are preserved**. ✅
- Procedure (run on the build PC, Inno Setup 6 + PyInstaller present):
  ```
  build_installer.bat /nopause            # both editions
  build_installer.bat /nopause /owner     # Owner only
  build_installer.bat /nopause /user      # User only
  ```
  It installs deps, runs the full test suite (`pytest -q -rs --fail-on-gui-skip`; real-MySQL tests skip without env vars — acceptable), builds PyInstaller per edition, runs `fsr_build_check.py` on the User edition, then Inno Setup → new `Installer/*_<version>.exe`.
- For full isolation, copy the project to a temp directory and build there.
- **I did NOT rebuild** (to keep this review read-only and avoid deleting `dist/`); procedure documented. **Result: PASS (procedure/tooling) / NOT TESTED (no rebuild by me).**

## 6. Code-signing assessment

- **Inno Setup supports Authenticode** via `SignTool=` (in `[Setup]`) + `Sign=` (per `[Files]`/`[Run]`) + `SignUninstaller`. Currently **none** → unsigned.
- **Sign:** `FieldSurveyReport.exe` (both editions) and the two `Setup_*.exe`; optionally the uninstaller.
- **Timestamping:** SignTool `/tr <timestamp-url> /td sha256` (e.g., DigiCert/Sectigo timestamp server).
- **Certificate:** OV code-signing (~$100–400/yr) or **EV** (~$300–600/yr + hardware token) — EV clears SmartScreen immediately; OV builds reputation over time.
- **Operational:** obtain a cert from a CA (DigiCert, Sectigo, SSL.com, etc.), store in a hardware token/HSM or the Windows certificate store, set `SignTool=` in `installer.iss` (or sign in CI). **No certificate purchased or signed here.** **Result: NOT TESTED (assessment provided).**

## 7. Disposable VM testing plan

Use a Windows 10/11 VM (Hyper-V/VMware/VirtualBox), snapshot before, **never** the working PC.

1. **Clean Owner install:** run Owner Setup → launch → first-run auth (owner) → confirm 4 Excel templates present and forms open → MySQL Settings present but **disabled** (no connection) → create/save a report → export.
4. **Clean User install:** run User Setup → launch → "Set Up This PC" → create Administrator → confirm Excel templates → export master data.
5. **Upgrade preserving data:** install an older build, create a report, install the newer build over it → confirm `Documents\Field Survey Report\`, `%APPDATA%\FieldSurveyReport\`, and the reports DB are preserved.
6. **Uninstall preserving data:** uninstall → confirm `{app}` removed but Documents/AppData/DB remain.
- **Result: NOT TESTED (plan provided; requires a VM).**

## 8. Outstanding defects

| ID | Severity | Defect |
|---|---|---|
| D1 | High/Med | Owner installer ships owner PII + password hash (S1) — needs auth-behavior change (approval required) |
| D2 | Low–Med | Installers not code-signed (S2) |
| D3 | Low | Packaged-schema currency unverified (rebuild + extract) |
| D4 | Low | Install/upgrade/uninstall not executed (VM test pending) |

## 9. Release-readiness assessment

The installer is **functionally sound, buildable, correctly split (Owner=Excel+MySQL, User=Excel-only), and data-preserving** on upgrade/uninstall by design; the User edition is free of credentials. However, three items remain before a production release: (1) the **Owner-installer credential exposure** (requires an authentication-behavior change — presented for approval, not applied), (2) **code-signing**, and (3) a **clean VM install/upgrade/uninstall test** plus a rebuild that packages the corrected schema.

**Overall: READY WITH CONDITIONS** (not a clean PASS — D1 requires an approved auth change, and D2–D4 are open).

---

**STOP — report complete.** No authentication logic, source, schema, or installer was modified; nothing rebuilt/installed/signed; nothing staged/committed/pushed. Awaiting owner approval before implementing the authentication-seed change (Option B/C).