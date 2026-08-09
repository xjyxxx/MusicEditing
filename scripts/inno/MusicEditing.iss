; MusicEditing Inno Setup 安装脚本
; 依赖: 已安装 Inno Setup 6+，且已打好便携目录
;
; 用法（仓库根）:
;   scripts\build_installer.bat
;   或: ISCC.exe scripts\inno\MusicEditing.iss
;
; 默认读取 dist 下最新 MusicEditing_Portable_* 目录；
; 也可用命令行: ISCC /DPortableDir="D:\path\to\portable" scripts\inno\MusicEditing.iss

#ifndef PortableDir
  #define PortableDir "..\..\dist\MusicEditing_Portable_PLACEHOLDER"
#endif

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "MusicEditing"
#define MyAppPublisher "MusicEditing"
#define MyAppExeName "MusicEditing.exe"

[Setup]
AppId={{A8F3C2E1-9B4D-4E6A-8F21-MusicEditPortable}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=MusicEditing_Setup_{#MyAppVersion}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes
; 有代码签名证书时可取消下一行注释，并填写 SignTool
; SignTool=signtool

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
; 整个便携目录拷入安装目录（保持 runtime / build_x64 相对路径）
Source: "{#PortableDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := DirExists(ExpandConstant('{#PortableDir}'));
  if not Result then
    MsgBox('便携源目录不存在，请先 pack_portable 或传入 /DPortableDir=...', mbError, MB_OK);
end;
