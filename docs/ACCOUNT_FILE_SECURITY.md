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

* **Owner** – created by the Owner on the first start of a new Owner
  install ("Set Up This PC"), with a password of their own. No installer
  contains an account or a password hash (since 22 November 2026; earlier
  Owner installers carried `auth_seed.json`). A copy run from the project
  folder can still use a development `auth_seed.json`.
* **Administrator** – the first account created on a PC that has none (the
  one-time "Set Up This PC" screen of the User edition). Approves and
  manages the other accounts of that PC.
* **User** – signs up, waits for approval.

Nobody but the Owner can change the Owner account. A site Administrator
cannot disable, reject, delete or reset the password of the Owner account on
that PC, and the program has no function that changes a role at all (so
nobody can be promoted or demoted). The Owner's password changes only with
the Owner's current password. Changing a role in the file by hand is caught
by the signature (below). Tests: `tests/test_auth_owner_on_site.py`.

### The Owner account on site PCs installed before the update

The 9 November User installer put the Owner account, with its password
hash, on every site PC. The update keeps that account, but:

* The first time it signs in on a site PC (with the old password) the only
  screen that opens is "Set a New Password". Closing it signs nobody in.
* When the new password is set it is stored at 600,000 iterations and the
  old hash is removed from `users.json`, from `users.lastgood.json` and
  from every `users.before_update_…` / `users.rejected_…` file in that
  folder (in those backups the Owner's hash and salt become empty; the
  other accounts stay).
* Wrong tries count towards the 15-minute lock like any sign in.
* Until the Owner has done this on a PC, the old hash is still on that PC.
  `docs/PHASE1_ROLLOUT.md` has a table to track it.

The new password never travels: it is typed on each site PC.

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
Credential Manager.

Who sees the code:

* It is shown once, right after an **Owner or Administrator** has signed in
  with their password (on a new PC: right after the Administrator account
  was created). A normal user never sees it, also not when they are the
  first person to open the program after the update. On an updated site PC
  whose only administrator is the Owner, that means: when the Owner comes,
  signs in and has set the new password.
* Later: Account > Recovery Code. Only for an Owner / Administrator, and
  only after typing the password again; an open session is not enough.
  Wrong passwords there count towards the lock of that account.

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
  ends it early.
* **Accepted exception to "never longer than 15 minutes":** the program
  only knows the time when it is looked at. If the clock is set back while
  the program is closed (or nobody tries to sign in), the lock continues
  with the time it had left at the last attempt the program saw, so the
  real time locked out can be more than 15 minutes. It is never more than
  15 minutes counted from the next sign-in attempt.
* The reports themselves (Excel, JSON) are not signed or encrypted. Anyone
  with the Windows login can open them without the program.
* Without a Windows Credential Manager (not Windows, or it is switched off)
  the code and the MySQL password are kept in plain files and none of the
  above applies.

## Later option: an owner access file with a public-key signature (not built)

Today the Owner must visit (or remotely open) every site PC once to replace
the old password. If that becomes impractical, the new hash could be sent
instead:

1. The owner has a key pair. The private key stays on the owner's PC,
   encrypted with the owner's password; the public key is built into the
   User installer.
2. After changing the password the Owner edition exports a small "owner
   access file": the Owner's email, the new salt, hash and iteration count,
   a date, and a signature made with the private key.
3. On a site PC the file is loaded from the sign-in window. The program
   checks the signature with the built-in public key, checks that the file
   is newer than the last one it accepted, and replaces the Owner's hash.

Because only the owner's PC can make the signature, a forged file is
refused - unlike a file protected only by something the site PC already
knows (such as the old hash, which everyone with a 9 November installer
has). Cost: a cryptography library in both installers, safe keeping and
backup of the private key, and a plan for replacing it if it is lost.

## Later option: a public-key signature for approvals (not built)

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
