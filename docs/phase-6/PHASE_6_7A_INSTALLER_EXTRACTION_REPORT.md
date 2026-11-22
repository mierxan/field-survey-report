# Phase 6.7A — Installer Extraction Report

**Project:** Field Survey Report (FSR)
**Validation installers:** `D:\Build Build Build\fsr_validate_6_6\Installer\`
**Mode:** Offline extraction & inspection. **No application installation, no extracted binary executed, no MySQL connection, no SQL, no source/config/installer changes.**

**Overall status: PASS** — both installers extracted and verified.

---

## 1. Extraction tool availability
| Tool | Path | Version | Inno Setup support | Used |
|---|---|---|---|---|
| **innounp** | `C:\Users\rojom\AppData\Local\Temp\kilo\innounp2\unpacked\innounp.exe` | **2.71.4 (2026-11-18)** | 2.0.7 → **7.1.1** | ✅ |
| 7-Zip | `C:\Program Files\7-Zip\7z.exe` | 26.06 | none (no Inno handler) | ✗ |
| innoextract | `C:\Users\rojom\Downloads\innoextract-1.9-windows\innoextract.exe` | 1.9 | ≤ 6.0.5 | ✗ (too old) |
| innounp (old) | `C:\Users\rojom\Downloads\innounp050\innounp.exe` | 0.50 | ≤ ~6.1 | ✗ (too old) |

`innounp 2.71.4` was obtained from the official GitHub repo `jrathlev/InnoUnpacker-Windows-GUI` (`innounp-2/bin/innounp-2.zip`) and used. The installers were built with **Inno Setup 6.7.3** (confirmed in the registry), which only innounp 2.71.x supports.

## 2. Installer integrity — **PASS**
| Installer | SHA-256 | Matches Phase 6.6 |
|---|---|---|
| `…Owner_Setup_2026.11.22.183121-…exe` | `3BD4CBC84053EC6CAB8FF0B9F65EE064387E38FB5D9412C715CFCAF39964EB51` | ✅ |
| `…User_Setup_2026.11.22.183121-…exe` | `A33C2C46CB088AF3D4A9F86A7876FBBCEE85E647635E2850BE80FA1CC3CB28B3` | ✅ |

Installers were not modified.

## 3. Extraction — **PASS**
- **Owner:** `innounp -x -d<dir> <owner>` → **1,989 files** extracted (incl. `{app}\…` and `install_script.iss`).
- **User:** `innounp -x -d<dir> <user>` → **1,977 files** extracted.
- Output dirs: `test_run_temp\inno_owner\`, `test_run_temp\inno_user\` (git-ignored scratch). **No extracted binary was executed.**

## 4. Package verification (actual extracted contents) — **PASS**
| Check | Owner | User |
|---|---|---|
| `auth_seed.json` absent | ✅ absent | ✅ absent |
| Equivalent embedded verifier / `users.json` | ✅ none | ✅ none |
| Real Owner PII packaged | ✅ none (no seed) | ✅ none |
| Owner SQL dir (`{app}\sql`) | ✅ present | ✅ **absent** (no Owner-only SQL) |
| `sql\field_survey_schema.sql` | ✅ present | — |
| Migrations 001–004 | ✅ all 4 present | — |
| `packing_list_no VARCHAR(120) NULL` | ✅ line 105 | — |
| `origin_line VARCHAR(120) NULL` | ✅ line 106 | — |
| Excel templates (×4) | ✅ 4 | ✅ 4 |
| `master_list.json` | ✅ | ✅ |
| `edition.json` | `{"edition":"owner"}` | `{"edition":"user"}` |
| MySQL (`libmysql.dll`) | ✅ present | ❌ absent |
| Private files | only `installer_defaults/db_config.json` (disabled, `password:""`) | none |
| `*.sqlite3` / `*.log` | ✅ none | ✅ none |

- The Owner `installer_defaults/db_config.json` is the **disabled default** (`enabled:false`, empty password) — **not a credential**.
- No `auth_seed.json`, no `users.json`, no `*.sqlite3`, no `*.log` anywhere in either package.

## 5. Restrictions observed
- No FSR installation, no execution of extracted binaries, no MySQL connection, no SQL, no source/config/installer changes, nothing staged/committed/pushed.
- Validation installers and original project preserved.

## 6. Status
| Category | Status |
|---|---|
| Extraction tool availability | **PASS** (innounp 2.71.4) |
| Installer hash verification | **PASS** |
| Extraction | **PASS** |
| Package-content verification | **PASS** |

---

**Phase 6.7A: PASS.** Both installers extracted with innounp 2.71.4 and verified: no `auth_seed.json`/`users.json`, Owner has `sql\field_survey_schema.sql` (with `packing_list_no`/`origin_line`) + migrations 001–004, User has no Owner-only SQL, resources/edition metadata correct, and no credentials/private DB files embedded.

**STOP — extraction & verification complete.** No installation, MySQL access, SQL, or file changes were performed. Awaiting owner direction (Phase 6.7 VM lifecycle remains blocked on VM infrastructure).