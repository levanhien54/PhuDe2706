@echo off
chcp 65001 >nul
title Dong goi AI Dubbing Offline (Export)
color 0E

echo ===================================================
echo   DONG GOI HE THONG VA AI MODELS THANH BAN OFFLINE
echo ===================================================
echo.
echo Luu y: 
echo 1. Ban nen mo he thong chay it nhat 1 lan tren may nay de AI tai cac models 
echo    ve thu muc ./models truoc khi thuc hien dong goi.
echo 2. Qua trinh nay se nen cac phan mem thanh file offline_images.tar
echo    File nay se kha nang (co the len den 10-15GB) va ton 5-10 phut.
echo.
pause

echo.
echo [1/2] Dang dong goi Docker Images... (Vui long doi)
docker save -o offline_images.tar ai_dubbing_orchestrator ai_dubbing_frontend ollama/ollama:latest ahmetkca/whisperx-api:latest xserrat/facebook-demucs:latest mikan/gpt-sovits-api:latest ghcr.io/debpalash/omnivoice-studio:latest

IF %ERRORLEVEL% NEQ 0 (
    echo [LOI] Khong the luu Docker Images. Vui long kiem tra xem Docker da bat va cac image co ton tai khong.
    pause
    exit /b
)

echo [2/2] Da dong goi thanh cong!
echo.
echo ===================================================
echo HUONG DAN TIEP THEO:
echo 1. Bay gio, toan bo he thong da duoc dong goi vao tệp offline_images.tar
echo    va cac Model AI nam san trong thu muc "models".
echo 2. Ban hay COPY TOAN BO thu muc "PhuDe27.06" nay (bang USB hoac o cung ngoai)
echo    sang bat ky may tinh moi nao.
echo 3. O may tinh moi, chi can chay file "install_offline.bat"
echo ===================================================
pause
