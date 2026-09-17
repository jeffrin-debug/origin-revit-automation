# origin.ps1 - one command line for the env currently OPEN IN REVIT.
#
#   .\origin.ps1 sep          ceiling / wall separation  (per-room ceilings)
#   .\origin.ps1 panels       drywall on walls + ceilings
#   .\origin.ps1 panels-all   drywall on walls, ceilings, soffits, columns, beams
#   .\origin.ps1 all          separation, then everything above
#
# Everything goes through the ONE pipeline bridge (bridge\ + dynamo\ORIGIN Pipeline Bridge.dyn)
# and the ONE runner (origin_run.py), whatever combination is asked for. There is no second
# bridge to start and no script to edit between commands.
#
# NOTHING IS SAVED by any of these. The model changes in the open Revit session and you save it
# yourself. pipeline.cmd is still the batch, and it stays the only thing that writes .rvt files.

param(
    [Parameter(Position = 0)][string]$Command = "help",
    [int]$TimeoutSec = 1800,
    [switch]$Raw
)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$send    = Join-Path $root 'send_command.ps1'
$runner  = Join-Path $root 'origin_run.py'
$cfgPath = Join-Path $root '_origin_cli.json'
$hbPath  = Join-Path $root 'bridge\heartbeat.json'
$resPath = Join-Path $root 'bridge\result.json'

$ALL_PANELS = @('walls', 'ceilings', 'soffits', 'columns', 'beams')

# Order here is irrelevant - origin_run.py always sorts into canonical order (ceiling first,
# then walls, then the rest), because the panel generators read the ceilings separation builds
# and every generator measures against the walls one.
$MAP = [ordered]@{
    'sep'        = @('ceiling')
    'separation' = @('ceiling')
    'ceiling'    = @('ceiling')
    'walls'      = @('walls')
    'ceilings'   = @('ceilings')
    'soffits'    = @('soffits')
    'columns'    = @('columns')
    'beams'      = @('beams')
    'panels'     = @('walls', 'ceilings')
    'panels-all' = $ALL_PANELS
    'az'         = $ALL_PANELS
    'all'        = @('ceiling') + $ALL_PANELS
    'master'     = @('ceiling') + $ALL_PANELS
}

function Show-Help {
    Write-Host ""
    Write-Host "  ORIGIN - commands for the env open in Revit" -ForegroundColor Cyan
    Write-Host "  ------------------------------------------------------------"
    Write-Host "   origin sep          ceiling / wall separation - per-room ceilings"
    Write-Host "   origin panels       drywall panels on walls + ceilings"
    Write-Host "   origin panels-all   drywall on walls, ceilings, soffits, columns, beams"
    Write-Host "   origin all          separation, then all five generators  (master)"
    Write-Host ""
    Write-Host "   one at a time:  origin walls | ceilings | soffits | columns | beams"
    Write-Host "   origin status       is the bridge alive, and on which document"
    Write-Host "   origin doctor       check every path resolved (run this first on a new machine)"
    Write-Host ""
    Write-Host "  Nothing is saved. Save it yourself in Revit if you like the result." -ForegroundColor DarkGray
    Write-Host "  Needs dynamo\ORIGIN Pipeline Bridge.dyn open in Dynamo, run mode Periodic." -ForegroundColor DarkGray
    Write-Host ""
}

function Get-Heartbeat {
    if (-not (Test-Path $hbPath)) { return $null }
    try {
        $raw = Get-Content $hbPath -Raw
        if (-not $raw.Trim()) { return $null }
        return $raw | ConvertFrom-Json
    } catch { return $null }
}

$key = $Command.ToLower()

if ($key -eq 'help' -or $key -eq '-h' -or $key -eq '--help') { Show-Help; exit 0 }

if ($key -eq 'doctor') {
    # What a fresh clone actually resolved to. The two roots are worked out from this script's
    # own location and cannot be wrong; the drywall repo lives outside the repo and can be.
    Write-Host ""
    Write-Host "  ORIGIN - resolved paths" -ForegroundColor Cyan
    Write-Host "  ------------------------------------------------------------"
    $py = python -c @"
import json, os
p = os.path.join(r'$root', 'origin_paths.py')
ns = {'__name__': 'origin_paths', '__file__': p}
exec(compile(open(p).read(), p, 'exec'), ns)
print(json.dumps(ns['describe']()))
"@ 2>&1
    try { $d = $py | ConvertFrom-Json } catch {
        Write-Host "  could not run the resolver (is python on PATH?)" -ForegroundColor Red
        Write-Host "  $py"; exit 1
    }
    function Line($label, $value, $ok) {
        $mark = "  ok "; $col = "Green"
        if ($null -ne $ok -and -not $ok) { $mark = "MISS"; $col = "Red" }
        Write-Host ("   {0}  {1,-14} {2}" -f $mark, $label, $value) -ForegroundColor $col
    }
    Line "pipeline"  $d.PIPELINE_ROOT $d.pipeline_root_ok
    Line "ceilings"  $d.CEILING_ROOT  $d.ceiling_root_ok
    Line "drywall"   $d.DRYWALL_REPO  $d.drywall_repo_ok
    Line "envs"      $d.INPUT_DIR     $null
    Write-Host ("   ---   config         {0}" -f $(if ($d.config_file) { $d.config_file } else { "none (using built-in defaults)" })) -ForegroundColor DarkGray
    Write-Host "  ------------------------------------------------------------"
    if (-not $d.drywall_repo_ok) {
        Write-Host "  The drywall generators are not at that path." -ForegroundColor Yellow
        Write-Host "  They live in a separate repository. Point at them with either:" -ForegroundColor Yellow
        Write-Host "    origin.config.json  beside this folder, key 'drywall_repo'"
        Write-Host "    or the ORIGIN_DRYWALL_REPO environment variable"
        Write-Host "  Until then 'origin sep' works; anything that panels will report"
        Write-Host "  'generator not found' per generator."
        Write-Host ""
        exit 1
    }
    Write-Host "  everything resolves - you are good to go" -ForegroundColor Green
    Write-Host ""
    exit 0
}

if ($key -eq 'status') {
    $hb = Get-Heartbeat
    if ($null -eq $hb) {
        Write-Host "bridge : DOWN - no readable heartbeat" -ForegroundColor Red
        Write-Host "         open dynamo\ORIGIN Pipeline Bridge.dyn in Dynamo, run mode Periodic (1000 ms)"
        exit 1
    }
    $age = [int]((New-TimeSpan -Start ([datetime]$hb.time) -End (Get-Date)).TotalSeconds)
    if ($age -le 30) {
        Write-Host ("bridge : alive  (doc '{0}', view '{1}', tick {2})" -f $hb.doc, $hb.view, $hb.tick) -ForegroundColor Green
        exit 0
    }
    Write-Host ("bridge : STALE by {0}s  (last doc '{1}')" -f $age, $hb.doc) -ForegroundColor Yellow
    Write-Host "         run mode fell back to Manual, or a model was opened in the UI"
    exit 1
}

if (-not $MAP.Contains($key)) {
    Write-Host "unknown command '$Command'" -ForegroundColor Red
    Show-Help
    exit 1
}

$steps = @($MAP[$key])

$hb = Get-Heartbeat
$hbAge = -1
if ($null -ne $hb) {
    $hbAge = [int]((New-TimeSpan -Start ([datetime]$hb.time) -End (Get-Date)).TotalSeconds)
}
# Checked here as well as inside send_command.ps1, so a dead bridge reads as one clear line
# instead of a thrown transport error.
if ($null -eq $hb -or $hbAge -gt 30) {
    if ($null -eq $hb) {
        Write-Host "bridge is not running (no readable heartbeat)." -ForegroundColor Red
    } else {
        Write-Host ("bridge is STALE by {0}s (last doc '{1}')." -f $hbAge, $hb.doc) -ForegroundColor Red
    }
    Write-Host "  Revit 2026 -> Manage -> Dynamo -> open dynamo\ORIGIN Pipeline Bridge.dyn"
    Write-Host "  bottom-left: run mode Periodic, interval 1000 ms, leave it open"
    exit 1
}

# BOM-less, like command.json: Python's json.load rejects a UTF-8 BOM and the runner would
# then see no steps at all.
$json = @{ steps = $steps; command = $key } | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($cfgPath, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ""
Write-Host ("  ORIGIN  {0,-12}  doc: {1}" -f $key, $hb.doc) -ForegroundColor Cyan
Write-Host ("  steps : {0}" -f ($steps -join ' -> '))
Write-Host "  ------------------------------------------------------------"

try {
    & $send -Script $runner -TimeoutSec $TimeoutSec | Out-Null
} catch {
    Write-Host ("  transport failed: {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}

$r = $null
try { $r = Get-Content $resPath -Raw | ConvertFrom-Json } catch { }
if ($null -eq $r) {
    Write-Host "  no result came back - check bridge\node_error.txt" -ForegroundColor Red
    exit 1
}
if (-not $r.ok) {
    Write-Host "  the runner itself threw:" -ForegroundColor Red
    Write-Host $r.error
    exit 1
}
if ($Raw) { Get-Content $resPath -Raw; exit 0 }

$o = $r.out

function Show-Step($name, $row) {
    if ($null -eq $row) { return }
    if ($row.skipped) {
        Write-Host ("  {0,-10} SKIPPED  {1}" -f $name, $row.skipped) -ForegroundColor Yellow
        return
    }
    $tag = "FAIL"; $col = "Red"
    if ($row.ok) { $tag = "OK"; $col = "Green" }
    Write-Host ("  {0,-10} {1,-5} {2,6}s" -f $name, $tag, $row.sec) -ForegroundColor $col

    if ($name -eq 'ceiling' -and $null -ne $row.regions) {
        Write-Host ("             {0} rooms | {1} authored | {2} kept | {3} cut | {4} deleted ({5} collateral) | {6} sf bare" -f `
                $row.regions, $row.authored_rooms, $row.kept_ceilings, $row.created, `
                $row.deleted, $row.collateral, $row.bare_area_sf)
    }
    if ($name -eq 'panels' -and $null -ne $row.counts) {
        Write-Host ("             targets: {0} walls, {1} ceilings" -f $row.counts.walls, $row.counts.ceilings)
        if ($row.direction) {
            $dcol = "DarkGray"
            if ($row.direction_applied) { $dcol = "Cyan" }
            Write-Host ("             {0}" -f $row.direction) -ForegroundColor $dcol
        }
        if ($row.direction_skipped) {
            Write-Host ("             direction NOT applied: {0}" -f $row.direction_skipped) -ForegroundColor Yellow
        }
        foreach ($w in @($row.direction_warnings)) { if ($w) { Write-Host ("             ! {0}" -f $w) -ForegroundColor Yellow } }
        if ($null -ne $row.generators) {
            foreach ($g in $row.generators.PSObject.Properties) {
                $mark = "  ok"
                if ($g.Value.PSObject.Properties.Name -contains 'FATAL') { $mark = "FATAL" }
                Write-Host ("               {0,-10} {1,-6} {2,6}s" -f $g.Name, $mark, $g.Value.sec)
            }
        }
    }
    foreach ($f in @($row.verify_failures)) { if ($f) { Write-Host ("             ! {0}" -f $f) -ForegroundColor Yellow } }
    foreach ($f in @($row.fail_reasons))    { if ($f) { Write-Host ("             ! {0}" -f $f) -ForegroundColor Yellow } }
    if ($row.error) { Write-Host ("             ! {0}" -f $row.error) -ForegroundColor Red }
}

Show-Step 'ceiling' $o.ceiling
Show-Step 'panels'  $o.panels

Write-Host "  ------------------------------------------------------------"
if ($o.error) { Write-Host ("  {0}" -f $o.error) -ForegroundColor Red }
Write-Host ("  nothing saved - File > Save As in Revit to keep this  ({0}s total)" -f $o.sec) -ForegroundColor DarkGray
if ($o.report) { Write-Host ("  detail: {0}" -f $o.report) -ForegroundColor DarkGray }
Write-Host ""

if ($o.ok) { exit 0 } else { exit 1 }
