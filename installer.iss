; Inno Setup script - builds Installer\FieldSurveyReport_Setup.exe
; build_installer.bat passes /DAppVersion=<build date>
#define AppName "Field Survey Report"
#ifndef AppVersion
  #define AppVersion "1.0"
#endif
#define AppExe "FieldSurveyReport.exe"

[Setup]
AppId={{6F0C3C1E-2B7A-4C55-9E61-4F5A5B1D7A10}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Installer
OutputBaseFilename=FieldSurveyReport_Setup
SetupIconFile=logo.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; remove files left over from the previous version of the program
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\FieldSurveyReport\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs
; database scripts for MySQL Workbench (not used by the program itself)
Source: "data\schema\field_survey_schema.sql"; DestDir: "{app}\sql"; Flags: ignoreversion
Source: "data\schema\migrations\*.sql"; DestDir: "{app}\sql\migrations"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
