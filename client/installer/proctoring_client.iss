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
; Bundle hajmi (MB) - disk tekshiruvi uchun, build.ps1 o'lchab beradi.
; Qo'lda ISCC chaqirilganda 0: faqat zaxira chegara tekshiriladi.
#ifndef BundleMB
  #define BundleMB "0"
#endif
; version.py COMPANY_NAME (build.ps1 uzatadi) - .exe resursi bilan bir xil.
#ifndef AppPublisher
  #define AppPublisher "Proctoring System"
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
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersionNumeric}
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup ({#Variant})

; Kod imzosi - faqat build.ps1 SIGN_CERT_THUMBPRINT bilan chaqirganda
; (ISCC /Sproctoringsign=... /DSignToolName=proctoringsign). ISCC
; setup.exe ni VA uninstaller'ni imzolaydi: unins000.exe ISCC ichida
; yasaladi va uni keyin tashqaridan imzolab bo'lmaydi.
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

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
; Qt 6.11 - Windows 10 1809 va undan yangi. Eski Windows'da (7/8.1, 10
; 1803-) va 32-bit tizimda Setup O'ZI to'xtaydi (Inno xabari, kod 1) -
; qo'shimcha [Code] tekshiruvi kerak emas. Administrator huquqini ham
; Setup o'zi so'raydi (PrivilegesRequired=admin -> UAC); SCCM/PDQ SYSTEM
; nomidan ishlatadi, ya'ni /VERYSILENT da UAC oynasi chiqmaydi.
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
; "dasturni yoping" dialogi chiqardi. Jarayon [Code] da o'ldiriladi
; (StopClient). AppMutex ham ATAYLAB yo'q: client mutex'i topilsa Setup
; "dasturni yoping, keyin OK" deb kutib qolardi - kiosk client'ni esa
; operator yopa olmaydi, yangilash ishlab turgan mashinada o'tadi.
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
ErrStillRunning=Proctoring Client jarayonlarini to'xtatib bo'lmadi (%1). O'rnatish BOSHLANMADI, eski versiya o'z holicha qoldi. Kompyuterni qayta yuklab, o'rnatuvchini qaytadan ishga tushiring.
ErrDiskSpace=%3 diskida joy yetarli emas: kerak %1 MB, bo'sh %2 MB. O'rnatish BOSHLANMADI. Diskni bo'shating yoki /DIR= bilan boshqa diskni tanlang.
ErrRollbackPrepare=Eski versiya zaxiraga olinmadi (%1). O'rnatish BOSHLANMADI, eski versiya o'z holicha qoldi. Fayl band bo'lishi mumkin - kompyuterni qayta yuklab, qaytadan urinib ko'ring.
WarnVcRedistFailed=Microsoft Visual C++ runtime o'rnatilmadi (kod %1). Dastur o'z runtime nusxasi bilan ishlaydi; muammo bo'lsa qo'lda o'rnating: https://aka.ms/vs/17/release/vc_redist.x64.exe
WarnVcRuntimeOld=Tizimdagi Microsoft Visual C++ runtime eski (14.40 dan past). Yuz tekshiruvi (ONNX Runtime) unda qulashi mumkin. O'rnatish davom etadi; iloji boricha yangilang: https://aka.ms/vs/17/release/vc_redist.x64.exe
ErrUninstallRunning=Proctoring Client jarayonlarini to'xtatib bo'lmadi (%1). O'chirish BEKOR qilindi. Kompyuterni qayta yuklab, qaytadan urinib ko'ring.

[Tasks]
; Avtostart standart YOQILGAN: o'rnatuvchining asosiy auditoriyasi -
; imtihon mashinalari. Sinov mashinasida /TASKS="" yoki belgini olib
; tashlang. Nega Task Scheduler (Run kaliti emas) - tools\autostart.ps1.
Name: "autostart"; Description: "{cm:TaskAutostart}"
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; Flags: unchecked

[InstallDelete]
; Oldingi versiyaning `_internal` i yangisi bilan ARALASHMASLIGI kerak.
; onedir'da yangilash faqat fayllarni ustidan yozsa, eski versiyada bo'lib
; yangisida yo'q DLL qolib ketadi - masalan GPU -> CPU nashriga o'tishda
; 2 GB lik `cuda/` katalogi, yoki eski Qt plagini, u esa yangi Qt bilan
; birga yuklanib "procedure not found" beradi.
; Odatda bu yerga kelganda `_internal` YO'Q: PrepareToInstall uni
; o'chirmaydi, `{app}\_rollback` ga KO'CHIRADI (BackupPrevious) - o'rnatish
; yarmida yiqilsa eski versiya qaytariladi. Bu qator - zaxira.
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
; `dontcopy`: PrepareToInstall o'zi ochadi va FAYLLARDAN OLDIN o'rnatadi -
; [Run] da (uninstaller yakunlangandan keyin) xatosi rollback qilinmasdi
; va chiqish kodi (3010 - qayta yuklash) e'tiborsiz qolardi.
Source: "{#VcRedist}"; DestName: "vc_redist.x64.exe"; Flags: dontcopy
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
; `runasoriginaluser`: o'rnatuvchi administrator huquqida ishlaydi va
; undan ochilgan client ham yuqori huquqni meros qilib olardi. Standart
; belgisiz - kiosk client ishga tushishi bilan boshqa oynalarni yopadi
; (CLOSE_OTHER_APPS), o'rnatayotgan administrator buni kutmaydi.
Filename: "{app}\{#AppExeName}"; Description: "{cm:RunAfterInstall}"; Flags: nowait postinstall skipifsilent runasoriginaluser unchecked

[UninstallRun]
; Jarayonlar bundan OLDIN to'xtatilgan (InitializeUninstall -> StopClient).
; Vazifa o'chirilmasa keyingi kirishda Task Scheduler yo'q .exe ni
; ishga tushirishga urinib, "0x80070002" xatosini yozib yuraverardi.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""{#TaskName}"" /F"; Flags: runhidden; RunOnceId: "RemoveAutostartTask"

[UninstallDelete]
; Ishlash paytida paydo bo'lishi mumkin bo'lgan qoldiqlar (QtWebEngine
; keshi `_internal` ichida emas, lekin kelajakdagi o'zgarishga qarshi).
; `_rollback` - yiqilgan o'rnatishdan (masalan elektr o'chishi) qolgan
; eski versiya zaxirasi. ProgramData\.env va %APPDATA% ATAYLAB bu yerda
; yo'q ([Dirs] va [Files] dagi izohlar).
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\_rollback"

[Code]
var
  MachinePage: TInputQueryWizardPage;
  { Eski versiya `<app>\_rollback` ga ko'chirildi - yiqilishda qaytariladi. }
  RollbackArmed: Boolean;
  { Fayllar to'liq yozildi (ssPostInstall) - qaytarish endi kerak emas. }
  InstallFinished: Boolean;
  { vc_redist 3010/1641 qaytardi - oxirida qayta yuklash taklif qilinadi. }
  VcRestartNeeded: Boolean;

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

{ ---------------------------------------------------------------------- }
{ Client jarayonlarini to'xtatish                                         }
{ ---------------------------------------------------------------------- }
{ `tasklist` matni lokalizatsiya qilingan ("INFO: No tasks..." / ruscha),
  shuning uchun matn emas, `find` ning chiqish kodi o'qiladi: jarayon nomi
  faqat topilgan qatorda bo'ladi. }
function ProcessRunning(const ExeName: String): Boolean;
var
  Code: Integer;
  Sys: String;
begin
  Sys := ExpandConstant('{sys}');
  Result := Exec(ExpandConstant('{cmd}'),
                 '/C ' + Sys + '\tasklist.exe /NH /FI "IMAGENAME eq ' + ExeName + '" | ' +
                 Sys + '\find.exe /I "' + ExeName + '" >NUL',
                 '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

function ClientRunning: Boolean;
begin
  Result := ProcessRunning('{#AppExeName}') or ProcessRunning('{#CheckExeName}');
end;

{ Nom bo'yicha o'ldirilmaydigan qoldiqlar - `<app>` dan ishga tushgan
  HAR jarayon. Asosan yetim `QtWebEngineProcess.exe` (ota jarayon /T siz
  o'lgan bo'lsa): u `_internal` dagi DLL'larni band qilib turadi va
  `_internal` ni ko'chirib bo'lmaydi. Nom bo'yicha o'ldirib bo'lmaydi -
  boshqa Qt dasturining WebEngine jarayonini ham urib yuborardi. }
procedure KillByPath;
var
  Code: Integer;
  AppPath: String;
begin
  AppPath := AddBackslash(ExpandConstant('{app}'));
  if not DirExists(AppPath) then
    Exit;
  StringChangeEx(AppPath, '''', '''''', True);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
       '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$d = ''' + AppPath + '''; ' +
       'Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($d, [System.StringComparison]::OrdinalIgnoreCase) } | ' +
       'Stop-Process -Force -ErrorAction SilentlyContinue"',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

{ Kiosk client oddiy yopilishni rad etadi - jarayonlar majburan to'xtatiladi.
  BIR XIL `.exe` dan uch xil jarayon bo'lishi mumkin: asosiy oyna,
  `--keyboard-hook` qulfi va `--watchdog` nazoratchisi. Nazoratchi asosiy
  jarayonni QAYTA ko'taradi, uni nom bo'yicha "birinchi" o'ldirib esa
  bo'lmaydi (nom bir xil) - shuning uchun `tasklist` hech narsa
  ko'rsatmaguncha takrorlanadi (~10 s gacha). /T - QtWebEngineProcess
  bolalari ham: ular `_internal` dagi DLL'larni band qiladi.
  Avval `schtasks /End`: Task Scheduler ishga tushirgan nusxa vazifa
  orqali ham to'xtatiladi.
  NARXI: majburan o'ldirilgan client o'chirilgan qo'shimcha monitorlarni
  QAYTARMAYDI (main._restore_monitors `finally` da). Yangilashni imtihon
  vaqtidan tashqarida o'tkazing. }
function StopClient: Boolean;
var
  Tries, Code: Integer;
  Sys: String;
begin
  Sys := ExpandConstant('{sys}');
  Exec(Sys + '\schtasks.exe', '/End /TN "{#TaskName}"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Tries := 0;
  while Tries < 15 do
  begin
    Tries := Tries + 1;
    Exec(Sys + '\taskkill.exe', '/F /T /IM {#AppExeName}', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Exec(Sys + '\taskkill.exe', '/F /T /IM {#CheckExeName}', '', SW_HIDE, ewWaitUntilTerminated, Code);
    if not ClientRunning then
      Break;
    Sleep(300);
  end;
  KillByPath;
  Result := not ClientRunning;
  if Result then
    Log('Client jarayonlari to''xtatildi (' + IntToStr(Tries) + ' urinish)')
  else
    Log('XATO: client jarayonlari hali ishlayapti');
end;

{ ---------------------------------------------------------------------- }
{ Microsoft Visual C++ runtime                                            }
{ ---------------------------------------------------------------------- }
{ Bundle VC++ runtime'ni o'zi bilan olib keladi (app-local, 14.44), ya'ni
  runtime YO'Q tizimda ham ishlaydi. Xavf - ESKI tizim nusxasi: ba'zi
  yuklovchilar (ctypes, add_dll_directory) System32 ni `_internal` dan
  OLDIN qidiradi va eski msvcp140 onnxruntime 1.2x da std::mutex
  qulashini beradi. 0 - yo'q, 1 - bor lekin 14.40 dan eski, 2 - yetarli. }
function RuntimeState(const RootKey: Integer): Integer;
var
  Installed, Major, Minor: Cardinal;
  Key: String;
begin
  Result := 0;
  Key := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  if not (RegQueryDWordValue(RootKey, Key, 'Installed', Installed) and (Installed = 1)) then
    Exit;
  Result := 1;
  if RegQueryDWordValue(RootKey, Key, 'Major', Major) and
     RegQueryDWordValue(RootKey, Key, 'Minor', Minor) and
     ((Major > 14) or ((Major = 14) and (Minor >= 40))) then
    Result := 2;
end;

function VcRuntimeState: Integer;
var
  A, B: Integer;
begin
  { x64 runtime kalitni registrning ikki ko'rinishidan biriga yozadi. }
  A := RuntimeState(HKLM64);
  B := RuntimeState(HKLM32);
  if A > B then Result := A else Result := B;
end;

{ Runtime xatosi o'rnatishni TO'SMAYDI - app-local nusxa bor; faqat
  ogohlantiriladi (silent rejimda log'ga) va davom etiladi. }
procedure EnsureVcRuntime;
var
  State: Integer;
#ifdef VcRedist
  Code: Integer;
#endif
begin
  State := VcRuntimeState;
  Log('VC++ runtime holati: ' + IntToStr(State) + ' (0 yo''q, 1 eski, 2 yetarli)');
  if State = 2 then
    Exit;
#ifdef VcRedist
  Log(CustomMessage('StatusVcRedist'));
  ExtractTemporaryFile('vc_redist.x64.exe');
  if not Exec(ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart', '',
              SW_HIDE, ewWaitUntilTerminated, Code) then
    Code := -1;
  Log('vc_redist chiqish kodi: ' + IntToStr(Code));
  { 0 - o'rnatildi, 1638 - yangiroq nusxa bor, 3010/1641 - qayta yuklash. }
  if (Code = 3010) or (Code = 1641) then
    VcRestartNeeded := True
  else if (Code <> 0) and (Code <> 1638) then
    SuppressibleMsgBox(FmtMessage(CustomMessage('WarnVcRedistFailed'), [IntToStr(Code)]),
                       mbInformation, MB_OK, IDOK);
#else
  { Runtime umuman yo'q - app-local nusxa yetadi, ogohlantirish shovqin bo'lardi. }
  if State = 1 then
    SuppressibleMsgBox(CustomMessage('WarnVcRuntimeOld'), mbInformation, MB_OK, IDOK);
#endif
end;

function NeedRestart: Boolean;
begin
  Result := VcRestartNeeded;
end;

{ ---------------------------------------------------------------------- }
{ Disk joyi                                                               }
{ ---------------------------------------------------------------------- }
{ Inno o'zi joyni faqat katalog sahifasida ko'rsatadi, silent rejimda va
  yangilashda (DisableDirPage=auto) tekshirmaydi. Yetmasa fayllar
  yarmida "disk to'ldi" bo'lardi. Eski versiya o'rnatish tugaguncha
  `_rollback` da turadi, ya'ni joy YANGI bundle uchun to'liq kerak.
  Zaxira 512 MB - log, WebEngine keshi va Windows'ning o'zi uchun. }
function CheckDiskSpace: String;
var
  Drive: String;
  FreeBytes, TotalBytes, Required: Int64;
begin
  Result := '';
  Drive := AddBackslash(ExtractFileDrive(ExpandConstant('{app}')));
  Required := (Int64({#BundleMB}) + 512) * 1024 * 1024;
  if not GetSpaceOnDisk64(Drive, FreeBytes, TotalBytes) then
  begin
    Log('Disk joyi o''qilmadi: ' + Drive + ' - tekshiruv o''tkazib yuborildi');
    Exit;
  end;
  Log('Disk ' + Drive + ': bo''sh ' + IntToStr(FreeBytes div (1024 * 1024)) +
      ' MB, kerak ' + IntToStr(Required div (1024 * 1024)) + ' MB');
  if FreeBytes < Required then
    { Satr `[` bilan boshlanmasin - Inno uni bo'lim sarlavhasi deb o'qiydi. }
    Result := FmtMessage(CustomMessage('ErrDiskSpace'), [IntToStr(Required div (1024 * 1024)),
                         IntToStr(FreeBytes div (1024 * 1024)), Drive]);
end;

{ ---------------------------------------------------------------------- }
{ Rollback: eski versiya zaxirasi                                         }
{ ---------------------------------------------------------------------- }
{ Inno rollback'i faqat O'ZI yozgan fayllarni qaytaradi: [InstallDelete]
  o'chirgan eski `_internal` qaytmaydi. Ilgari o'rnatish yarmida yiqilsa
  (disk, antivirus bloki, bekor qilish) mashinada eski `.exe` + yarim
  yangi `_internal` qolardi - client umuman ochilmasdi. Endi eski
  versiya O'CHIRILMAYDI, bir diskdagi `<app>\_rollback` ga KO'CHIRILADI
  (tez, joy talab qilmaydi) va yiqilishda DeinitializeSetup uni qaytaradi. }
function RollbackDir: String;
begin
  Result := ExpandConstant('{app}\_rollback');
end;

{ `<app>` ildizidagi, `_internal` bilan BIRGA almashadigan fayllar. }
function RootFile(const Index: Integer): String;
begin
  case Index of
    0: Result := '{#AppExeName}';
    1: Result := '{#CheckExeName}';
    2: Result := 'models_manifest.json';
    3: Result := 'tools\autostart.ps1';
  else
    Result := '';
  end;
end;

function BackupPrevious: String;
var
  App, Rb, Name: String;
  I: Integer;
begin
  Result := '';
  App := ExpandConstant('{app}');
  Rb := RollbackDir;
  if not DirExists(App + '\_internal') then
    Exit;   { yangi o'rnatish - qaytariladigan narsa yo'q }

  { Oldingi yiqilgan o'rnatishdan qolgan zaxira (elektr o'chishi) -
    joriy `_internal` undan yangiroq yoki teng. }
  if DirExists(Rb) and not DelTree(Rb, True, True, True) then
  begin
    Result := FmtMessage(CustomMessage('ErrRollbackPrepare'), [Rb]);
    Exit;
  end;
  ForceDirectories(Rb + '\tools');

  if not RenameFile(App + '\_internal', Rb + '\_internal') then
  begin
    Result := FmtMessage(CustomMessage('ErrRollbackPrepare'), [App + '\_internal']);
    Exit;
  end;
  RollbackArmed := True;
  for I := 0 to 3 do
  begin
    Name := RootFile(I);
    if FileExists(App + '\' + Name) and not RenameFile(App + '\' + Name, Rb + '\' + Name) then
    begin
      { Yarim ko'chirilgan holatda qolmaslik uchun darhol qaytaramiz. }
      Result := FmtMessage(CustomMessage('ErrRollbackPrepare'), [App + '\' + Name]);
      Exit;
    end;
  end;
  Log('Eski versiya zaxirada: ' + Rb);
end;

procedure RestorePrevious;
var
  App, Rb, Name: String;
  I: Integer;
begin
  App := ExpandConstant('{app}');
  Rb := RollbackDir;
  Log('O''rnatish yakunlanmadi - eski versiya qaytarilmoqda: ' + Rb);
  if DirExists(Rb + '\_internal') then
  begin
    DelTree(App + '\_internal', True, True, True);
    if not RenameFile(Rb + '\_internal', App + '\_internal') then
      Log('XATO: _internal qaytarilmadi, zaxira joyida qoldi: ' + Rb);
  end;
  for I := 0 to 3 do
  begin
    Name := RootFile(I);
    if FileExists(Rb + '\' + Name) then
    begin
      DeleteFile(App + '\' + Name);
      if not RenameFile(Rb + '\' + Name, App + '\' + Name) then
        Log('XATO: qaytarilmadi: ' + Name);
    end
    else if I = 2 then
      { Eski versiyada manifest yo'q edi - yangisi eski modellarga mos emas. }
      DeleteFile(App + '\' + Name);
  end;
  { Hammasi qaytgan bo'lsagina zaxira o'chiriladi. }
  if not DirExists(Rb + '\_internal') then
    DelTree(Rb, True, True, True);
end;

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

{ Faylga tegishdan OLDINGI hamma narsa shu yerda. Bo'sh bo'lmagan satr
  o'rnatishni TOZA to'xtatadi (kod 7): fayllar hali yozilmagan, eski
  versiya ishlaydigan holicha qoladi. Tartib: yon ta'sirsiz tekshiruv ->
  jarayonlar -> runtime -> eski versiyani zaxiraga. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := CheckDiskSpace;
  if Result <> '' then
  begin
    Log('XATO: ' + Result);
    Exit;
  end;

  if not StopClient then
  begin
    Result := FmtMessage(CustomMessage('ErrStillRunning'), ['{#AppExeName}']);
    Log('XATO: ' + Result);
    Exit;
  end;

  { Client to'xtagandan KEYIN: ishlab turgan jarayon msvcp140 ni band
    qilib turganda vc_redist qayta yuklashni (3010) talab qilardi. }
  EnsureVcRuntime;

  Result := BackupPrevious;
  if Result <> '' then
    Log('XATO: ' + Result);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { Bu nuqtada fayllar va uninstaller to'liq yozilgan (Inno bundan
      keyin rollback qilmaydi) - eski versiya zaxirasi endi kerak emas. }
    InstallFinished := True;
    if RollbackArmed then
      if not DelTree(RollbackDir, True, True, True) then
        Log('Zaxira to''liq o''chirilmadi (uninstall o''chiradi): ' + RollbackDir);
    WriteEnv;
    ConfigureAutostart;
  end;
end;

procedure DeinitializeSetup;
begin
  { Bekor qilish, disk to'lishi, fayl yozish xatosi - Inno o'z fayllarini
    qaytargandan keyin eski versiyani joyiga qo'yamiz. }
  if RollbackArmed and not InstallFinished then
    RestorePrevious;
end;

function InitializeUninstall: Boolean;
begin
  { Ishlab turgan jarayon fayllarni band qilsa, uninstall ularni "qayta
    yuklashda o'chirish" ga qoldirib, yarim o'chirilgan dastur qoldirardi.
    To'xtatib bo'lmasa - o'chirish umuman boshlanmaydi. }
  Result := StopClient;
  if not Result then
    SuppressibleMsgBox(FmtMessage(CustomMessage('ErrUninstallRunning'), ['{#AppExeName}']),
                       mbCriticalError, MB_OK, IDOK);
end;
