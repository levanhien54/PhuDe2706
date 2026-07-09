# =============================================================================
# Regression tests for the shared hardware-check decision logic (hardware_check.ps1).
# Pure functions only -- no side effects -- so they run anywhere (no GPU/network needed).
#
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File tests\test_hardware_check.ps1
# Exit: 0 = all pass, 1 = a failure (or the module is missing).
# =============================================================================

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$module = Join-Path (Split-Path -Parent $here) 'hardware_check.ps1'

if (-not (Test-Path $module)) {
    Write-Host "RED: hardware_check.ps1 does not exist yet ($module)" -ForegroundColor Red
    exit 1
}
. $module

$fail = 0
function Assert-Eq($label, $got, $want) {
    if ("$got" -eq "$want") {
        Write-Host "  [PASS] $label" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $label -- got '$got', want '$want'" -ForegroundColor Red
        $script:fail++
    }
}

Write-Host "`n== VRAM severity (16 GB min, 24 GB profile boundary) ==" -ForegroundColor Cyan
Assert-Eq 'VRAM 8000  sev'  (Get-VramSeverity 8000).Severity  'FAIL'
Assert-Eq 'VRAM 8000  code' (Get-VramSeverity 8000).Code      'VRAM_LOW'
Assert-Eq 'VRAM 15999 sev'  (Get-VramSeverity 15999).Severity 'FAIL'
Assert-Eq 'VRAM 16000 sev'  (Get-VramSeverity 16000).Severity 'PASS'
Assert-Eq 'VRAM 16000 code' (Get-VramSeverity 16000).Code     'VRAM_16GB'
Assert-Eq 'VRAM 23999 code' (Get-VramSeverity 23999).Code     'VRAM_16GB'
Assert-Eq 'VRAM 24000 sev'  (Get-VramSeverity 24000).Severity 'PASS'
Assert-Eq 'VRAM 24000 code' (Get-VramSeverity 24000).Code     'VRAM_24GB'
Assert-Eq 'VRAM 48000 sev'  (Get-VramSeverity 48000).Severity 'PASS'
Assert-Eq 'VRAM 48000 code' (Get-VramSeverity 48000).Code     'VRAM_24GB'

Write-Host "`n== Driver severity (>= 452.39 for CUDA 11.8) ==" -ForegroundColor Cyan
Assert-Eq 'Driver 452.38 sev'  (Get-DriverSeverity '452.38').Severity 'WARN'
Assert-Eq 'Driver 452.38 code' (Get-DriverSeverity '452.38').Code     'DRIVER_OLD'
Assert-Eq 'Driver 452.39 sev'  (Get-DriverSeverity '452.39').Severity 'PASS'
Assert-Eq 'Driver 452.39 code' (Get-DriverSeverity '452.39').Code     'DRIVER_OK'
Assert-Eq 'Driver 581.57 sev'  (Get-DriverSeverity '581.57').Severity 'PASS'
Assert-Eq 'Driver bad    sev'  (Get-DriverSeverity 'not-a-version').Severity 'WARN'
Assert-Eq 'Driver bad    code' (Get-DriverSeverity 'not-a-version').Code 'DRIVER_UNREADABLE'

Write-Host "`n== Python severity (3.10 ideal; 3.11/3.12 warn; <3.10 or >=3.13 fail) ==" -ForegroundColor Cyan
Assert-Eq 'Python 3.9  sev'  (Get-PythonSeverity '3.9').Severity  'FAIL'
Assert-Eq 'Python 3.9  code' (Get-PythonSeverity '3.9').Code      'PY_OLD'
Assert-Eq 'Python 3.10 sev'  (Get-PythonSeverity '3.10').Severity 'PASS'
Assert-Eq 'Python 3.10 code' (Get-PythonSeverity '3.10').Code     'PY_OK'
Assert-Eq 'Python 3.11 sev'  (Get-PythonSeverity '3.11').Severity 'WARN'
Assert-Eq 'Python 3.11 code' (Get-PythonSeverity '3.11').Code     'PY_NOTREC'
Assert-Eq 'Python 3.12 sev'  (Get-PythonSeverity '3.12').Severity 'WARN'
Assert-Eq 'Python 3.13 sev'  (Get-PythonSeverity '3.13').Severity 'FAIL'
Assert-Eq 'Python 3.13 code' (Get-PythonSeverity '3.13').Code     'PY_NEW'
Assert-Eq 'Python bad  sev'  (Get-PythonSeverity 'x').Severity    'WARN'
Assert-Eq 'Python bad  code' (Get-PythonSeverity 'x').Code        'PY_UNREADABLE'

Write-Host "`n== Disk severity (35 GB min for online install) ==" -ForegroundColor Cyan
Assert-Eq 'Disk 34.9 sev'  (Get-DiskSeverity 34.9).Severity 'FAIL'
Assert-Eq 'Disk 34.9 code' (Get-DiskSeverity 34.9).Code     'DISK_LOW'
Assert-Eq 'Disk 35.0 sev'  (Get-DiskSeverity 35.0).Severity 'PASS'
Assert-Eq 'Disk 35.0 code' (Get-DiskSeverity 35.0).Code     'DISK_OK'
Assert-Eq 'Disk 55   sev'  (Get-DiskSeverity 55).Severity   'PASS'
# Custom MinGB path (preflight passes 15 for the installed bundle) -- must respect the arg
Assert-Eq 'Disk 15 min15'   (Get-DiskSeverity 15 15).Severity   'PASS'
Assert-Eq 'Disk 14.9 min15' (Get-DiskSeverity 14.9 15).Severity 'FAIL'
Assert-Eq 'Disk 34 min35'   (Get-DiskSeverity 34 35).Severity   'FAIL'

Write-Host "`n== Gate decision (any FAIL => STOP) ==" -ForegroundColor Cyan
Assert-Eq 'all-warn -> PROCEED'  (Get-GateDecision @('PASS','WARN','WARN')) 'PROCEED'
Assert-Eq 'one-fail -> STOP'     (Get-GateDecision @('PASS','FAIL','WARN')) 'STOP'
Assert-Eq 'no-gpu   -> STOP'     (Get-GateDecision @('FAIL'))               'STOP'
Assert-Eq 'empty    -> PROCEED'  (Get-GateDecision @())                     'PROCEED'

Write-Host ""
if ($fail -eq 0) { Write-Host "ALL TESTS PASS" -ForegroundColor Green; exit 0 }
else { Write-Host "$fail TEST(S) FAILED" -ForegroundColor Red; exit 1 }
