<#
  GUI đơn giản cho việc di chuyển dự án qua croc (P2P, xuyên NAT, resume).
  Double-click migrate\Migrate.bat để mở. Không cần cài gì ngoài croc.
#>
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$proj = Split-Path -Parent $PSScriptRoot   # gốc dự án (cha của migrate/)

# ---------- Helpers ----------
function Get-CrocPath {
    $c = Get-Command croc -ErrorAction SilentlyContinue
    if ($c) { return $c.Source } else { return $null }
}

$script:proc = $null

function Append-Log([System.Windows.Forms.TextBox]$box, [string]$text) {
    if ([string]::IsNullOrEmpty($text)) { return }
    $box.Invoke([Action]{ $box.AppendText($text + "`r`n") }) | Out-Null
}

function Start-CrocProcess {
    param(
        [string]$Arguments,
        [string]$WorkDir,
        [System.Windows.Forms.TextBox]$LogBox,
        [System.Windows.Forms.Label]$CodeLabel
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "croc"
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $WorkDir
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $script:proc = New-Object System.Diagnostics.Process
    $script:proc.StartInfo = $psi
    $script:proc.EnableRaisingEvents = $true

    $handler = {
        $data = $EventArgs.Data
        if ($data) {
            Append-Log $Event.MessageData.Log $data
            # Bắt code phrase: dòng kiểu "croc <code>" hoặc "Code is: <code>"
            $m = [regex]::Match($data, '(?:Code is:\s*|croc\s+)([0-9]+-[a-z]+-[a-z]+-[a-z]+)')
            if ($m.Success) {
                $code = $m.Groups[1].Value
                $lbl = $Event.MessageData.Code
                $lbl.Invoke([Action]{
                    $lbl.Text = "CODE: $code   (đã copy vào clipboard)"
                }) | Out-Null
                Set-Clipboard -Value $code
            }
        }
    }
    $md = @{ Log = $LogBox; Code = $CodeLabel }
    Register-ObjectEvent -InputObject $script:proc -EventName OutputDataReceived -Action $handler -MessageData $md | Out-Null
    Register-ObjectEvent -InputObject $script:proc -EventName ErrorDataReceived  -Action $handler -MessageData $md | Out-Null

    $script:proc.Start() | Out-Null
    $script:proc.BeginOutputReadLine()
    $script:proc.BeginErrorReadLine()
}

# ---------- Form ----------
$form = New-Object System.Windows.Forms.Form
$form.Text = "Di chuyển dự án PhuDe27.06"
$form.Size = New-Object System.Drawing.Size(640, 620)
$form.StartPosition = "CenterScreen"
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

# --- Trạng thái croc ---
$lblCroc = New-Object System.Windows.Forms.Label
$lblCroc.Location = New-Object System.Drawing.Point(15, 12)
$lblCroc.Size = New-Object System.Drawing.Size(470, 22)
$form.Controls.Add($lblCroc)

$btnInstall = New-Object System.Windows.Forms.Button
$btnInstall.Text = "Cài croc"
$btnInstall.Location = New-Object System.Drawing.Point(495, 9)
$btnInstall.Size = New-Object System.Drawing.Size(110, 26)
$form.Controls.Add($btnInstall)

function Refresh-CrocStatus {
    $p = Get-CrocPath
    if ($p) {
        $lblCroc.Text = "✓ croc đã cài: $p"
        $lblCroc.ForeColor = [System.Drawing.Color]::Green
        $btnInstall.Enabled = $false
    } else {
        $lblCroc.Text = "✗ Chưa có croc — bấm 'Cài croc' (cần winget)"
        $lblCroc.ForeColor = [System.Drawing.Color]::Firebrick
        $btnInstall.Enabled = $true
    }
}
$btnInstall.Add_Click({
    $lblCroc.Text = "Đang cài croc qua winget..."
    Start-Process -FilePath "winget" -ArgumentList "install","schollz.croc","--accept-source-agreements","--accept-package-agreements" -Wait -NoNewWindow
    Refresh-CrocStatus
})

# ===================== GỬI =====================
$grpSend = New-Object System.Windows.Forms.GroupBox
$grpSend.Text = "GỬI — chạy trên máy nguồn (máy này)"
$grpSend.Location = New-Object System.Drawing.Point(15, 45)
$grpSend.Size = New-Object System.Drawing.Size(590, 165)
$form.Controls.Add($grpSend)

$chkClean = New-Object System.Windows.Forms.CheckBox
$chkClean.Text = "Dọn data/temp, output, node_modules trước khi gửi (khuyến nghị)"
$chkClean.Location = New-Object System.Drawing.Point(15, 25)
$chkClean.Size = New-Object System.Drawing.Size(560, 22)
$chkClean.Checked = $true
$grpSend.Controls.Add($chkClean)

$chkGit = New-Object System.Windows.Forms.CheckBox
$chkGit.Text = "Gửi cả .git (giữ lịch sử) — mặc định bỏ vì code đã trên GitHub"
$chkGit.Location = New-Object System.Drawing.Point(15, 50)
$chkGit.Size = New-Object System.Drawing.Size(560, 22)
$grpSend.Controls.Add($chkGit)

$btnSend = New-Object System.Windows.Forms.Button
$btnSend.Text = "▶ Bắt đầu gửi"
$btnSend.Location = New-Object System.Drawing.Point(15, 80)
$btnSend.Size = New-Object System.Drawing.Size(150, 34)
$btnSend.BackColor = [System.Drawing.Color]::FromArgb(46, 160, 67)
$btnSend.ForeColor = [System.Drawing.Color]::White
$grpSend.Controls.Add($btnSend)

$lblCode = New-Object System.Windows.Forms.Label
$lblCode.Text = "CODE: (sẽ hiện ở đây — đọc cho server)"
$lblCode.Location = New-Object System.Drawing.Point(180, 84)
$lblCode.Size = New-Object System.Drawing.Size(395, 28)
$lblCode.Font = New-Object System.Drawing.Font("Consolas", 11, [System.Drawing.FontStyle]::Bold)
$lblCode.ForeColor = [System.Drawing.Color]::DarkBlue
$grpSend.Controls.Add($lblCode)

$lblSize = New-Object System.Windows.Forms.Label
$lblSize.Location = New-Object System.Drawing.Point(15, 130)
$lblSize.Size = New-Object System.Drawing.Size(560, 22)
$lblSize.ForeColor = [System.Drawing.Color]::DimGray
$grpSend.Controls.Add($lblSize)

$btnSend.Add_Click({
    if (-not (Get-CrocPath)) { [System.Windows.Forms.MessageBox]::Show("Chưa có croc. Bấm 'Cài croc' trước."); return }
    $btnSend.Enabled = $false
    $lblCode.Text = "Đang chuẩn bị..."

    # Dọn
    if ($chkClean.Checked) {
        foreach ($r in @("data\temp","data\output","frontend\node_modules")) {
            $p = Join-Path $proj $r
            if (Test-Path $p) {
                Get-ChildItem $p -Force -ErrorAction SilentlyContinue |
                    Where-Object { $_.Name -ne ".gitkeep" } |
                    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        Get-ChildItem $proj -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }

    # Dung lượng
    $sz = [math]::Round((Get-ChildItem $proj -Recurse -Force -File -ErrorAction SilentlyContinue |
            Measure-Object Length -Sum).Sum / 1GB, 2)
    $lblSize.Text = "Tổng dung lượng gửi: ${sz} GB — giữ cửa sổ mở đến khi xong."

    # Danh sách mục (bỏ .git nếu không chọn)
    $items = Get-ChildItem $proj -Force |
        Where-Object { $chkGit.Checked -or $_.Name -ne ".git" } |
        ForEach-Object { '"' + $_.FullName + '"' }
    $args = "send --no-compress " + ($items -join " ")
    Append-Log $txtLog "> croc $args`r`n"
    Start-CrocProcess -Arguments $args -WorkDir $proj -LogBox $txtLog -CodeLabel $lblCode
})

# ===================== NHẬN =====================
$grpRecv = New-Object System.Windows.Forms.GroupBox
$grpRecv.Text = "NHẬN — chạy trên server"
$grpRecv.Location = New-Object System.Drawing.Point(15, 218)
$grpRecv.Size = New-Object System.Drawing.Size(590, 110)
$form.Controls.Add($grpRecv)

$lblCodeIn = New-Object System.Windows.Forms.Label
$lblCodeIn.Text = "Code phrase:"
$lblCodeIn.Location = New-Object System.Drawing.Point(15, 28)
$lblCodeIn.Size = New-Object System.Drawing.Size(85, 22)
$grpRecv.Controls.Add($lblCodeIn)

$txtCode = New-Object System.Windows.Forms.TextBox
$txtCode.Location = New-Object System.Drawing.Point(100, 25)
$txtCode.Size = New-Object System.Drawing.Size(220, 24)
$grpRecv.Controls.Add($txtCode)

$lblDest = New-Object System.Windows.Forms.Label
$lblDest.Text = "Thư mục lưu:"
$lblDest.Location = New-Object System.Drawing.Point(15, 62)
$lblDest.Size = New-Object System.Drawing.Size(85, 22)
$grpRecv.Controls.Add($lblDest)

$txtDest = New-Object System.Windows.Forms.TextBox
$txtDest.Location = New-Object System.Drawing.Point(100, 59)
$txtDest.Size = New-Object System.Drawing.Size(370, 24)
$txtDest.Text = "C:\PhuDe27.06"
$grpRecv.Controls.Add($txtDest)

$btnBrowse = New-Object System.Windows.Forms.Button
$btnBrowse.Text = "..."
$btnBrowse.Location = New-Object System.Drawing.Point(476, 58)
$btnBrowse.Size = New-Object System.Drawing.Size(40, 26)
$grpRecv.Controls.Add($btnBrowse)
$btnBrowse.Add_Click({
    $fb = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($fb.ShowDialog() -eq "OK") { $txtDest.Text = $fb.SelectedPath }
})

$btnRecv = New-Object System.Windows.Forms.Button
$btnRecv.Text = "▼ Bắt đầu nhận"
$btnRecv.Location = New-Object System.Drawing.Point(330, 22)
$btnRecv.Size = New-Object System.Drawing.Size(150, 30)
$btnRecv.BackColor = [System.Drawing.Color]::FromArgb(31, 111, 235)
$btnRecv.ForeColor = [System.Drawing.Color]::White
$grpRecv.Controls.Add($btnRecv)

$btnRecv.Add_Click({
    if (-not (Get-CrocPath)) { [System.Windows.Forms.MessageBox]::Show("Chưa có croc. Bấm 'Cài croc' trước."); return }
    $code = $txtCode.Text.Trim()
    if (-not $code) { [System.Windows.Forms.MessageBox]::Show("Nhập code phrase."); return }
    $dest = $txtDest.Text.Trim()
    if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }
    $btnRecv.Enabled = $false
    Append-Log $txtLog "> croc --yes $code  (vào $dest)`r`n"
    Start-CrocProcess -Arguments "--yes $code" -WorkDir $dest -LogBox $txtLog -CodeLabel $lblCode
})

# ===================== LOG =====================
$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Location = New-Object System.Drawing.Point(15, 338)
$txtLog.Size = New-Object System.Drawing.Size(590, 220)
$txtLog.Multiline = $true
$txtLog.ScrollBars = "Vertical"
$txtLog.ReadOnly = $true
$txtLog.BackColor = [System.Drawing.Color]::Black
$txtLog.ForeColor = [System.Drawing.Color]::LightGray
$txtLog.Font = New-Object System.Drawing.Font("Consolas", 8.5)
$form.Controls.Add($txtLog)

$form.Add_Shown({ Refresh-CrocStatus })
$form.Add_FormClosing({
    if ($script:proc -and -not $script:proc.HasExited) {
        try { $script:proc.Kill() } catch {}
    }
    Get-EventSubscriber | Unregister-Event -ErrorAction SilentlyContinue
})

[void]$form.ShowDialog()
