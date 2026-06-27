@echo off
chcp 65001 >nul
title Cai dat AI Dubbing Offline (Install)
color 0B

echo ===================================================
echo     CAI DAT HE THONG AI DUBBING (OFFLINE MODE)
echo ===================================================
echo.

docker -v >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [LOI] Khong tim thay Docker!
    echo Van can cai dat Docker Desktop vao may nay: https://www.docker.com/products/docker-desktop/
    pause
    exit /b
)

IF NOT EXIST "offline_images.tar" (
    echo [LOI] Khong tim thay file offline_images.tar. Ban da chay file export_offline o may goc chua?
    pause
    exit /b
)

echo [1/2] Dang nap cac Docker Images vao may (Khong can mang)...
echo Thao tac nay ton tu 2-5 phut tuy toc do o cung.
docker load -i offline_images.tar

echo.
echo [2/2] Khoi dong he thong...
docker-compose up -d

echo.
echo ===================================================
echo [THANH CONG] He thong da khoi dong hoan tat!
echo Khong he can internet de tai models nua.
echo ===================================================
echo.
echo Vui long truy cap trinh duyet o dia chi:
echo http://localhost:5173
echo.
pause
