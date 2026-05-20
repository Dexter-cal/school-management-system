@echo off
SETLOCAL EnableDelayedExpansion
SET SCRIPT_DIR=%~dp0
CD /d "%SCRIPT_DIR%"

echo Running automatic environment setup and migration helper...
python setup_env.py --serve
if errorlevel 1 (
    echo.
    echo Setup failed. Check the output above for details.
    goto :eof
)

echo Setup completed successfully.
