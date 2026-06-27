@echo off
chcp 65001 >nul
title AI Dubbing Studio - 1-Click Installer
color 0B

echo ===================================================
echo    CHUONG TRINH CAI DAT VA CHAY AI DUBBING STUDIO
echo ===================================================
echo.

echo Kiem tra Docker Engine...
docker -v >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [LOI] Khong tim thay Docker! He thong yeu cau Docker de hoat dong.
    echo Vui long cai dat Docker Desktop tai: https://www.docker.com/products/docker-desktop/
    echo Sau khi cai dat xong, hay khoi dong lai may tinh va mo lai file nay.
    pause
    exit /b
)
echo [OK] Docker da san sang.
echo.

echo Tien hanh Build va chay toan bo he thong (AI, Backend, Frontend)...
echo Qua trinh nay co the mat tu 5-15 phut o lan chay dau tien de tai AI Models.
echo Vui long khong tat cua so nay!
echo.

docker-compose up -d --build

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [LOI] Qua trinh khoi dong Docker Compose gap loi. Vui long kiem tra log o tren.
    pause
    exit /b
)

echo.
echo ===================================================
echo [THANH CONG] He thong da khoi dong hoan tat!
echo ===================================================
echo.
echo - Truoc khi su dung, he thong se can khoang 1 phut de bat cac AI Model.
echo - Vui long truy cap trinh duyet cua ban o dia chi:
echo   http://localhost:5173
echo.
echo De tat he thong sau nay, ban co the chay lenh: docker-compose down
echo De khoi dong lai sau nay, ban chi can chay lai file nay.
echo.
pause
