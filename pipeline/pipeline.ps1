# pipeline.ps1 - ORIGIN env pipeline launcher.
#
# Turns a plain .rvt env into a drywall-panelled env ready for sim, in two stages:
#
#     source .rvt  --stage 1 ceilings-->  01_ceiling_done
#                  --stage 2 panels  -->  02_panels_done  --you approve-->  03_sim_ready
#
# Everything that touches Revit goes through the bridge (dynamo\ORIGIN Pipeline Bridge.dyn,
# running in Periodic mode). This script only ever writes a config file, sends one command,
# and reads the result back - so it can be interrupted at any point without leaving Revit in
# a half-finished state.
#
# Run it by double-clicking pipeline.cmd.

$ErrorActionPreference = 'Stop'
$Root      = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bridge    = Join-Path $Root 'bridge'
$Ceiling   = Join-Path $Root '01_ceiling_done'
$Panels    = Join-Path $Root '02_panels_done'
$SimReady  = Join-Path $Root '03_sim_ready'
$Reports   = Join-Path $Root '_reports'
$Logs      = Join-Path $Root '_logs'
$LedgerPath = Join-Path $Root 'ledger.json'
$ConfigPath = Join-Path $Root '_run_config.json'
$Sender    = Join-Path $Root 'send_command.ps1'

# Envs only. The Downloads folder is also full of Revit's numbered auto-backups and of large
# architecture reference models, and processing either is a waste of a long batch.
$MaxEnvMB = 50

$Source = $null          # file, list of files, or folder chosen in menu item 1

foreach ($d in @($Bridge, $Ceiling, $Panels, $SimReady, $Reports, $Logs)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

# ---------------------------------------------------------------------------- helpers ------

function Read-Choice($Prompt) {
    # Read-Host hands back $null when there is no console to read from - a piped or service
    # context rather than the double-clicked window this is meant for. Calling .Trim() on that
    # is what would otherwise take the menu down with a null-reference error, so $null is
    # passed through deliberately and every caller treats it as "stop".
    $v = Read-Host $Prompt
    if ($null -eq $v) { return $null }
    return $v.Trim().ToUpper()
}

function Write-Json($Path, $Object, $Depth = 12) {
    # BOM-less, always. PowerShell 5.1's -Encoding utf8 writes a BOM and Python's json.load
    # then raises - which the bridge swallows, so the command is ignored with no error anywhere.
    $json = $Object | ConvertTo-Json -Depth $Depth
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-BridgeStatus {
    $hb = Join-Path $Bridge 'heartbeat.json'
    if (-not (Test-Path $hb)) {
        return [pscustomobject]@{ Alive = $false; Age = $null; Doc = $null
                                  Text = 'not started' }
    }
    try { $h = Get-Content $hb -Raw | ConvertFrom-Json } catch {
        return [pscustomobject]@{ Alive = $false; Age = $null; Doc = $null
                                  Text = 'unreadable heartbeat' }
    }
    $age = (New-TimeSpan -Start ([datetime]$h.time) -End (Get-Date)).TotalSeconds
    $alive = ($age -le 30)
    $text = if ($alive) { "alive (doc '$($h.doc)')" }
            else { "STALE by $([int]$age)s - set the graph to Periodic" }
    [pscustomobject]@{ Alive = $alive; Age = [int]$age; Doc = $h.doc; Text = $text }
}

function Get-Ledger {
    if (-not (Test-Path $LedgerPath)) { return @{} }
    try {
        $o = Get-Content $LedgerPath -Raw | ConvertFrom-Json
    } catch { return @{} }
    $h = @{}
    foreach ($p in $o.PSObject.Properties) { $h[$p.Name] = $p.Value }
    return $h
}

function Save-Ledger($Ledger) { Write-Json $LedgerPath $Ledger }

function Set-LedgerEntry($Ledger, $Name, $Fields) {
    if ($Ledger.ContainsKey($Name)) {
        $e = @{}
        foreach ($p in $Ledger[$Name].PSObject.Properties) { $e[$p.Name] = $p.Value }
    } else {
        $e = @{ file = $Name; ceiling = '-'; panels = '-'; review = '-'; promoted = '-' }
    }
    foreach ($k in $Fields.Keys) { $e[$k] = $Fields[$k] }
    $e['updated'] = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    $Ledger[$Name] = [pscustomobject]$e
    return $Ledger
}

function Get-EnvFiles($PathOrList) {
    # Accepts a folder, a single .rvt, or an array of .rvt paths. Applies the same discovery
    # rules the ceiling batch settled on: no Revit auto-backups, nothing over $MaxEnvMB.
    $out = @()
    $items = @($PathOrList)
    foreach ($p in $items) {
        if (-not $p) { continue }
        if (Test-Path $p -PathType Container) {
            $found = Get-ChildItem $p -Filter *.rvt -File | Where-Object {
                ($_.Name -notmatch '\.\d{4}\.rvt$') -and (($_.Length / 1MB) -le $MaxEnvMB)
            }
            $out += $found.FullName
        } elseif (Test-Path $p -PathType Leaf) {
            $out += (Resolve-Path $p).Path
        }
    }
    return @($out | Sort-Object -Unique)
}

function Get-ModelFiles($Dir) {
    # Listing rule for the pipeline's OWN output folders, which is not the same as the one for
    # incoming envs: Revit drops a numbered backup (name.0009.rvt) beside every SaveAs and those
    # are not outputs, but there is deliberately no size cap here - a panelled model is
    # legitimately much larger than the env it came from.
    @(Get-ChildItem $Dir -Filter *.rvt -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -notmatch '\.\d{4}\.rvt$' })
}

function Pick-Source {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    Write-Host ''
    Write-Host '  1) Pick .rvt file(s)'
    Write-Host '  2) Pick a folder of envs'
    Write-Host '  3) Type a path'
    $c = Read-Host '  choice'
    if ($c -eq '1') {
        $dlg = New-Object System.Windows.Forms.OpenFileDialog
        $dlg.Filter = 'Revit models (*.rvt)|*.rvt'
        $dlg.Multiselect = $true
        $dlg.Title = 'Choose the env(s) to process'
        if ($dlg.ShowDialog() -eq 'OK') { return @($dlg.FileNames) }
    } elseif ($c -eq '2') {
        $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
        $dlg.Description = 'Choose a folder of envs'
        if ($dlg.ShowDialog() -eq 'OK') { return $dlg.SelectedPath }
    } elseif ($c -eq '3') {
        $p = Read-Host '  path'
        if ($p) { return $p.Trim('"') }
    }
    return $null
}

function Invoke-Stage($Stages, $Files) {
    # Writes the run config, sends one command to the bridge, then folds the result into the
    # ledger. Returns the parsed result object (or $null if the bridge never answered).
    $bs = Get-BridgeStatus
    if (-not $bs.Alive) {
        Write-Host ''
        Write-Host "  Bridge is $($bs.Text)." -ForegroundColor Red
        Write-Host '  Open Revit 2026, then Manage > Dynamo > open:' -ForegroundColor Yellow
        Write-Host "     $Root\dynamo\ORIGIN Pipeline Bridge.dyn" -ForegroundColor Yellow
        Write-Host '  and set the run mode (bottom-left) to Periodic, 1000 ms.' -ForegroundColor Yellow
        return $null
    }
    if (-not $Files -or $Files.Count -eq 0) {
        Write-Host '  Nothing to run - choose a source first (menu 1).' -ForegroundColor Yellow
        return $null
    }

    $cfg = [ordered]@{
        files            = @($Files)
        stages           = @($Stages)
        save             = $true
        delete_unmatched = $true
        out_ceiling      = $Ceiling
        out_panels       = $Panels
        reports          = $Reports
    }
    Write-Json $ConfigPath $cfg

    # Ceilings run in about 3 s per env; the panel generators are far heavier, so the wait has
    # to scale with both the file count and which stages were asked for.
    $per = 90
    if ($Stages -contains 'panels') { $per = 600 }
    $timeout = 120 + ($per * $Files.Count)

    Write-Host ''
    Write-Host ("  Running [{0}] on {1} file(s). Timeout {2}s. Revit is busy until this returns." -f ($Stages -join ' + '), $Files.Count, $timeout) -ForegroundColor Cyan
    Write-Host ''

    & $Sender -Script (Join-Path $Root 'pipeline_run.py') -TimeoutSec $timeout | Out-Null

    $resPath = Join-Path $Bridge 'result.json'
    if (-not (Test-Path $resPath)) { Write-Host '  No result.json came back.' -ForegroundColor Red; return $null }
    $res = Get-Content $resPath -Raw | ConvertFrom-Json

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    Copy-Item $resPath (Join-Path $Logs "run_$stamp.json") -Force

    if (-not $res.ok) {
        Write-Host '  The run failed inside Revit:' -ForegroundColor Red
        Write-Host $res.error
        return $res
    }

    $ledger = Get-Ledger
    foreach ($f in $res.out.files) {
        $fields = @{ source = $f.source; status = $f.status }
        if ($f.ceiling) { $fields['ceiling'] = $f.ceiling }
        if ($f.panels)  { $fields['panels']  = $f.panels }
        if ($f.panels -eq 'ok') { $fields['review'] = 'pending' }
        $ledger = Set-LedgerEntry $ledger $f.file $fields
    }
    Save-Ledger $ledger

    Show-RunSummary $res.out
    return $res
}

function Show-RunSummary($Out) {
    Write-Host ''
    Write-Host '  RESULT' -ForegroundColor Cyan
    Write-Host '  ------'
    $rows = foreach ($f in $Out.files) {
        [pscustomobject]@{
            File    = $f.file
            Ceiling = if ($f.ceiling) { $f.ceiling } else { '-' }
            Panels  = if ($f.panels)  { $f.panels }  else { '-' }
            Sec     = $f.sec
            Status  = $f.status
        }
    }
    if ($rows) { $rows | Format-Table -AutoSize | Out-String -Width 160 | Write-Host }
    $t = $Out.totals
    Write-Host ("  ok {0}   ceiling-failed {1}   panels-failed {2}   errors {3}   quarantined {4}   skipped {5}" -f `
        $t.ok, $t.ceiling_failed, $t.panels_failed, $t.errors, $t.quarantined, $t.skipped)
    if ($Out.dialogs_auto_answered -and $Out.dialogs_auto_answered.Count -gt 0) {
        Write-Host ("  dialogs auto-answered: {0}" -f (($Out.dialogs_auto_answered | Select-Object -Unique) -join ', ')) -ForegroundColor DarkGray
    }
    Write-Host ''
    Write-Host ("  A stage only saves after it passes, so nothing half-generated reaches disk." ) -ForegroundColor DarkGray
    Write-Host ("  A file can still show ceiling 'ok' and then fail stage 2 - its ceiling output" ) -ForegroundColor DarkGray
    Write-Host ("  is already in 01_ceiling_done, so re-run it with menu 4 rather than from scratch." ) -ForegroundColor DarkGray
}

function Show-Status {
    $ledger = Get-Ledger
    Write-Host ''
    if ($ledger.Count -eq 0) { Write-Host '  Nothing processed yet.'; return }
    $rows = foreach ($k in ($ledger.Keys | Sort-Object)) {
        $e = $ledger[$k]
        [pscustomobject]@{
            File = $e.file; Ceiling = $e.ceiling; Panels = $e.panels
            Review = $e.review; Promoted = $e.promoted; Updated = $e.updated
        }
    }
    $rows | Format-Table -AutoSize | Out-String -Width 160 | Write-Host
    Write-Host ("  01_ceiling_done {0}   02_panels_done {1}   03_sim_ready {2}" -f `
        (Get-ModelFiles $Ceiling).Count, (Get-ModelFiles $Panels).Count, (Get-ModelFiles $SimReady).Count)
}

function Do-Review {
    $ledger = Get-Ledger
    $pending = @(Get-ModelFiles $Panels |
                 Where-Object { -not $ledger.ContainsKey($_.Name) -or $ledger[$_.Name].review -ne 'approved' })
    if ($pending.Count -eq 0) {
        Write-Host ''
        Write-Host '  Nothing waiting for review in 02_panels_done.'
        return
    }
    Write-Host ''
    Write-Host '  Look at each model in the ORIGIN Assembly 3D view - boards z-fight in other views,' -ForegroundColor DarkGray
    Write-Host '  which looks like missing drywall but is only a display artifact.' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  NOTE: opening a model in Revit makes it the active document, which stops the' -ForegroundColor Yellow
    Write-Host '  Dynamo bridge. Finish reviewing, then reopen the graph before the next run.' -ForegroundColor Yellow

    foreach ($f in $pending) {
        $mark = if ($ledger.ContainsKey($f.Name)) { $ledger[$f.Name].review } else { 'pending' }
        Write-Host ''
        Write-Host ("  --- {0}   ({1:N1} MB, review: {2})" -f $f.Name, ($f.Length/1MB), $mark) -ForegroundColor Cyan
        $rep = Join-Path $Reports ("{0}_pipeline.json" -f [System.IO.Path]::GetFileNameWithoutExtension($f.Name))
        if (Test-Path $rep) {
            try {
                $d = Get-Content $rep -Raw | ConvertFrom-Json
                if ($d.panels.counts) {
                    Write-Host ("      walls {0}, ceilings {1}" -f $d.panels.counts.walls, $d.panels.counts.ceilings) -ForegroundColor DarkGray
                }
                foreach ($g in $d.panels.generators.PSObject.Properties) {
                    $w = $g.Value.warnings
                    if ($w -and $w.Count -gt 0) {
                        Write-Host ("      {0}: {1} warning(s)" -f $g.Name, $w.Count) -ForegroundColor Yellow
                    }
                }
            } catch { }
        }
        Write-Host '      [O] open in Revit   [A] approve   [R] reject   [S] skip   [Q] stop reviewing'
        $c = Read-Choice '      '
        if ($null -eq $c) { Save-Ledger $ledger; return }
        if ($c -eq 'O') {
            Start-Process $f.FullName
            Write-Host '      opening... approve or reject once you have looked at it.' -ForegroundColor DarkGray
            $c = Read-Choice '      [A] approve  [R] reject  [S] skip'
            if ($null -eq $c) { Save-Ledger $ledger; return }
        }
        switch ($c) {
            'A' { $ledger = Set-LedgerEntry $ledger $f.Name @{ review = 'approved' }
                  Write-Host '      approved' -ForegroundColor Green }
            'R' { $ledger = Set-LedgerEntry $ledger $f.Name @{ review = 'rejected' }
                  Write-Host '      rejected - it stays in 02_panels_done' -ForegroundColor Red }
            'Q' { Save-Ledger $ledger; return }
            default { Write-Host '      skipped' -ForegroundColor DarkGray }
        }
    }
    Save-Ledger $ledger
}

function Do-Promote {
    $ledger = Get-Ledger
    $approved = @($ledger.Keys | Where-Object { $ledger[$_].review -eq 'approved' -and $ledger[$_].promoted -ne 'yes' })
    if ($approved.Count -eq 0) {
        Write-Host ''
        Write-Host '  Nothing approved and waiting. Review first (menu 5).'
        return
    }
    Write-Host ''
    Write-Host ("  Moving {0} approved file(s) into 03_sim_ready:" -f $approved.Count)
    foreach ($n in $approved) { Write-Host "    $n" }
    $ok = Read-Host '  proceed? [y/N]'
    if ($ok -notmatch '^(y|Y)') { Write-Host '  cancelled.'; return }

    foreach ($n in $approved) {
        $src = Join-Path $Panels $n
        if (-not (Test-Path $src)) {
            Write-Host "    $n - not in 02_panels_done, skipped" -ForegroundColor Yellow
            continue
        }
        $dst = Join-Path $SimReady $n
        Move-Item $src $dst -Force
        $ledger = Set-LedgerEntry $ledger $n @{ promoted = 'yes'; sim_path = $dst }
        Write-Host "    $n -> 03_sim_ready" -ForegroundColor Green
    }
    Save-Ledger $ledger
}

function Invoke-VerifyStage2 {
    $bs = Get-BridgeStatus
    if (-not $bs.Alive) {
        Write-Host ''
        Write-Host "  Bridge is $($bs.Text) - start the graph first." -ForegroundColor Red
        return
    }
    Write-Host ''
    Write-Host '  Opening one env as a background document, running the panel generators against' -ForegroundColor Cyan
    Write-Host '  it, then closing WITHOUT saving. Nothing on disk changes.' -ForegroundColor Cyan
    Write-Host '  (Target is set at the top of verify_stage2.py.)' -ForegroundColor DarkGray
    Write-Host ''
    & $Sender -Script (Join-Path $Root 'verify_stage2.py') -TimeoutSec 900 -Raw
}

# ------------------------------------------------------------------------------ menu -------

# Labelled, because `break` inside the switch below would otherwise only leave the switch and
# the menu would redraw forever instead of quitting.
:menu while ($true) {
    $bs = Get-BridgeStatus
    $files = Get-EnvFiles $Source

    Clear-Host
    Write-Host ''
    Write-Host '  ORIGIN ENV PIPELINE' -ForegroundColor Cyan
    Write-Host '  ==================='
    Write-Host ''
    $srcText = if ($Source) {
        if (@($Source).Count -gt 1) { "$(@($Source).Count) file(s) picked" } else { "$Source" }
    } else { '(none chosen)' }
    Write-Host ("  Source : {0}" -f $srcText)
    Write-Host ("           {0} env(s) queued" -f $files.Count)
    if ($bs.Alive) { Write-Host ("  Bridge : {0}" -f $bs.Text) -ForegroundColor Green }
    else           { Write-Host ("  Bridge : {0}" -f $bs.Text) -ForegroundColor Red }
    Write-Host ''
    Write-Host '   1) Choose source file or folder'
    Write-Host '   2) Run  ceilings + panels      (the full flow)'
    Write-Host '   3) Run  ceilings only'
    Write-Host '   4) Run  panels only            (on 01_ceiling_done)'
    Write-Host '   5) Review finished files       -> approve / reject'
    Write-Host '   6) Promote approved            -> 03_sim_ready'
    Write-Host '   7) Status'
    Write-Host '   8) Verify stage 2 on one file  (nothing saved)'
    Write-Host '   9) Open the output folders'
    Write-Host '   Q) Quit'
    Write-Host ''
    $choice = Read-Choice '  Select'
    if ($null -eq $choice) {
        Write-Host ''
        Write-Host '  No console to read from - exiting. Double-click pipeline.cmd instead.' -ForegroundColor Yellow
        break menu
    }

    switch ($choice) {
        '1' { $s = Pick-Source; if ($s) { $Source = $s } }
        '2' { Invoke-Stage @('ceiling', 'panels') $files | Out-Null; Read-Host '  [enter]' | Out-Null }
        '3' { Invoke-Stage @('ceiling') $files | Out-Null; Read-Host '  [enter]' | Out-Null }
        '4' {
              $cf = @((Get-ModelFiles $Ceiling).FullName)
              if ($cf.Count -eq 0) { Write-Host '  01_ceiling_done is empty.' -ForegroundColor Yellow }
              else { Invoke-Stage @('panels') $cf | Out-Null }
              Read-Host '  [enter]' | Out-Null
            }
        '5' { Do-Review;  Read-Host '  [enter]' | Out-Null }
        '6' { Do-Promote; Read-Host '  [enter]' | Out-Null }
        '7' { Show-Status; Read-Host '  [enter]' | Out-Null }
        '8' { Invoke-VerifyStage2; Read-Host '  [enter]' | Out-Null }
        '9' { Start-Process $Root; }
        'Q' { break menu }
        default { }
    }
}
