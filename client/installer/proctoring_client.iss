; ==========================================================================
; Proctoring Client - Inno Setup 6 o'rnatuvchisi
; ==========================================================================
; Odatda `installer\build.ps1` chaqiradi:
;
;   ISCC /DAppVersion=1.0.0 /DVariant=gpu /DSourceDir=..\dist\gpu\ProctoringClient
;        /DEnvSource=..\build\gpu\client.env
;        /DOutputDir=..\dist\installer [/DIconFile=..] [/DVcRedist=..] proctoring_client.iss
;
; SERVER MANZILI O'RNATISHDA SO'RALMAYDI. U build paytida tayyor `.env`
; dan (`installer\client.env`, build.ps1 tekshiradi) o'rnatuvchining
; ICHIGA joylanadi. Sabab: manzil bitta o'rnatish (viloyat/markaz) uchun
; bitta va o'zgarmaydi - uni 500 mashinaning har birida qo'lda terish
; faqat xato qilish imkoniyati edi (bitta harf xatosi = mashina hech
; qayerga ulanmaydi va buni faqat o'sha mashinaga borib topish mumkin).
; Mashinaga xos yagona qiymat - INVENTAR KODI - so'raladi, u ixtiyoriy.
;
; SILENT (ommaviy tarqatish, GPO/SCCM/PDQ):
;
;   ProctoringClientSetup-1.0.0-gpu.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
;       [/INVENTORY_CODE=INV-001] [/ENVFILE=\\server\share\bino12.env]
;       [/FORCEENV] [/TASKS="autostart,desktopicon"] [/LOG="C:\Windows\Temp\pc-setup.log"]
;
; Chiqish kodi 0 - muvaffaqiyat.
;
; FAYL FAQAT ASCII: ISCC BOM'siz skriptni ANSI deb o'qiydi.
; ==========================================================================

#ifndef AppVersion
  #error "AppVersion berilmagan: ISCC /DAppVersion=1.0.0 (build.ps1 version.py dan o'qiydi)"
#endif
#ifndef AppVersionNumeric
  #define AppVersionNumeric AppVersion
#endif
#ifndef Variant
  #define Variant "gpu"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\" + Variant + "\ProctoringClient"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installer"
#endif
#ifndef EnvSource
  #error "EnvSource berilmagan: ISCC /DEnvSource=<tayyor .env> (build.ps1 installer\client.env dan tayyorlaydi)"
#endif
#if !FileExists(EnvSource)
  #error "EnvSource topilmadi: " + EnvSource
#endif
#ifndef Compression
  #define Compression "lzma2/ultra64"
#endif

#define AppName "Proctoring Client"
#define AppDirName "ProctoringClient"
#define AppExeName "ProctoringClient.exe"
#define CheckExeName "ProctoringClientCheck.exe"
#define TaskName "ProctoringClient"

#if !FileExists(AddBackslash(SourceDir) + AppExeName)
  #error "Bundle topilmadi: " + SourceDir + " (avval PyInstaller: build.ps1)"
#endif

[Setup]
; AppId - O'ZGARTIRILMAYDI. Windows yangilashni aynan shu GUID bo'yicha
; taniydi: u o'zgarsa yangi versiya eskisining ustiga emas, YONIGA
; o'rnatiladi va mashinada ikkita client, ikkita avtostart vazifasi
; paydo bo'ladi. GPU va CPU nashri BIR XIL AppId: ular bitta dasturning
; ikki ko'rinishi va biri ikkinchisini almashtiradi.
AppId={{D942E94C-337F-44E4-AD31-52F2FFC15F0F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} ({#Variant})
AppPublisher=Proctoring System
VersionInfoVersion={#AppVersionNumeric}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup ({#Variant})

; Program Files: oddiy foydalanuvchi (talabgor) dastur fayllarini
; o'zgartira olmaydi. Buning narxi - administrator huquqi va `.env`
; ning ProgramData'ga ko'chishi (pastda).
DefaultDirName={autopf}\{#AppDirName}
DisableDirPage=auto
DisableProgramGroupPage=yes
DefaultGroupName={#AppName}
PrivilegesRequired=admin
; x64compatible: x64 va ARM64 (x64 emulyatsiyasi). Bundle faqat x64.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Qt 6.11 - Windows 10 1809 va undan yangi.
MinVersion=10.0.17763

OutputDir={#OutputDir}
OutputBaseFilename=ProctoringClientSetup-{#AppVersion}-{#Variant}
#ifdef IconFile
SetupIconFile={#IconFile}
#endif
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
WizardStyle=modern

; Siqish: bundle'ning ~2/3 qismi CUDA DLL'lari va ular yaxshi siqiladi.
; Solid + LZMA2 - bitta katta oqim, eng kichik setup.exe. Alohida 64-bit
; jarayon va bloklar bo'yicha oqimlar - 2-3 GB ni siqish vaqti uchun.
Compression={#Compression}
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4

; Kiosk client yopilishni rad etadi (closeEvent parol so'raydi), ya'ni
; Restart Manager uni "yumshoq" yopa olmaydi va har o'rnatishda
; "dasturni yoping" dialogi chiqardi. Jarayon [Code] da o'ldiriladi.
CloseApplications=no
RestartApplications=no
SetupLogging=yes
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[CustomMessages]
MachineCaption=Kompyuter
MachineDescription=Shu kompyuterning inventar kodi
MachineSubCaption=Ixtiyoriy. Bo'sh qoldirilsa server kompyuterni MAC manzili bo'yicha topadi. Qiymat ProgramData\ProctoringClient\.env fayliga yoziladi.
MachineInventoryLabel=Inventar kodi (ixtiyoriy), masalan INV-001
ErrInventory=Inventar kodi 3-50 belgidan iborat bo'lishi va faqat lotin harfi, raqam, "-" va "_" dan tuzilishi kerak (yoki bo'sh qoldiring).
ErrEnvFileMissing=/ENVFILE ko'rsatgan fayl topilmadi:
ErrEnvWrite=.env yozilmadi:
WarnAutostart=Avtostart vazifasi yaratilmadi (kod %1). Qo'lda: tools\autostart.ps1 -Action Register
TaskAutostart=Windows'ga kirilganda avtomatik ishga tushirish (kiosk)
TaskDesktop=Ish stolida yorliq
StatusVcRedist=Microsoft Visual C++ runtime o'rnatilmoqda...
RunAfterInstall=Dasturni ishga tushirish

[Tasks]
; Avtostart standart YOQILGAN: o'rnatuvchining asosiy auditoriyasi -
; imtihon mashinalari. Sinov mashinasida /TASKS="" yoki belgini olib
; tashlang. Nega Task Scheduler (Run kaliti emas) - tools\autostart.ps1.
Name: "autostart"; Description: "{cm:TaskAutostart}"
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; Flags: unchecked

[InstallDelete]
; Oldingi versiyaning `_internal` i BUTUNLAY o'chiriladi. onedir'da
; yangilash faqat fayllarni ustidan yozsa, eski versiyada bo'lib yangisida
; yo'q DLL qolib ketadi - masalan GPU -> CPU nashriga o'tishda 2 GB lik
; `cuda/` katalogi, yoki eski Qt plagini, u esa yangi Qt bilan birga
; yuklanib "procedure not found" beradi.
Type: filesandordirs; Name: "{app}\_internal"

[Dirs]
; ProgramData\ProctoringClient - mashina sozlamasi (`.env`). Uninstall'da
; O'CHIRILMAYDI: qayta o'rnatishda server manzili qaytadan so'ralmasligi
; kerak. Standart ACL: administrator yaratgan faylni oddiy foydalanuvchi
; faqat O'QIYDI - talabgor `KIOSK_MODE=false` yoza olmaydi.
Name: "{commonappdata}\{#AppDirName}"; Flags: uninsneveruninstall

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "autostart.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
; Tayyor `.env` (server manzili bilan) - {app} ga EMAS, faqat o'rnatish
; paytida {tmp} ga ochiladi (`dontcopy` + ExtractTemporaryFile). Program
; Files'da ikkinchi nusxa qolsa, administrator uni tahrirlab "nega
; o'zgarmadi?" deb qolardi: client faqat ProgramData'dagini o'qiydi.
Source: "{#EnvSource}"; DestName: "client.env"; Flags: dontcopy
#ifdef VcRedist
Source: "{#VcRedist}"; DestDir: "{tmp}"; DestName: "vc_redist.x64.exe"; Flags: deleteafterinstall; Check: VcRedistNeeded
#endif
; %APPDATA%\ProctoringClient (device_id.json, log) bu yerda YO'Q va bu
; ataylab: o'rnatuvchi u yerga hech narsa yozmaydi, ya'ni uninstall ham
; unga tegmaydi. `device_id` - serverdagi qurilma yozuvining kaliti; u
; yo'qolsa qayta o'rnatilgan mashina administrator tasdig'ini qaytadan
; kutib qoladi (`core/bundle_paths.writable_root`).

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autoprograms}\{#AppName} - diagnostika"; Filename: "{sys}\cmd.exe"; Parameters: "/k ""{app}\{#CheckExeName}"""; WorkingDir: "{app}"; Check: CheckExeExists
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
#ifdef VcRedist
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "{cm:StatusVcRedist}"; Flags: waituntilterminated; Check: VcRedistNeeded
#endif
; `runasoriginaluser`: o'rnatuvchi administrator huquqida ishlaydi va
; undan ochilgan client ham yuqori huquqni meros qilib olardi. Standart
; belgisiz - kiosk client ishga tushishi bilan boshqa oynalarni yopadi
; (CLOSE_OTHER_APPS), o'rnatayotgan administrator buni kutmaydi.
Filename: "{app}\{#AppExeName}"; Description: "{cm:RunAfterInstall}"; Flags: nowait postinstall skipifsilent runasoriginaluser unchecked

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""{#TaskName}"" /F"; Flags: runhidden; RunOnceId: "RemoveAutostartTask"

[UninstallDelete]
; Ishlash paytida paydo bo'lishi mumkin bo'lgan qoldiqlar (QtWebEngine
; keshi `_internal` ichida emas, lekin kelajakdagi o'zgarishga qarshi).
Type: filesandordirs; Name: "{app}\_internal"

[Code]
var
  MachinePage: TInputQueryWizardPage;

{ ---------------------------------------------------------------------- }
{ Yordamchilar                                                            }
{ ---------------------------------------------------------------------- }
function EnvDir: String;
begin
  Result := ExpandConstant('{commonappdata}\{#AppDirName}');
end;

function EnvPath: String;
begin
  Result := EnvDir + '\.env';
end;

function ParamValue(const Name: String): String;
begin
  Result := Trim(ExpandConstant('{param:' + Name + '|}'));
end;

{ Qiymatsiz kalit, masalan /FORCEENV. }
function HasSwitch(const Name: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/' + Name) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

function StartsWithText(const Value, Prefix: String): Boolean;
begin
  Result := CompareText(Copy(Value, 1, Length(Prefix)), Prefix) = 0;
end;

{ Server qoidasi bilan AYNAN bir xil (`common.utils.validators.
  inventory_code_validator`: 3-50 belgi, A-Z a-z 0-9 - _). Bu yerda
  tekshirilmasa xato qiymat `.env` ga yozilar va har handshake'da server
  uni rad etardi - operator esa sababni o'rnatuvchidan emas, logdan
  qidirardi. Bo'sh - ruxsat (kod ixtiyoriy). }
function ValidInventory(const Value: String): Boolean;
var
  I: Integer;
  C: Char;
begin
  Result := True;
  if Value = '' then
    Exit;
  if (Length(Value) < 3) or (Length(Value) > 50) then
  begin
    Result := False;
    Exit;
  end;
  for I := 1 to Length(Value) do
  begin
    C := Value[I];
    if not (((C >= 'A') and (C <= 'Z')) or ((C >= 'a') and (C <= 'z')) or
            ((C >= '0') and (C <= '9')) or (C = '-') or (C = '_')) then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

{ MAVJUD .env HECH QACHON jimgina ustidan yozilmaydi: unda administrator
  qo'lda qo'ygan qiymatlar bo'lishi mumkin (INVENTORY_CODE, arxiv diski).
  Faqat ochiq /FORCEENV bilan - va o'shanda ham eski nusxa saqlanadi. }
function ShouldWriteEnv: Boolean;
begin
  Result := HasSwitch('FORCEENV') or not FileExists(EnvPath);
end;

{ Inventar kodi faqat YANGI .env yozilayotganda so'raladi: yangilashda
  mavjud fayl saqlanadi va undagi kod o'z joyida qoladi. /ENVFILE bilan
  esa to'liq fayl tashqaridan keladi. }
function NeedMachineInput: Boolean;
begin
  Result := ShouldWriteEnv and (ParamValue('ENVFILE') = '');
end;

function CheckExeExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\{#CheckExeName}'));
end;

procedure KillClient;
var
  Code: Integer;
begin
  { Kiosk client oddiy yopilishni rad etadi. /T - QtWebEngineProcess
    bolalari ham: ular `_internal` dagi DLL'larni band qilib turadi va
    fayllarni almashtirib bo'lmay qoladi.
    NARXI: majburan o'ldirilgan client o'chirilgan qo'shimcha monitorlarni
    QAYTARMAYDI (main._restore_monitors `finally` da). Yangilashni imtihon
    vaqtidan tashqarida o'tkazing. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#AppExeName}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#CheckExeName}', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

#ifdef VcRedist
{ Bundle VC++ runtime'ni o'zi bilan olib keladi (app-local, 14.44). Tizim
  nusxasi faqat ESKI bo'lsa yangilanadi: ba'zi yuklovchilar (ctypes,
  add_dll_directory) System32 ni `_internal` dan OLDIN qidiradi va eski
  msvcp140 onnxruntime 1.2x da std::mutex qulashini beradi. }
function RuntimeIsRecent(const RootKey: Integer): Boolean;
var
  Installed, Major, Minor: Cardinal;
  Key: String;
begin
  Key := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  Result := RegQueryDWordValue(RootKey, Key, 'Installed', Installed) and (Installed = 1) and
            RegQueryDWordValue(RootKey, Key, 'Major', Major) and
            RegQueryDWordValue(RootKey, Key, 'Minor', Minor) and
            ((Major > 14) or ((Major = 14) and (Minor >= 40)));
end;

function VcRedistNeeded: Boolean;
begin
  Result := not (RuntimeIsRecent(HKLM64) or RuntimeIsRecent(HKLM32));
end;
#endif

{ ---------------------------------------------------------------------- }
{ .env                                                                    }
{ ---------------------------------------------------------------------- }
procedure BackupEnv;
var
  Backup: String;
begin
  if FileExists(EnvPath) then
  begin
    Backup := EnvPath + '.bak-' + GetDateTimeString('yyyymmdd-hhnnss', #0, #0);
    if RenameFile(EnvPath, Backup) then
      Log('.env zaxira nusxasi: ' + Backup)
    else
      Log('.env zaxira nusxasi YARATILMADI: ' + Backup);
  end;
end;

procedure WriteEnv;
var
  Source, Template: String;
  Raw: AnsiString;
begin
  if not ShouldWriteEnv then
  begin
    Log('Mavjud .env saqlandi (ustidan yozish uchun /FORCEENV): ' + EnvPath);
    Exit;
  end;

  ForceDirectories(EnvDir);

  { /ENVFILE - bino yoki viloyat uchun tayyorlangan to'liq fayl. Ommaviy
    tarqatishda qulay: bitta buyruq, har bino uchun bitta fayl. }
  Source := ParamValue('ENVFILE');
  if Source <> '' then
  begin
    BackupEnv;
    if CopyFile(Source, EnvPath, False) then
      Log('.env nusxalandi: ' + Source + ' -> ' + EnvPath)
    else
      SuppressibleMsgBox(CustomMessage('ErrEnvWrite') + #13#10 + EnvPath, mbError, MB_OK, IDOK);
    Exit;
  end;

  { Server manzili bilan tayyor fayl (build paytida joylangan). Unda
    yagona o'rinbosar - @INVENTORY_CODE@ (build.ps1 qo'yadi). Fayl xom
    baytlar sifatida o'qiladi va yoziladi: almashtiriladigan qiymat
    ASCII (ValidInventory), ya'ni izohlardagi UTF-8 matni buzilmaydi. }
  ExtractTemporaryFile('client.env');
  Template := ExpandConstant('{tmp}\client.env');
  if not LoadStringFromFile(Template, Raw) then
  begin
    SuppressibleMsgBox(CustomMessage('ErrEnvWrite') + #13#10 + Template, mbError, MB_OK, IDOK);
    Exit;
  end;

  Source := String(Raw);
  StringChangeEx(Source, '@INVENTORY_CODE@', Trim(MachinePage.Values[0]), True);

  BackupEnv;
  if SaveStringToFile(EnvPath, AnsiString(Source), False) then
    Log('.env yozildi: ' + EnvPath)
  else
    SuppressibleMsgBox(CustomMessage('ErrEnvWrite') + #13#10 + EnvPath, mbError, MB_OK, IDOK);
end;

{ ---------------------------------------------------------------------- }
{ Avtostart                                                               }
{ ---------------------------------------------------------------------- }
procedure ConfigureAutostart;
var
  Code: Integer;
  Action, Params: String;
begin
  { Belgi olib tashlangan yangilashda eski vazifa ham O'CHIRILADI -
    aks holda "avtostartni o'chirdim" degan administrator qarori
    jimgina e'tiborsiz qolardi. }
  if WizardIsTaskSelected('autostart') then
    Action := 'Register'
  else
    Action := 'Unregister';

  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
            ExpandConstant('{app}\tools\autostart.ps1') + '" -Action ' + Action +
            ' -TaskName "{#TaskName}" -ExePath "' + ExpandConstant('{app}\{#AppExeName}') + '"';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '',
              SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
  begin
    Log('autostart.ps1 ' + Action + ' kodi: ' + IntToStr(Code));
    if Action = 'Register' then
      SuppressibleMsgBox(FmtMessage(CustomMessage('WarnAutostart'), [IntToStr(Code)]),
                         mbInformation, MB_OK, IDOK);
  end
  else
    Log('Avtostart: ' + Action);
end;

{ ---------------------------------------------------------------------- }
{ Setup hodisalari                                                        }
{ ---------------------------------------------------------------------- }
function InitializeSetup: Boolean;
var
  EnvFile: String;
begin
  Result := True;
  EnvFile := ParamValue('ENVFILE');

  if (EnvFile <> '') and not FileExists(EnvFile) then
  begin
    Log('XATO: /ENVFILE topilmadi: ' + EnvFile);
    SuppressibleMsgBox(CustomMessage('ErrEnvFileMissing') + #13#10 + EnvFile, mbCriticalError, MB_OK, IDOK);
    Result := False;
    Exit;
  end;

  { Silent rejimda sahifa yo'q - kod faqat buyruq satridan. Xato kod
    bilan o'rnatishni BOSHLAMAYMIZ: jimgina tashlab yuborish mashinani
    MAC bo'yicha qidiruvga tushirib qo'yardi va administrator bergan
    qiymat izsiz yo'qolardi. }
  if WizardSilent and NeedMachineInput and not ValidInventory(ParamValue('INVENTORY_CODE')) then
  begin
    Log('XATO: ' + CustomMessage('ErrInventory'));
    SuppressibleMsgBox(CustomMessage('ErrInventory'), mbCriticalError, MB_OK, IDOK);
    Result := False;
    Exit;
  end;
end;

procedure InitializeWizard;
begin
  MachinePage := CreateInputQueryPage(wpSelectTasks,
    CustomMessage('MachineCaption'), CustomMessage('MachineDescription'),
    CustomMessage('MachineSubCaption'));
  MachinePage.Add(CustomMessage('MachineInventoryLabel'), False);

  { Buyruq satridagi qiymat sahifani TO'LDIRADI - silent rejimda ham
    aynan shu maydondan o'qiladi (bitta manba). }
  MachinePage.Values[0] := ParamValue('INVENTORY_CODE');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = MachinePage.ID) and not NeedMachineInput;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = MachinePage.ID) and not ValidInventory(Trim(MachinePage.Values[0])) then
  begin
    MsgBox(CustomMessage('ErrInventory'), mbError, MB_OK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillClient;
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WriteEnv;
    ConfigureAutostart;
  end;
end;

function InitializeUninstall: Boolean;
begin
  KillClient;
  Result := True;
end;
