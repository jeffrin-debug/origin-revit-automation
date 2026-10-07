# send.ps1 <script.py> [-Transaction]  - queue a script for the ORIGIN Layout Bridge and wait for its result.
param([Parameter(Mandatory)][string]$Script, [switch]$Transaction, [int]$TimeoutSec = 60)
$bridge = Join-Path $PSScriptRoot 'bridge'
$cmdPath = Join-Path $bridge 'command.json'
$resPath = Join-Path $bridge 'result.json'
$id = [int][double]::Parse((Get-Date -UFormat %s))
$full = (Resolve-Path $Script).Path
$json = @{ id = $id; script = $full; transaction = [bool]$Transaction } | ConvertTo-Json
# BOM-less on purpose: a BOM makes the bridge's json.load fail silently.
[System.IO.File]::WriteAllText($cmdPath, $json, (New-Object System.Text.UTF8Encoding($false)))
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $resPath) {
        try { $r = Get-Content -Raw $resPath | ConvertFrom-Json } catch { $r = $null }
        if ($r -and $r.id -eq $id) { Get-Content -Raw $resPath; exit 0 }
    }
    Start-Sleep -Milliseconds 500
}
Write-Output "TIMEOUT waiting for command $id - is the Dynamo graph running in Periodic mode?"
exit 1
