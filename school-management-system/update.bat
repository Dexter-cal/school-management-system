@echo off
SETLOCAL EnableDelayedExpansion
SET SCRIPT_DIR=%~dp0
CD /d "%SCRIPT_DIR%"

echo Checking for local changes...
git diff --quiet --ignore-submodules --
if errorlevel 1 goto :dirty
git diff --cached --quiet --ignore-submodules --
if errorlevel 1 goto :dirty

for /f "delims=" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set BRANCH=%%i
if not defined BRANCH (
    echo Could not detect the current Git branch.
    goto :eof
)

echo Fetching updates from origin/%BRANCH%...
git fetch origin %BRANCH%
if errorlevel 1 (
    echo.
    echo Failed to fetch updates from GitHub.
    goto :eof
)

echo Pulling latest changes...
git pull --ff-only origin %BRANCH%
if errorlevel 1 (
    echo.
    echo Update failed. Resolve the Git issue above, then try again.
    goto :eof
)

echo Refreshing the local environment...
python setup_env.py
if errorlevel 1 (
    echo.
    echo Code updated, but environment refresh failed. Check the output above.
    goto :eof
)

echo.
echo Update complete. You can now run start.bat.
goto :eof

:dirty
echo.
echo Local changes were detected, so update.bat stopped before pulling from GitHub.
echo Commit or stash your changes first, then run update.bat again.
