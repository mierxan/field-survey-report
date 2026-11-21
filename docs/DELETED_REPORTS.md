# Delete and recover saved reports

Open **Open Saved Report**, select a report, and click **Delete Selected**.
Confirm the Control #. When MySQL is enabled this deletes the whole report
and its lines from MySQL and this PC's local storage and Excel file,
regardless of which source is selected in the list. MySQL must be reachable.
PO-linked Withdrawal reports are excluded from this operation.

Click **Deleted History** to see the Control #, deletion time, user, status,
and restoration time. Select a deleted entry and click **Restore Selected**.
Recovery preserves both the local and MySQL versions when they differed.
An existing report with the same Control # is never overwritten.

If a deletion stops (for example, Excel has the file open), close Excel,
reconnect MySQL if necessary, and use **Retry Incomplete Deletion** in
Deleted History. A failed restore can be resumed with **Restore Selected**.
History remains available even when no active reports remain.

Recovery snapshots are committed before deletion to a local SQLite archive
named `<workbook>_deleted.sqlite3` in the workbook's JSON data directory.
Keep that file with your backups. History is retained until you remove the
archive yourself; it is not automatically purged. Times use the PC's clock.

Use the application's Delete button for this workflow. SQL DELETE commands
issued outside the application do not create recovery snapshots or update
Excel. This operation updates this PC; other PCs have their own local files
and recovery archives. A separate automatic cross-PC deletion protocol is
not part of this workflow.
