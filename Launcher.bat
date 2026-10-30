@echo off
title WestBroadcast Encoder - Launcher

set IS_FR=0
reg query "HKCU\Control Panel\International" /v LocaleName 2>nul | findstr /i "fr" >nul
if not errorlevel 1 set IS_FR=1

set PY_CMD=
python --version >nul 2>&1
if not errorlevel 1 set PY_CMD=python

if "%PY_CMD%"=="" (
    py --version >nul 2>&1
    if not errorlevel 1 set PY_CMD=py
)

if "%IS_FR%"=="1" (
    echo =======================================================
    echo    PREPARATION DE L'ENCODEUR ET VERIFICATION REQUISE
    echo =======================================================
    echo.
    echo Verification des fichiers requis... et si manquants, installation des dependances.
    echo - Cette etape peut prendre quelques instants lors du tout premier lancement.
    echo.
) else (
    echo ======================================================
    echo    PREPARING THE ENCODER AND VERIFYING REQUIREMENTS
    echo ======================================================
    echo.
    echo Verification of required files... and if missing, installation of dependencies.
    echo - This step may take a few moments when launching for the first time.
    echo.
)

if "%PY_CMD%"=="" (
    echo.
    if "%IS_FR%"=="1" (
        echo [ERREUR] Python n'est pas installe ou n'est pas present dans le PATH Windows.
        echo Veuillez installer Python en cochant la case "Add Python to PATH" lors de l'installation.
    ) else (
        echo [ERROR] Python is not installed or not added to the Windows PATH.
        echo Please install Python and make sure to check "Add Python to PATH" in the setup wizard.
    )
    echo.
    pause
    exit /b 1
)

%PY_CMD% -c "import flask, flask_socketio, numpy, sounddevice, psutil, requests" >nul 2>&1
if errorlevel 1 (
    %PY_CMD% -m pip install --quiet --no-warn-script-location flask==3.0.3 flask-socketio==5.3.6 numpy sounddevice psutil requests
)

if "%IS_FR%"=="1" (
    echo.
    echo =============================================================
    echo    LANCEMENT DE L'ENCODEUR EN COURS... VEUILLEZ PATIENTER.
    echo =============================================================
    echo.
    echo IMPORTANT : Vous devez garder ce terminal ouvert, sinon le logiciel se fermera !
    echo.
) else (
    echo.
    echo ================================================
    echo    ENCODER LAUNCH IN PROGRESS... PLEASE WAIT.
    echo ================================================
    echo.
    echo IMPORTANT: You must keep this terminal open, otherwise the software will close!
    echo.
)

%PY_CMD% app.py

echo.
pause