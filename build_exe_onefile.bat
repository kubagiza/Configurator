@echo off
setlocal

cd /d "%~dp0"

echo.
echo === Budowanie pojedynczego pliku EXE ===
echo.

python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt

if errorlevel 1 (
    echo.
    echo Nie udalo sie zainstalowac wymaganych bibliotek do builda.
    pause
    exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name ConfigSensor ^
    --icon "app_icon.ico" ^
    --add-data "images;images" ^
    konfigurator_sensorow_silownika.py

if errorlevel 1 (
    echo.
    echo Build zakonczyl sie bledem.
    pause
    exit /b 1
)

echo.
echo Gotowe. Plik EXE znajduje sie w folderze dist\ConfigSensor.exe
echo.
pause
