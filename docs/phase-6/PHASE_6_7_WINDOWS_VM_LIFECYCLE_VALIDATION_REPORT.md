# Phase 6.7 — Windows VM Lifecycle Validation Report

**Project:** Field Survey Report (FSR)
**Validation installers:** `D:\Build Build Build\fsr_validate_6_6\Installer\`
**Mode:** Pre-test inspection only. **No installation on the working PC, no MySQL connection, no SQL, no untrusted utilities installed, no source/config/installer changes.**

**Overall status: BLOCKED** — installer hashes verified, but **embedded-content extraction** and **all VM lifecycle tests** are blocked (no extraction utility, no VM infrastructure). Per the phase rules, I did not substitute testing on the working PC.

---

## 1. Installer hash verification — **PASS**
| Installer | SHA-256 | Matches Phase 6.6 |
|---|---|---|
| `FieldSurveyReport_Owner_Setup_2026.11.22.183121-1f7573e105bc487e88d9ef144fe85419.exe` | `3BD4CBC84053EC6CAB8FF0B9F65EE064387E38FB5D9412C715CFCAF39964EB51` | ✅ |
| `FieldSurveyReport_User_Setup_2026.11.22.183121-1f7573e105bc487e88d9ef144fe85419.exe` | `A33C2C46CB088AF3D4A9F86A7876FBBCEE85E647635E2850BE80FA1CC3CB28B3` | ✅ |

Only the `fsr_validate_6_6\Installer\` installers were inspected; the original project's `Installer/` was **not** used.

## 2. Actual installer extraction — **BLOCKED**
- Checked for `7z`, `innounp`, `lessmsi`, `msiextract` → **none installed**.
- No other trusted Inno Setup extractor is available. The phase forbids installing untrusted utilities and forbids inferring package contents from installer scripts.
- **Embedded-content verification (auth_seed absence, packaged SQL, resources inside the `.exe`) is BLOCKED** pending a trusted extraction tool (`7-Zip` or `innounp`).

## 3. Packaged SQL verification — **BLOCKED**
- Depends on §2 extraction. Cannot inspect the embedded `{app}\sql\field_survey_schema.sql` without extracting the installer.
- (Source-level evidence from Phase 6.6 remains: `installer.iss` ships the schema + migrations 001–004 to `{app}\sql` Owner-only, and the source schema contains `packing_list_no`/`origin_line` — but this is **not** a substitute for inspecting the actual package, per the phase rules.)

## 4. Owner clean installation — **BLOCKED**
- No VM infrastructure: `vmrun` (VMware), `VBoxManage` (VirtualBox), `qemu-system-x86_64`, `vmconnect` all absent; Hyper-V feature query requires elevation.
- Installation on the working PC is forbidden. **BLOCKED** pending a disposable Windows VM.

## 5. User clean installation — **BLOCKED**
- Same as §4 (no VM). **BLOCKED.**

## 6. First-launch authentication — **BLOCKED**
- Requires §4/§5 (installed app in a VM). **BLOCKED.**

## 7. Essential resource tests — **BLOCKED**
- Requires §4/§5. **BLOCKED.**

## 8. Upgrade testing — **BLOCKED**
- Requires a disposable VM (absent). Also, the phase restricts validation to `fsr_validate_6_6\Installer\`; a legitimate previous-version installer would come from the original `Installer/`, which is outside the authorized set — so even with a VM, the upgrade baseline needs owner clarification. **BLOCKED.**

## 9. Uninstallation testing — **BLOCKED**
- Requires §4/§5 in a disposable VM. **BLOCKED.**

## 10. Data-preservation verification — **BLOCKED**
- Depends on §8/§9. **BLOCKED.**

## 11. Security and operational checks — **NOT TESTED**
- No installation occurred, so no runtime security/operational checks were possible. No MySQL connection, no SQL, no elevation, no network/DB access by the agent.

## 12. Screenshots / logs
- None (no VM/install). Hash evidence in §1.

## 13. Outstanding defects and release blockers
- **No trusted extraction utility** (`7z`/`innounp`) → cannot verify actual embedded contents (`auth_seed.json` absence inside the `.exe`, packaged `{app}\sql` schema, resources).
- **No VM infrastructure** (VMware/VirtualBox/QEMU/Hyper-V CLI) → cannot perform clean install, first-launch auth, upgrade, uninstall, or data-preservation tests.
- Prior open items remain: not code-signed; clean VM lifecycle untested; coverage baseline / other Phase 5 items.

## Category status
| Category | Status |
|---|---|
| 1. Installer hash verification | **PASS** |
| 2. Actual package extraction | **BLOCKED** (no extraction utility) |
| 3. Packaged SQL verification | **BLOCKED** (depends on §2) |
| 4. Owner clean install | **BLOCKED** (no VM) |
| 5. User clean install | **BLOCKED** (no VM) |
5. First-launch authentication | **BLOCKED** (no VM) |
| 7. Essential resources | **BLOCKED** (no VM) |
| 8. Upgrade | **BLOCKED** (no VM; baseline scope) |
| 9. Uninstallation | **BLOCKED** (no VM) |
| 10. Data preservation | **BLOCKED** (no VM) |
| 11. Security/operational | **NOT TESTED** |

## What is needed to unblock
1. **Trusted extraction:** install **7-Zip** or **innounp** (owner-approved) so the `.exe` contents can be inspected (auth_seed absence, packaged SQL, resources).
5. **Disposable Windows 10/11 VM** (Hyper-V/VMware/VirtualBox) with snapshots for Owner install, User install, upgrade, and uninstall — **not** the working PC.
6. Owner confirmation of a legitimate previous-version installer if upgrade testing is required.

---

**STOP — Phase 6.7 BLOCKED.** Installer hashes verified; extraction and VM lifecycle testing blocked by missing tooling/infrastructure. No installation, MySQL access, SQL, or file changes were performed. Awaiting owner provision of an extraction utility and disposable VM(s).