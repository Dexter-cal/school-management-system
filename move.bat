@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "APP_NAME=school-management-system"
set "EXPORT_DIR=exports"
set "STAMP=%DATE:~-4%%DATE:~4,2%%DATE:~7,2%-%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
set "STAMP=%STAMP: =0%"
set "STAGE=%TEMP%\%APP_NAME%-move-%STAMP%"

if not exist "%EXPORT_DIR%" mkdir "%EXPORT_DIR%"

echo.
echo School Management System Move Tool
echo ----------------------------------
echo 1. Build code-only ZIP for a new provider
echo 2. Build ZIP with media uploads
echo 3. Build ZIP with media and local SQLite database
echo 4. Build sensitive full ZIP with media, SQLite database, and .env
echo 5. Build TAR.GZ with media uploads
echo 6. Show provider migration checklist
echo.
set /p "CHOICE=Choose an option [1-6]: "

if "%CHOICE%"=="6" goto checklist
if "%CHOICE%"=="5" (
  set "FORMAT=tar"
  set "INCLUDE_MEDIA=1"
  set "INCLUDE_DB=0"
  set "INCLUDE_ENV=0"
  goto build
)
if "%CHOICE%"=="4" (
  set "FORMAT=zip"
  set "INCLUDE_MEDIA=1"
  set "INCLUDE_DB=1"
  set "INCLUDE_ENV=1"
  goto warn_sensitive
)
if "%CHOICE%"=="3" (
  set "FORMAT=zip"
  set "INCLUDE_MEDIA=1"
  set "INCLUDE_DB=1"
  set "INCLUDE_ENV=0"
  goto build
)
if "%CHOICE%"=="2" (
  set "FORMAT=zip"
  set "INCLUDE_MEDIA=1"
  set "INCLUDE_DB=0"
  set "INCLUDE_ENV=0"
  goto build
)
if "%CHOICE%"=="1" (
  set "FORMAT=zip"
  set "INCLUDE_MEDIA=0"
  set "INCLUDE_DB=0"
  set "INCLUDE_ENV=0"
  goto build
)

echo Invalid option.
exit /b 1

:warn_sensitive
echo.
echo WARNING: This package may contain secrets and real school data.
set /p "CONFIRM=Type YES to continue: "
if /I not "%CONFIRM%"=="YES" exit /b 1
goto build

:build
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"

robocopy "." "%STAGE%" /E ^
  /XD ".git" ".github" ".venv" "venv" "env" "ENV" "node_modules" "staticfiles" "__pycache__" "%EXPORT_DIR%" ^
  /XF "*.pyc" "*.pyo" "*.pyd" "*.log" "db.sqlite3-journal" "runserver_*.err" "runserver_*.out" "tmpstart*.err" "tmpstart*.out" "start_*.err" "start_*.out" "admin_probe.err" "admin_probe.out" "debug_index_script.js" "debug-test.html" "test-sidebar-render.html" "quick_test.py" "tmp_buildsidebar_test.js" "GRADING_SCALE_UI_GUIDE.md" "SYSTEM_ENHANCEMENTS.md" "school-management-system\school\settings.py" >nul

if errorlevel 8 (
  echo Failed to stage files.
  rmdir /s /q "%STAGE%" >nul 2>nul
  exit /b 1
)

if "%INCLUDE_MEDIA%"=="0" rmdir /s /q "%STAGE%\school-management-system\media" >nul 2>nul
if "%INCLUDE_DB%"=="0" del /q "%STAGE%\school-management-system\db.sqlite3" >nul 2>nul
if "%INCLUDE_ENV%"=="0" del /q "%STAGE%\school-management-system\.env" >nul 2>nul
if "%INCLUDE_ENV%"=="0" del /q "%STAGE%\.env" >nul 2>nul

(
  echo Built: %DATE% %TIME%
  echo Source: %CD%
  echo Include media: %INCLUDE_MEDIA%
  echo Include sqlite database: %INCLUDE_DB%
  echo Include env secrets: %INCLUDE_ENV%
  echo.
  echo After upload to a provider:
  echo 1. Set SECRET_KEY, DEBUG=False, ALLOWED_HOSTS, DATABASE_URL.
  echo 2. Run python manage.py migrate --noinput.
  echo 3. Run python manage.py collectstatic --noinput.
  echo 4. Run python manage.py bootstrap_superadmin only when needed.
  echo 5. Start gunicorn bjs_management.wsgi:application.
) > "%STAGE%\MOVE_MANIFEST.txt"

set "OUT=%EXPORT_DIR%\%APP_NAME%-%STAMP%"
if "%FORMAT%"=="tar" (
  tar -czf "%OUT%.tar.gz" -C "%STAGE%" .
  set "ARCHIVE=%OUT%.tar.gz"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%OUT%.zip' -Force"
  set "ARCHIVE=%OUT%.zip"
)

rmdir /s /q "%STAGE%" >nul 2>nul

echo.
echo Package created:
echo %ARCHIVE%
echo.
echo Keep sensitive packages private if you included .env or db.sqlite3.
exit /b 0

:checklist
echo.
echo Provider migration checklist
echo ----------------------------
echo 1. Create PostgreSQL on the new provider and copy DATABASE_URL.
echo 2. Set SECRET_KEY, DEBUG=False, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS if needed.
echo 3. Set email/SMS/mobile money/API credentials in provider environment variables.
echo 4. Upload or connect persistent media storage. Many free app disks are temporary and should not store school files.
echo 5. Deploy, then run migrations and collectstatic.
echo 6. Confirm login, payments, report cards, payroll dashboard, and parent portal.
echo.
exit /b 0
