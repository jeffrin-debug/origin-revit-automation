# send_command.ps1 - drive the ORIGIN pipeline bridge from outside Revit.
#
#   .\send_command.ps1 pipeline_run.py
#   .\send_command.ps1 verify_stage2.py -TimeoutSec 600
#
# Bumps the command id, writes bridge\command.json, then waits for bridge\result.json to come
# back with that id. The bridge graph must be running in Dynamo in PERIODIC mode.

param(
    [Parameter(Mandatory = $true)][string]$Script,
    [switch]$Transaction,
    [int]$TimeoutSec = 180,
    [switch]$Raw
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bridge = Join-Path $root 'bridge'
$cmdPath = Join-Path $bridge 'command.json'
$resPath = Join-Path $bridge 'result.json'
$hbPath = Join-Path $bridge 'heartbeat.json'

if (-not (Test-Path $bridge)) { New-Item -ItemType Directory -Force -Path $bridge | Out-Null }

$scriptPath = if ([System.IO.Path]::IsPathRooted($Script)) { $Script } else { Join-Path $root $Script }
if (-not (Test-Path $scriptPath)) { throw "script not found: $scriptPath" }

# The bridge must be alive, or we would wait out the whole timeout for nothing.
if (-not (Test-Path $hbPath)) {
    throw "No heartbeat.json. Open dynamo\ORIGIN Pipeline Bridge.dyn in Dynamo and set run mode to Periodic."
}
$hb = Get-Content $hbPath -Raw | ConvertFrom-Json
$hbAge = (New-TimeSpan -Start ([datetime]$hb.time) -End (Get-Date)).TotalSeconds
if ($hbAge -gt 30) {
    throw ("Bridge heartbeat is {0:N0}s old (doc '{1}'). Start the graph in Periodic mode first." -f $hbAge, $hb.doc)
}

$prevId = 0
if (Test-Path $resPath) {
    try { $prevId = [int](Get-Content $resPath -Raw | ConvertFrom-Json).id } catch { $prevId = 0 }
}
$id = $prevId + 1

# Must be BOM-less: PowerShell 5.1's "-Encoding utf8" writes a UTF-8 BOM, and Python's
# json.load rejects it - the bridge would then silently ignore the command forever.
$json = @{ id = $id; script = $scriptPath; transaction = [bool]$Transaction } | ConvertTo-Json
[System.IO.File]::WriteAllText($cmdPath, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "sent id=$id -> $(Split-Path -Leaf $scriptPath) (doc: $($hb.doc))"

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 800
    if (-not (Test-Path $resPath)) { continue }
    try { $r = Get-Content $resPath -Raw | ConvertFrom-Json } catch { continue }
    if ([int]$r.id -ne $id) { continue }

    if ($r.ok) {
        Write-Host "OK ($($r.started) -> $($r.finished))"
    } else {
        Write-Host "FAILED"
        Write-Host $r.error
    }
    if ($Raw) { Get-Content $resPath -Raw } else { $r.out | ConvertTo-Json -Depth 12 }
    exit 0
}

throw "timed out after ${TimeoutSec}s waiting for result id=$id"
