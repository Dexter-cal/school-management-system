@echo off
SETLOCAL EnableDelayedExpansion
SET SCRIPT_DIR=%~dp0
CD /d "%SCRIPT_DIR%"

echo Checking for Python virtual environment...
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment. Ensure Python is installed and in PATH.
        goto :eof
    )
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate virtual environment.
    goto :eof
)

echo Installing/Upgrading dependencies from requirements.txt...
set PIP_DISABLE_PIP_VERSION_CHECK=1
pip install -q -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    goto :eof
)

echo Checking for .env file...
if not exist .env (
    echo .env file not found. Creating a template .env file.
    for /f "delims=" %%s in ('python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"') do set GENERATED_SECRET_KEY=%%s
    echo SECRET_KEY=!GENERATED_SECRET_KEY! > .env
    echo DEBUG=True >> .env
    echo ALLOWED_HOSTS=127.0.0.1,localhost >> .env
    echo TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx >> .env
    echo TWILIO_AUTH_TOKEN=your_auth_token >> .env
    echo TWILIO_PHONE_NUMBER=+15017122661 >> .env
    echo DEFAULT_FROM_EMAIL=webmaster@bitendejuniorschool.com >> .env
    echo.
    echo IMPORTANT: Please edit the .env file with your production credentials, Twilio settings, and allowed hosts.
    echo Then run start.bat again.
    goto :eof
)

rem Fix a common dev-only migration inconsistency where socialaccount migrations were applied
rem before django.contrib.sites in an existing SQLite DB.
echo Fixing django.contrib.sites migration history (SQLite dev helper)...
python manage.py fix_sites_migration

echo Running Django migrations...
echo Checking for missing migrations...
python manage.py makemigrations --check --dry-run >nul
if errorlevel 1 (
    echo Missing migrations detected. Run: python manage.py makemigrations school
    goto :eof
)
python manage.py migrate --noinput
if errorlevel 1 (
    echo Failed to run migrations.
    goto :eof
)

echo Bootstrapping default Super Admin (if enabled in .env)...
python manage.py bootstrap_superadmin

echo Starting Django development server...
echo Access the application at http://127.0.0.1:8000/ or http://localhost:8000/
python manage.py runserver
