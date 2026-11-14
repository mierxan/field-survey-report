# Rolling out the security update (Phase 1)

For the owner. Do the steps in this order. Background and limits:
[ACCOUNT_FILE_SECURITY.md](ACCOUNT_FILE_SECURITY.md).

## 1. On the owner's PC, before building

1. Choose the new owner password. Put its hash into the seed, so a fresh
   Owner install gets it. In the project folder:

       .venv\Scripts\python.exe app_auth.py make-seed

   It asks for the password twice without showing it and rewrites
   `data\json\private\auth_seed.json` (owner only, hash at 600,000).
2. Run `build_installer.bat`. It must print
   `User edition is clean: no account file and none of the … private account value(s)…`.
   If it prints `PRIVATE DATA FOUND` no User Setup file is made.
3. Install the new Owner Setup on the owner's PC. The seed is only used on a
   PC that has no account yet, so sign in with the OLD password once, then
   Account > Change Password: set the new one. Write down the recovery code
   the program shows (Account > Recovery Code shows it again).
   The copy you run from the project folder (START_FSR.bat) has its own
   account file: change the password there the same way.
4. Account > MySQL Settings: after you set the longer `fsr_app` password in
   MySQL, type it here and Save. It is stored in the Windows Credential
   Manager; `db_config.json` keeps `"password": ""`.

## 2. Check on ONE site PC before the others

Before installing, on that PC, copy the folder
`%APPDATA%\FieldSurveyReport` to a safe place (for example a USB stick).
This is what "undo" below puts back.

Install `FieldSurveyReport_User_Setup_<date>.exe` over the existing program.

| # | Do | Expect |
|---|---|---|
| 1 | Start the program | The Sign In window, not "Set Up This PC" and no red message. |
| 2 | Open `%APPDATA%\FieldSurveyReport` | New files `users.before_update_<time>.json` and `users.lastgood.json`. `users.json` contains `"version": 2` and `"signature"`. |
| 3 | Look in `users.json` | The DSG account is gone. Every other account is still there. |
| 4 | A normal site user signs in with their usual password | Works. In `users.json` that account now has `"iterations": 600000`. |
| 5 | Open two saved reports, one of them with a Control # containing DSG if there is one | Both open and print as before. |
| 6 | Sign out. Type a wrong password five times for one account (wait when asked) | "Please wait … seconds" after the 2nd–4th, then "locked for 15 minutes". Another account can still sign in. After 15 minutes the first one can too. |
| 7 | **New site PC only:** the Administrator created in "Set Up This PC" | Was shown the recovery code right after creating the account. A normal user signing in is never shown it. |
| 7a | **Site PC that had the program before:** the Owner signs in with the OLD owner password | Only "Set a New Password" opens (one button, nothing else). A password under 12 characters or the old one again is refused. After a good new password the program opens and the recovery code of that PC is shown once - write it down. Then search `%APPDATA%\FieldSurveyReport` for the first characters of the old hash: no file contains it. |
| 7b | Sign out, sign in as a normal user, Account menu | There is no "Recovery Code" entry. As Owner / Administrator: Account > Recovery Code asks for the password again before showing anything. |
| 8 | Close the program. Open `users.json` in Notepad, change one `"status"` value, save. Start the program | Red message "changed outside the program". A normal user cannot sign in. The Administrator signs in, sees the change listed, clicks "Restore the last good copy", signs in again. |
| 9 | Export Master Data and import it on the owner's PC | Works as before. |
| 10 | Look inside `C:\Program Files\Field Survey Report (User)\_internal\data\json` | Only `edition.json` and `master_list.json`. No `private` folder. |

On a site PC that never had the program: step 1 shows "Set Up This PC"
instead; create the Administrator account, write down the recovery code,
then do steps 6–10.

## 3. The owner's visit to each site PC

The old owner hash stays on a site PC until the Owner has signed in there
once and set the new password (step 7a). It can be done in person or over a
remote-desktop session; the password is typed on that PC and never sent.
Until then nobody else can use the Owner account there either, and the
site's own users keep working normally.

Track it here (one line per site PC):

| Site PC | Update installed (date) | Owner signed in and changed password (date) | Recovery code written down | users.before_update file deleted |
|---|---|---|---|---|
| | | | | |
| | | | | |
| | | | | |

A PC without a date in the third column still holds the 9 November hash.

## 4. Undo the update on that PC

1. Close the program.
2. Uninstall "Field Survey Report (User)" (Windows Settings > Apps) and
   install the earlier Setup file again.
3. Delete everything in `%APPDATA%\FieldSurveyReport` and copy back the
   folder you saved before installing. (Without that copy: delete
   `users.json` and `users.lastgood.json`, then rename
   `users.before_update_<time>.json` to `users.json`.)
4. Start the program: accounts and passwords are as before the update.

The reports in `Documents\Field Survey Report` are not changed by the update
or by the undo. The earlier program cannot read accounts that were re-hashed
by the new one, which is why step 3 puts the old file back. Installing the
new version again later asks an Administrator to review the account file
once ("Accept the changed file").

On the owner's PC an undo also needs the MySQL password typed again in
MySQL Settings (the earlier program does not read the Credential Manager).

If the Owner had already set the new password on that PC (step 7a), the
Owner's hash is blank in `users.before_update_<time>.json`: after an undo
from that file the site's users sign in as before, but the Owner account
cannot sign in on that PC with the earlier program. The safety copy of the
whole folder made before installing still has the old hash - which is the
reason to delete that copy once the update is confirmed.

## 5. After the roll-out: delete by hand

On the owner's PC / project folder:

* `MYSQL_SETUP.txt` (contains the old MySQL password)
* `data\schema\private\set_password.sql` (contains the old MySQL password)
* `Installer\FieldSurveyReport_User_Setup_2026.11.09.exe`,
  `Installer\FieldSurveyReport_Owner_Setup_2026.11.09.exe`, anything in
  `Installer\Archive`, and `Installer.zip` (they contain the old hashes)
* `dist\` and `build\` (the 9 November builds; the next build recreates them)
* `data\json\private\users.before_update_<time>.json` and
  `%APPDATA%\FieldSurveyReport\users.before_update_<time>.json`, once you
  have signed in successfully (they hold the old hashes)
* The unused project-root PyInstaller spec was removed in the approved
  14 November 2026 cleanup. Build with `build_installer.bat`, which writes
  its own edition-specific spec under `build`.

Project cleanup note (14 November 2026): the empty `Installer/Archive`
folder was moved to `D:\FSR_Cleanup_2026-11-14`; no old installer was deleted.
The removal instructions above still apply to old installers kept elsewhere.

On every site PC, once the checks pass:

* the old Setup file, wherever it was copied to
* `%APPDATA%\FieldSurveyReport\users.before_update_<time>.json`
* the safety copy of `%APPDATA%\FieldSurveyReport` made in section 2

Wherever the 9 November User Setup file was sent (email, chat, USB sticks,
shared folders): delete those copies too. Anyone who kept one still has the
old owner hash, which is why the old password must not be used anywhere
again.
