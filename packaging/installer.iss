; Inno Setup script for the Windows installer (built by the GitHub workflow).
#define AppVersion GetEnv("ORIS_VERSION")
[Setup]
AppId={{6B2E3C1A-7F4D-4E8B-9A51-0C3D2F7E8B19}
AppName=ORIS
AppVersion={#AppVersion}
AppPublisher=Open Research Technology Co., Ltd.
DefaultDirName={autopf}\ORIS
DefaultGroupName=ORIS
UninstallDisplayIcon={app}\ORIS.exe
OutputDir=..\release
OutputBaseFilename=ORIS-{#AppVersion}-Windows-Setup
SetupIconFile=..\assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
[Files]
Source: "..\dist\ORIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\ORIS"; Filename: "{app}\ORIS.exe"
Name: "{autodesktop}\ORIS"; Filename: "{app}\ORIS.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\ORIS.exe"; Description: "{cm:LaunchProgram,ORIS}"; Flags: nowait postinstall skipifsilent
