$filename = "son.mp4"
$job_id = "bf36ff4e"

Write-Host "Monitoring job $job_id for $filename..."

$i = 0
while ($i -lt 300) { # 300 * 5s = 25 minutes timeout
    try {
        $res = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/status/$filename" -UseBasicParsing | ConvertFrom-Json
        
        Write-Host "[$([datetime]::now.ToString('HH:mm:ss'))] Status: $($res.status)"
        
        if ($res.results) {
            Write-Host ($res.results | ConvertTo-Json -Depth 5)
        }
        
        if ($res.status -eq "AWAITING_REVIEW") {
            Write-Host "Phase 1 done. Triggering Resume for Phase 2..."
            Invoke-WebRequest -Method Post -Uri "http://127.0.0.1:8000/api/jobs/$($res.job_id)/resume" -UseBasicParsing | Out-Null
            Write-Host "Resume triggered."
        }
        elseif ($res.status -eq "COMPLETED" -or $res.status -eq "FAILED") {
            Write-Host "Job finished with status: $($res.status)"
            Write-Host ($res | ConvertTo-Json -Depth 5)
            break
        }
    } catch {
        Write-Host "Error polling API: $_"
    }
    
    Start-Sleep -Seconds 5
    $i++
}
