@echo off
rem ==========================================================================
rem Proctoring Client: CPU nashri - faqat .exe (dist\cpu\ProctoringClient)
rem
rem Istalgan katalogdan ishlaydi (yo'llar shu faylning joyidan olinadi).
rem Qo'shimcha build.ps1 parametrlari uzatiladi, masalan:
rem   build-cpu.bat -Clean
rem   build-cpu.bat -EnvFile installer\toshkent.env
rem Barcha parametrlar: installer\README.md
rem ==========================================================================
setlocal
set "CLIENT_DIR=%~dp0.."
pushd "%CLIENT_DIR%" || (echo XATO: client katalogi topilmadi: %CLIENT_DIR% & exit /b 1)

powershell -NoProfile -ExecutionPolicy Bypass -File "installer\build.ps1" -Cpu -SkipInstaller %*
set "CODE=%ERRORLEVEL%"
popd

echo.
if not "%CODE%"=="0" goto :failed
echo TAYYOR: CPU nashri - faqat .exe (dist\cpu\ProctoringClient)
goto :done
:failed
echo XATO: build yiqildi, kod %CODE%
:done

exit /b %CODE%
