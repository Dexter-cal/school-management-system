@echo off
setlocal

if "%PORT%"=="" set PORT=8000
if "%WEB_CONCURRENCY%"=="" set WEB_CONCURRENCY=3

echo Starting portable Django deployment...
echo Port: %PORT%
echo Workers: %WEB_CONCURRENCY%

if /I not "%SKIP_MIGRATIONS%"=="True" (
    echo Applying database migrations...
    python manage.py migrate --noinput
    if errorlevel 1 exit /b %errorlevel%
) else (
    echo Skipping migrations because SKIP_MIGRATIONS=True
)

if /I not "%SKIP_COLLECTSTATIC%"=="True" (
    echo Collecting static files...
    python manage.py collectstatic --noinput
    if errorlevel 1 exit /b %errorlevel%
) else (
    echo Skipping collectstatic because SKIP_COLLECTSTATIC=True
)

if /I "%BOOTSTRAP_SUPERADMIN%"=="True" (
    echo Bootstrapping super admin if needed...
    python manage.py bootstrap_superadmin
    if errorlevel 1 exit /b %errorlevel%
)

echo Launching Gunicorn...
gunicorn bjs_management.wsgi:application --bind 0.0.0.0:%PORT% --workers %WEB_CONCURRENCY%
