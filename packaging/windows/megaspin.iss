; Inno Setup script for the MegaSpin Windows installer.
; Build the executable first (see packaging/windows/README.md), then compile this script with ISCC.exe.
; Paths are relative to this file.

#define MyAppName "MegaSpin"
#define MyAppVersion "0.1.0 beta 1"
#define MyAppExe "MegaSpin.exe"

[Setup]
AppId={{46395AE1-C5C7-403B-8E3A-90EB9EF13FA2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=MegaSpin project
AppPublisherURL=https://github.com/pasce/megaspin
AppSupportURL=https://github.com/pasce/megaspin/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
OutputDir=..\..\dist\windows
OutputBaseFilename=MegaSpin-0.1.0-beta1-setup-x64
SetupIconFile=megaspin.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\windows\MegaSpin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent
