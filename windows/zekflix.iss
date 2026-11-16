#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B7A1D2E4-5C3F-4E8A-9D61-2F0C7A9E4B11}
AppName=ZekFlix
AppVersion={#AppVersion}
AppPublisher=ezekielso
DefaultDirName={autopf}\ZekFlix
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\release
OutputBaseFilename=ZekFlix-Setup-{#AppVersion}
SetupIconFile=..\zekflix.ico
UninstallDisplayIcon={app}\ZekFlix.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\ZekFlix\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ZekFlix"; Filename: "{app}\ZekFlix.exe"
Name: "{autodesktop}\ZekFlix"; Filename: "{app}\ZekFlix.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ZekFlix.exe"; Description: "{cm:LaunchProgram,ZekFlix}"; Flags: nowait postinstall skipifsilent
