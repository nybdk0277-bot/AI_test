; Inno Setup script for svtracker.
; ビルド: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
; 事前に repo ルートで PyInstaller を実行し、dist\svtracker.exe (CLI) と
; dist\svtracker-gui.exe (GUI) の両方を作っておくこと。

#define MyAppName "svtracker"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "svtracker project"

[Setup]
AppId={{B6B7B9C4-6E1A-4C6E-9C7E-9E7B7A0C9E11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=svtracker-setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作成する"; GroupDescription: "追加のアイコン:"

[Files]
Source: "..\dist\svtracker-gui.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\svtracker.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config\settings.example.json"; DestDir: "{app}\config"; Flags: ignoreversion
Source: "..\config\regions.example.json"; DestDir: "{app}\config"; Flags: ignoreversion

[Dirs]
Name: "{app}\data\cards"
Name: "{app}\data\matches"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\svtracker-gui.exe"; WorkingDir: "{app}"
Name: "{group}\{#MyAppName} (コマンドライン版・上級者向け)"; Filename: "{app}\svtracker.exe"; WorkingDir: "{app}"
Name: "{group}\README"; Filename: "{app}\README.md"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\svtracker-gui.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\svtracker-gui.exe"; Description: "svtrackerを起動する"; Flags: postinstall nowait skipifsilent
Filename: "{app}\README.md"; Description: "READMEを開く(セットアップ手順・OCR本体の別途インストールについて記載)"; Flags: postinstall shellexec skipifsilent unchecked
