; Instalador de VibeLoader (Inno Setup 6). Lo compila build_vibeload.bat:
;   iscc /DMyAppVersion=4.0 installer.iss
; Instala por usuario (sin pedir administrador) a partir de dist\VibeLoader\.

#ifndef MyAppVersion
  #define MyAppVersion "0.0"
#endif

[Setup]
AppId={{58BDDDE8-0A67-446C-8A28-C761830A0340}
AppName=VibeLoader
AppVersion={#MyAppVersion}
AppPublisher=Cracksmity
AppPublisherURL=https://github.com/Cracksmity/vibeload
DefaultDirName={autopf}\VibeLoader
DefaultGroupName=VibeLoader
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=VibeLoader-Setup-{#MyAppVersion}
SetupIconFile=assets\icono.ico
UninstallDisplayIcon={app}\VibeLoader.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\VibeLoader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VibeLoader"; Filename: "{app}\VibeLoader.exe"
Name: "{autodesktop}\VibeLoader"; Filename: "{app}\VibeLoader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VibeLoader.exe"; Description: "Abrir VibeLoader"; Flags: nowait postinstall skipifsilent
