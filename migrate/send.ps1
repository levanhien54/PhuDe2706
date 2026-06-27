<#
.SYNOPSIS
  Gửi toàn bộ dự án (kể cả models/) sang server qua croc — P2P, xuyên NAT, đa luồng, có resume.

.DESCRIPTION
  Chạy script này TRÊN MÁY NGUỒN (máy hiện tại). Nó dọn các thư mục tái tạo được
  (data/temp, data/output, node_modules, __pycache__) rồi croc send thư mục dự án.
  croc in ra một "code phrase" — đọc nó cho người nhận để chạy migrate/receive trên server.

.PARAMETER Clean
  Dọn các thư mục tái tạo được trước khi gửi (khuyến nghị, giảm dung lượng).

.PARAMETER IncludeGit
  Gửi cả thư mục .git (giữ lịch sử). Mặc định loại trừ để gọn — code đã có trên GitHub.

.EXAMPLE
  .\migrate\send.ps1 -Clean
#>
param(
    [switch]$Clean,
    [switch]$IncludeGit
)

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $PSScriptRoot   # thư mục gốc dự án (cha của migrate/)

# --- 1. Kiểm tra croc ---
$croc = Get-Command croc -ErrorAction SilentlyContinue
if (-not $croc) {
    Write-Host "croc chưa được cài. Cài bằng một trong các cách:" -ForegroundColor Yellow
    Write-Host "  winget install schollz.croc"
    Write-Host "  scoop install croc"
    Write-Host "  choco install croc"
    Write-Host "Hoặc tải binary: https://github.com/schollz/croc/releases"
    exit 1
}
Write-Host "croc: $($croc.Source)" -ForegroundColor Green

# --- 2. Dọn các thư mục tái tạo được ---
$regen = @(
    "data\temp", "data\output",
    "frontend\node_modules"
)
if ($Clean) {
    foreach ($r in $regen) {
        $p = Join-Path $proj $r
        if (Test-Path $p) {
            Write-Host "Dọn: $r" -ForegroundColor DarkGray
            Get-ChildItem -Path $p -Force -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -ne ".gitkeep" } |
                Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    # __pycache__ rải rác
    Get-ChildItem -Path $proj -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "Bỏ qua dọn dẹp (thêm -Clean để dọn data/temp, output, node_modules)." -ForegroundColor Yellow
}

# --- 3. Báo dung lượng sẽ gửi ---
$sizeGB = [math]::Round((Get-ChildItem $proj -Recurse -Force -File -ErrorAction SilentlyContinue |
            Measure-Object Length -Sum).Sum / 1GB, 2)
Write-Host "Tổng dung lượng dự án: ${sizeGB} GB" -ForegroundColor Cyan

# --- 4. croc send ---
# --no-compress: models là binary đã nén sẵn (safetensors/bin) -> nén lại tốn CPU, không lợi.
# croc tự dùng nhiều luồng + resume khi đứt kết nối.
$env:CROC_SECRET = ""   # dùng code phrase ngẫu nhiên do croc sinh
Write-Host "`nBắt đầu gửi. Đọc 'code phrase' bên dưới cho người nhận:`n" -ForegroundColor Green

if ($IncludeGit) {
    croc send --no-compress "$proj"
} else {
    # Gửi từng mục con để bỏ qua .git mà không cần tar
    $items = Get-ChildItem $proj -Force |
        Where-Object { $_.Name -ne ".git" } |
        Select-Object -ExpandProperty FullName
    croc send --no-compress @items
}
