; Inno Setup script for FlexASIO GUI
; Build with: ISCC setup.iss  (output: installer\FlexASIOGUI-Setup.exe)

#define AppName "FlexASIO GUI"
#define AppVersion "1.2.0"
#define AppExe "FlexASIOGUI.exe"

[Setup]
AppId={{B7E6D1A4-3C55-4F0A-9B1E-6A5D8C2F4E71}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ThinkInSound
AppPublisherURL=https://github.com/ThinkInSound/FlexASIO-GUI
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
; Per-user install: no UAC prompt, and the --init config lands in the
; installing user's profile (where FlexASIO looks for it)
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=FlexASIOGUI-Setup
Compression=lzma2
SolidCompression=yes
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}

[Files]
Source: "dist\*"; DestDir: "{app}"; Excludes: "FlexASIOGUI-portable.zip"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Run]
; Create a default FlexASIO.toml (shared mode) if none exists, so the
; driver is configured before the DAW first loads it
Filename: "{app}\{#AppExe}"; Parameters: "--init"; Flags: runhidden
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    if not FileExists(ExpandConstant('{commonpf64}\FlexASIO\x64\FlexASIO.dll')) then
      MsgBox('FlexASIO itself does not appear to be installed.' + #13#10 +
             'Download it from https://github.com/dechamps/FlexASIO/releases' + #13#10 +
             'before using this settings panel.', mbInformation, MB_OK);
end;
