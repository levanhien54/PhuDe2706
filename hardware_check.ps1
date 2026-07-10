# =============================================================================
# hardware_check.ps1 -- shared, side-effect-free hardware/compat decision logic.
#
# Each function takes a raw probed value and returns a decision as a
# [pscustomobject]@{ Severity; Code }:
#   Severity = 'PASS' | 'WARN' | 'FAIL'   (drives colour + the install gate)
#   Code     = stable token the caller maps to a localized message + remediation.
#
# The thresholds live HERE (single source of truth) so the installer gate
# (setup_native.ps1) and the diagnostic report (preflight_check.ps1) can never
# disagree. Covered by tests\test_hardware_check.ps1 -- change a threshold, a test
# must change with it.
# =============================================================================

function New-CheckResult($severity, $code) {
    [pscustomobject]@{ Severity = $severity; Code = $code }
}

# VRAM in MiB. 16 GB (16000) is the hard minimum; >= 24 GB selects the 24gb profile.
function Get-VramSeverity {
    param([int]$Mib)
    if ($Mib -lt 16000)      { New-CheckResult 'FAIL' 'VRAM_LOW' }
    elseif ($Mib -lt 24000)  { New-CheckResult 'PASS' 'VRAM_16GB' }
    else                     { New-CheckResult 'PASS' 'VRAM_24GB' }
}

# NVIDIA driver version string. < 452.39 may be too old for CUDA 11.8 (warn, not block).
function Get-DriverSeverity {
    param([string]$Version)
    try {
        if ([version]$Version -lt [version]'452.39') { New-CheckResult 'WARN' 'DRIVER_OLD' }
        else { New-CheckResult 'PASS' 'DRIVER_OK' }
    } catch { New-CheckResult 'WARN' 'DRIVER_UNREADABLE' }
}

# Python "major.minor" string. venv/torch cu118 wheels: 3.10 ideal, 3.11/3.12 work
# (warn), < 3.10 or >= 3.13 have no compatible wheel (block).
function Get-PythonSeverity {
    param([string]$Version)
    $pv = $null
    try { $pv = [version]$Version } catch { return (New-CheckResult 'WARN' 'PY_UNREADABLE') }
    if ($pv -lt [version]'3.10')      { New-CheckResult 'FAIL' 'PY_OLD' }
    elseif ($pv -ge [version]'3.13')  { New-CheckResult 'FAIL' 'PY_NEW' }
    elseif ($pv -ne [version]'3.10')  { New-CheckResult 'WARN' 'PY_NOTREC' }
    else                              { New-CheckResult 'PASS' 'PY_OK' }
}

# Free space in GB. 35 GB is the online-install minimum (models + venv + runtime).
function Get-DiskSeverity {
    param([double]$FreeGB, [double]$MinGB = 35)
    if ($FreeGB -ge $MinGB) { New-CheckResult 'PASS' 'DISK_OK' }
    else { New-CheckResult 'FAIL' 'DISK_LOW' }
}

# Overall gate: any FAIL among the collected severities blocks the install.
function Get-GateDecision {
    param([string[]]$Severities)
    if (@($Severities | Where-Object { $_ -eq 'FAIL' }).Count -gt 0) { 'STOP' } else { 'PROCEED' }
}
