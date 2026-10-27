#define MyAppName "HWddns"
#define MyAppVersion "0.4.7"

[Setup]
AppId=HWddns.Panhui.Windows
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=hainiu6
AppPublisherURL=https://github.com/hainiu6/HWddns
DefaultDirName={localappdata}\Programs\HWddns
DefaultGroupName=HWddns
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=Output
OutputBaseFilename=HWddns-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\HWddns.exe
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "其他选项:"; Flags: unchecked

Name: "startup"; Description: "开机自动启动（当前用户登录后）"; GroupDescription: "启动选项:"; Flags: unchecked

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "HWddns"; ValueData: """{app}\HWddns.exe"" --background"; Tasks: startup

[Files]
Source: "..\dist\HWddns\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\HWddns"; Filename: "{app}\HWddns.exe"
Name: "{autodesktop}\HWddns"; Filename: "{app}\HWddns.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\HWddns.exe"; Description: "启动 HWddns"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'HWddns');
end;
