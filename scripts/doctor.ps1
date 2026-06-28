# Doctor.ps1 — Windows PowerShell self-check for ai-orchestrator-v1
param(
    [switch]$Json = $false
)

$results = @()

function Check-Tool {
    param($Name, $Command, [switch]$Optional = $false)
    try {
        $out = Invoke-Expression "$Command 2>&1" | Out-String
        $status = "OK"
        $detail = ($out -split "`n")[0].Trim()
    } catch {
        $status = if ($Optional) { "OPTIONAL" } else { "MISSING" }
        $detail = $_.Exception.Message
    }
    $results += [PSCustomObject]@{
        Tool     = $Name
        Status   = $status
        Detail   = $detail
    }
    if (-not $Json) {
        $icon = if ($status -eq "OK") { "[OK]" } elseif ($status -eq "OPTIONAL") { "[OPT]" } else { "[MISS]" }
        Write-Host "$icon $Name : $detail"
    }
}

Write-Host "========================================"
Write-Host "  ai-orchestrator-v1 Doctor (Windows)"
Write-Host "========================================"
Write-Host ""

Check-Tool "python" "python --version"
Check-Tool "git" "git --version"
Check-Tool "gh" "gh --version" -Optional
Check-Tool "codex" "codex --version" -Optional
Check-Tool "claude" "claude --version" -Optional
Check-Tool "opencode" "opencode --version" -Optional
Check-Tool "uv" "uv --version"

Write-Host ""
Write-Host "--- Config Files ---"

$home = $env:AI_ORCHESTRATOR_HOME
if (-not $home) { $home = "$env:USERPROFILE\.ai-orchestrator" }

$files = @(
    "$home\projects.yaml",
    "$home\models.yaml",
    "$home\policies.yaml",
    "$env:USERPROFILE\.codex\config.toml"
)
foreach ($f in $files) {
    $exists = Test-Path $f
    $status = if ($exists) { "OK" } else { "MISSING" }
    Write-Host "[$status] $f"
    $results += [PSCustomObject]@{ Tool = "config:$f"; Status = $status; Detail = "" }
}

Write-Host ""
Write-Host "Done."

if ($Json) {
    $results | ConvertTo-Json
}
