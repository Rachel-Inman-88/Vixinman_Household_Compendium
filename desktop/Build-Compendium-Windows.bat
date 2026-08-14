@echo off
REM ============================================================
REM  Build Compendium Desktop (run this once on a Windows PC that
REM  has Python installed -- the same Python you use to run the
REM  app with "python app.py").
REM
REM  Just double-click this file. When it finishes, the app is
REM  in the  dist\Compendium  folder -- zip that folder and send it
REM  to your team.
REM ============================================================
setlocal

REM Move to the repository root (this script lives in \desktop).
cd /d "%~dp0.."

echo.
echo [1/3] Checking Python...
where py >nul 2>nul && (set "PY=py") || (set "PY=python")
%PY% --version || (
  echo.
  echo Could not find Python. Install it from https://www.python.org/downloads/
  echo ^(check "Add Python to PATH" during install^), then run this again.
  pause
  exit /b 1
)

echo.
echo [2/4] Installing the packaging tools ^(one-time, needs internet^)...
%PY% -m pip install --upgrade pip
%PY% -m pip install --upgrade pyinstaller flask
if errorlevel 1 (
  echo.
  echo Something went wrong installing the tools. Check your internet
  echo connection and try again.
  pause
  exit /b 1
)

echo.
echo [3/4] Clearing the previous build...
REM A running Compendium locks its own files, which makes the rebuild fail with
REM "Access is denied". Close any open copy first, then wipe the old output.
taskkill /F /IM Compendium.exe >nul 2>nul
rmdir /S /Q dist  >nul 2>nul
rmdir /S /Q build >nul 2>nul
if exist "dist\Compendium" (
  echo.
  echo Could not remove the old  dist\Compendium  folder -- something still has a
  echo file open in it. Please:
  echo    1. CLOSE any open Compendium window ^(the black console window^).
  echo    2. Close any Explorer window showing the  dist\Compendium  folder.
  echo    3. Run this build again.
  pause
  exit /b 1
)

echo.
echo [4/4] Building Compendium.exe ^(this takes a few minutes^)...
%PY% -m PyInstaller --noconfirm --clean desktop\compendium.spec
if errorlevel 1 (
  echo.
  echo The build failed. Copy the red text above and send it to Claude.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  DONE!  Your app is here:   dist\Compendium\
echo.
echo  Next: right-click the  dist\Compendium  folder, choose
echo  "Send to -^> Compressed (zipped) folder", and share that
echo  zip with your team. See desktop\README-DESKTOP.md.
echo ============================================================
echo.
pause
