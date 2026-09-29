#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "Prospecta Flow"
#define MyAppPublisher "JVS Tech"
#define MyAppExeName "ProspectaFlow.exe"

[Setup]
AppId={{7A8713D7-A5D7-4E2A-80CF-6DA03156B40C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\ProspectaFlow
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=ProspectaFlowSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; Flags: unchecked
Name: "autostart"; Description: "Iniciar o servidor com o Windows"; Flags: checkedonce

[Files]
Source: "..\dist\ProspectaFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Configurar Prospecta Flow"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure"
Name: "{group}\Painel Prospecta Flow"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--panel"
Name: "{group}\Servidor Prospecta Flow"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--runner"
Name: "{autodesktop}\Prospecta Flow"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--panel"; Tasks: desktopicon
Name: "{userstartup}\Prospecta Flow Server"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--runner"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure"; Description: "Configurar conexão"; Flags: postinstall waituntilterminated skipifsilent
Filename: "{app}\{#MyAppExeName}"; Parameters: "--runner"; Description: "Iniciar servidor"; Flags: postinstall nowait skipifsilent
