#ifndef MyAppVersion
  #define MyAppVersion "1.0.12"
#endif

#define MyAppName "Prospecta Flow"
#define MyAppPublisher "JVS Tech"
#define MyAppExeName "ProspectaFlow.exe"

[Setup]
AppId={{7A8713D7-A5D7-4E2A-80CF-6DA03156B40C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://jvs-prospecta-flow.netlify.app/
AppSupportURL=https://jvs-prospecta-flow.netlify.app/
DefaultDirName={localappdata}\Programs\ProspectaFlow
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
CreateUninstallRegKey=yes
OutputBaseFilename=ProspectaFlowSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter=ProspectaFlow.exe,node.exe,chrome.exe,chromedriver.exe
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=ProspectaFlow.ico
WizardImageFile=installer-sidebar.bmp
WizardSmallImageFile=installer-small.bmp

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; Flags: unchecked
Name: "autostart"; Description: "Iniciar o servidor com o Windows"; Flags: checkedonce

[Files]
Source: "..\dist\ProspectaFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "stop-app-processes.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\whatsapp_gateway"

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\tools\stop-app-processes.ps1"" -InstallPath ""{app}"""; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\ProspectaFlow"
Type: filesandordirs; Name: "{app}"

[Icons]
Name: "{group}\Configurar Prospecta Flow"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure"
Name: "{group}\Painel Prospecta Flow"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--panel"
Name: "{group}\Servidor Prospecta Flow"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--runner"
Name: "{group}\Desinstalar Prospecta Flow"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Prospecta Flow"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--panel"; Tasks: desktopicon
Name: "{userstartup}\Prospecta Flow Server"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--runner"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure"; Description: "Configurar conexão"; Flags: postinstall waituntilterminated skipifsilent
Filename: "{app}\{#MyAppExeName}"; Parameters: "--runner"; Description: "Iniciar servidor"; Flags: postinstall nowait skipifsilent
