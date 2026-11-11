# Accounts, sign in and the account file

How sign in is protected since the November 2026 security update, what it
does not protect against, and how to recover when something goes wrong.
Code: `app_auth.py`, `fsr_secrets.py`, `db_mysql.py`, `fsr_build_check.py`.

## Where things are kept

| What | Where | Notes |
|---|---|---|
| Accounts | `users.json` | Installed program: `%APPDATA%\FieldSurveyReport\`. Run from source: `data\json\private\`. |
| Last good copy | `users.lastgood.json`, same folder | The account file exactly as the program last saved it. |
| File from before the update | `users.before_update_<time>.json`, same folder | Made once, when an earlier `users.json` is first opened. Holds the old password hashes: delete it once the update is confirmed on that PC. |
| A file the Administrator rejected | `users.rejected_<time>.json`, same folder | Kept so nothing is lost; delete when no longer needed. |
| Recovery code, "this PC is set up" | Windows Credential Manager, entry `FieldSurveyReport/accounts-…` | Belongs to one Windows login. |
| MySQL password (Owner edition) | Windows Credential Manager, entry `FieldSurveyReport/mysql-…` | `db_config.json` then has `"password": ""`. |

Every Windows login has its own `%APPDATA%` and its own Documents folder,
so every Windows login is a separate copy of the program: its own accounts,
its own reports, its own Credential Manager entries. Two people sharing one
Windows login share one copy; two Windows logins on one PC do not see each
other's accounts.

## Accounts and roles

* **Owner** – created from `auth_seed.json`, which only the Owner installer
  contains.
* **Administrator** – the first account created on a PC that has none (the
  one-time "Set Up This PC" screen of the User edition). Approves and
  manages the other accounts of that PC.
* **User** – signs up, waits for approval.

The User installer contains no account, no email and no password hash.
`build_installer.bat` runs `fsr_build_check.py` on the User build and stops
if it finds an account file or any email, salt or hash of this PC's accounts.

## Passwords

* PBKDF2-SHA256, 600,000 iterations, a random salt per account. The count is
  stored with the account (`iterations`).
* An account saved by an earlier program has no count: it is checked with
  the earlier 200,000 and re-hashed with 600,000 (new salt) the next time
  its password is typed correctly.
* Wrong passwords: a wait of 2, 5 and 10 seconds after the 2nd, 3rd and 4th;
  the 5th locks the account for 15 minutes. The lock ends by itself and is
  never longer than 15 minutes, also for the Owner / Administrator. It is
  stored in `users.json`, so restarting the program does not clear it. If
  the PC clock is set back, a lock keeps the time it had left.
* An Administrator's "Reset Password" also ends a lock.

## The signature of users.json

Every time the program saves `users.json` it adds a signature (HMAC-SHA256
over the whole file). The key is derived from the **recovery code** of that
PC: 24 letters and digits, made on the first save, kept in the Windows
Credential Manager and shown to the Administrator once ("write it down").
An Administrator can see it again: Account > Recovery Code.

At every start and every sign in the signature is checked:

| What the program finds | What happens |
|---|---|
| Signature is right | Normal sign in. |
| File of an earlier program (no signature, no code on this PC yet) | Backed up, brought up to date, signed. Nobody has to do anything. |
| File changed after signing, or replaced by an unsigned file | Sign in is blocked for everybody except an Administrator **of the last good copy** (their password from before the change). That person sees what was changed and chooses: restore the last good copy, or accept the changed file. |
| File is missing on a PC that was set up | The same; the first set-up is not offered again. |
| File is signed but this Windows login has no code (moved PC, reinstalled Windows, restored profile, other Windows login) | The program asks for the recovery code. With the right code the file is trusted again and everything works as before. |

Who the Administrator is, is always read from the last good copy, never
from the file that was changed – editing yourself into that role does not
let you in. If the last good copy was changed or deleted as well, nobody is
an Administrator by password: only the recovery code opens the review, and
only then is "Start again with no accounts" offered.

### Recovery paths

* **New PC, reinstalled Windows, restored Windows profile** – copy
  `users.json` (and the data) to the new place, start the program, type the
  recovery code. Accounts and passwords are unchanged.
* **Restoring an older `users.json` that this program wrote on this PC** –
  just put it back; its signature is still right.
* **Restoring `users.before_update_….json`** (undoing the update) – the file
  has no signature, so the program asks for a review: an Administrator
  signs in and chooses "Accept the changed file".
* **Recovery code lost, PC moved** – there is no back door. Delete
  `users.json` and `users.lastgood.json` in the new place and start the
  program: it shows the first set-up again. Accounts must be created again;
  reports and other data are not touched.
* **Recovery code lost, PC not moved** – nothing is wrong: an Administrator
  signs in and reads it under Account > Recovery Code.

## What this does not protect against

This is an offline program whose files and keys are all on the PC of the
person using it. The signature makes changes *evident*; it cannot make them
*impossible*.

* A person who can run their own program under the same Windows login can
  read the recovery code from the Credential Manager and sign a file of
  their own. The signature stops a text editor, not a programmer.
* Deleting the Credential Manager entry **and** both account files makes the
  PC look new: the first set-up is offered again. The reports stay, but
  whoever does this becomes Administrator of that PC.
* An older, correctly signed `users.json` of the same PC is accepted
  (a disabled account could be brought back by restoring an old file).
* Changes made before the update are not detected: the file is signed as it
  is when the update first opens it.
* The 15-minute lock is counted on the PC clock. Setting the clock forward
  ends it early. Setting it back while the program has not looked can make
  a lock last longer than 15 minutes of real time, but never more than 15
  minutes after the next attempt.
* The reports themselves (Excel, JSON) are not signed or encrypted. Anyone
  with the Windows login can open them without the program.
* Without a Windows Credential Manager (not Windows, or it is switched off)
  the code and the MySQL password are kept in plain files and none of the
  above applies.

## Later option: a public-key signature (not built)

To make the file verifiable *without* a secret on the site PC:

1. The owner has a key pair. The private key stays on the owner's PC,
   encrypted with the owner's password; the public key is built into the
   installers.
2. The owner signs each approval ("this email, these initials, this role on
   this PC") on the Owner PC and sends it to the site as a small file; the
   site program accepts only accounts whose approval carries a valid
   signature.
3. A site PC can then check accounts but cannot create a signature, so
   neither a text editor nor a program on the site PC can add an
   Administrator.

Cost: a cryptography library in the installers (Python has no public-key
signatures built in), a hand-off step for every approval, key backup and a
plan for replacing a lost or leaked key. It also changes the answer to "who
approves accounts on a site PC" from the local Administrator to the owner.
