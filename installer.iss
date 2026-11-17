; Inno Setup script - builds one Setup file per edition:
;   Installer\FieldSurveyReport_Owner_Setup_<version>.exe  (Excel + MySQL)
;   Installer\FieldSurveyReport_User_Setup_<version>.exe   (this PC only)
; build_installer.bat passes the unique release and numeric Windows versions.
#ifndef AppVersion
  #define AppVersion "1.0"
#endif
#ifndef WindowsVersion
  #define WindowsVersion "1.0.0.0"
#endif
#ifndef Edition
  #define Edition "Owner"
#endif
#define AppExe "FieldSurveyReport.exe"

#if Edition == "Owner"
  ; same AppId as the earlier single installer, so the owner's PC updates in place
  #define AppGuid "{{6F0C3C1E-2B7A-4C55-9E61-4F5A5B1D7A10}"
  #define AppName "Field Survey Report"
#else
  #define AppGuid "{{B3E1A7D2-5C49-4F0B-8D36-2A9E71C4F5B8}"
  #define AppName "Field Survey Report (User)"
#endif

[Setup]
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#Edition} edition {#AppVersion}
VersionInfoVersion={#WindowsVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Installer
OutputBaseFilename=FieldSurveyReport_{#Edition}_Setup_{#AppVersion}
SetupIconFile=logo.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
; a hand-over file (.fsrhandover) opens the program - [Registry]
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; remove files left over from the previous version of the program
Type: filesandordirs; Name: "{app}\_internal"
; Nothing outside {app} is ever removed - neither by Setup nor by the
; uninstaller, except the .fsrhandover file type in [Registry]: the
; reports database (%LOCALAPPDATA%\FieldSurveyReport\Databases), the accounts and settings (%APPDATA%\FieldSurveyReport) and
; the data in Documents\Field Survey Report stay. (Tested on a scratch
; install on 14 November 2026: install, reinstall, uninstall - docs\SQLITE.md.)

[Files]
Source: "dist\{#Edition}\FieldSurveyReport\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs
; the way back from the reports database to the Excel file (docs\SQLITE.md)
Source: "GO_BACK_TO_WORKBOOK.bat"; DestDir: "{app}"; Flags: ignoreversion
#if Edition == "Owner"
; database scripts for MySQL Workbench (not used by the program itself)
Source: "data\schema\field_survey_schema.sql"; DestDir: "{app}\sql"; Flags: ignoreversion
Source: "data\schema\migrations\*.sql"; DestDir: "{app}\sql\migrations"; Flags: ignoreversion skipifsourcedoesntexist
#endif

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Double-clicking a hand-over file opens the program, which asks the
; inspector before bringing it in (fsr_incoming.py, docs\HANDOVER.md).
; Each edition has its own file type; the last edition installed opens
; the files. Uninstalling one edition keeps the other under Open with.
Root: HKA; Subkey: "Software\Classes\.fsrhandover"; ValueType: string; ValueName: ""; ValueData: "FieldSurveyReport.Handover.{#Edition}"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.fsrhandover\OpenWithProgids"; ValueType: string; ValueName: "FieldSurveyReport.Handover.{#Edition}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\FieldSurveyReport.Handover.{#Edition}"; ValueType: string; ValueName: ""; ValueData: "Field Survey Report Hand-over"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\FieldSurveyReport.Handover.{#Edition}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\FieldSurveyReport.Handover.{#Edition}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
