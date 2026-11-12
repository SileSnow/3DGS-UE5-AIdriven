<#
.SYNOPSIS
    Launch the UE5.8 virtual drone renderer for one mission JSON (background, auto-exit).

.DESCRIPTION
    Runs UnrealEditor.exe on capture/UE5Synth/UE5Synth.uproject with
    -ExecutePythonScript="llm_drone/ue5_mission/render_mission.py --mission ...".
    The Python script renders one 1600x1200 PNG per mission photo point into
    data/synthetic/mission/images plus metadata.json, then the editor quits by itself
    (PythonScriptPlugin behaviour, same mechanism as capture/run_capture.ps1).

    Safety / machine constraints implemented here:
      * ASCII launch path: the project is addressed through the C:\UEW junction
        (UE has known problems with non-ASCII paths). C:\UEW -> <repo-parent>
      * one UE at a time: aborts if another UnrealEditor.exe is already running
      * CPU <= 4 cores + BelowNormal: affinity = 0x000F, priority = BelowNormal, applied
        right after launch (the background thermal guard re-applies it every few seconds)
      * thermal pre-flight: refuses to start if CPU/GPU are already >= 80 C (-Force overrides)
      * timeout watchdog: kills the editor (and children) after -TimeoutSec
      * log: llm_drone/logs/ue5_mission_<timestamp>.log (UE stdout) plus _stderr.log

.PARAMETER Mission
    mission JSON path (absolute, repo-relative or relative to the repo root). Default: the
    bundled sample missions/mission_grid_12.json.

.PARAMETER Out
    Output dataset root. Default: data/synthetic/mission

.PARAMETER Limit
    Render only N evenly spaced photo points (0 = all).

.PARAMETER ValFrames
    Also render N held-out validation views into <Out>/val (0 = none).

.PARAMETER Exposure / Sun
    Fixed exposure and sun intensity (defaults match capture/RESULTS.md final look: 0.6 / 22).

.PARAMETER Rebuild
    Force clear + rebuild of the procedural scene inside the editor.

.PARAMETER TimeoutSec
    Watchdog timeout for the editor process (default 1800 s).

.PARAMETER Force
    Skip the thermal pre-flight and the "one UE at a time" check.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File ./llm_drone/ue5_mission/run_mission.ps1 -Mission ./llm_drone/ue5_mission/missions/mission_grid_12.json

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File ./llm_drone/ue5_mission/run_mission.ps1 -Mission ./llm_drone/demo/mission_grid_campus.json -ValFrames 8
#>
param(
    [string]$Mission = "",
    [string]$Out = "",
    [int]$Limit = 0,
    [int]$ValFrames = 0,
    [double]$Exposure = 0.6,
    [double]$Sun = 22.0,
    [switch]$Rebuild,
    [int]$TimeoutSec = 1800,
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------- paths (ASCII junction)
$RepoRoot   = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
$UewRoot    = "C:\UEW\dji_ue5_3dgs"
$UERoot     = "C:\Program Files\Epic Games\UE_5.8"
$Editor     = Join-Path $UERoot "Engine\Binaries\Win64\UnrealEditor.exe"
$Project    = Join-Path $UewRoot "capture\UE5Synth\UE5Synth.uproject"
$PyScript   = "C:/UEW/dji_ue5_3dgs/llm_drone/ue5_mission/render_mission.py"
$PyLocal    = "llm_drone/ue5_mission/render_mission.py"
$LogDir     = Join-Path $RepoRoot "llm_drone\logs"

if (-not (Test-Path -LiteralPath "C:\UEW")) {
    throw "ASCII junction C:\UEW is missing (expected -> <repo-parent>)"
}
if (-not (Test-Path -LiteralPath $Editor))   { throw "UnrealEditor.exe not found: $Editor" }
if (-not (Test-Path -LiteralPath $Project))  { throw "UE project not found: $Project" }
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $PyLocal))) { throw "python script not found: $PyLocal" }

if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

function Convert-ToUewPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $Path }
    $resolved = $Path
    if (-not [System.IO.Path]::IsPathRooted($resolved)) {
        $candidates = @((Join-Path (Get-Location) $resolved),
                        (Join-Path $RepoRoot $resolved))
        foreach ($candidate in $candidates) {
            if (Test-Path -LiteralPath $candidate) {
                $resolved = (Resolve-Path -LiteralPath $candidate).Path
                break
            }
        }
    } elseif (Test-Path -LiteralPath $resolved) {
        $resolved = (Resolve-Path -LiteralPath $resolved).Path
    }
    if ($resolved.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        $tail = $resolved.Substring($RepoRoot.Length).TrimStart("\", "/")
        return ($UewRoot + "\" + $tail).Replace("\", "/")
    }
    return $resolved.Replace("\", "/")
}

$missionAbs = $Mission
if ([string]::IsNullOrWhiteSpace($missionAbs)) {
    $missionAbs = "llm_drone/ue5_mission/missions/mission_grid_12.json"
}
if (-not [System.IO.Path]::IsPathRooted($missionAbs)) {
    $missionAbs = Join-Path $RepoRoot $missionAbs
}
if (-not (Test-Path -LiteralPath $missionAbs)) {
    throw "mission JSON not found: $missionAbs (use -Mission <path>)"
}
$missionJson = Convert-ToUewPath $missionAbs

$outDir = $Out
if ([string]::IsNullOrWhiteSpace($outDir)) { $outDir = "data/synthetic/mission" }
if (-not [System.IO.Path]::IsPathRooted($outDir)) { $outDir = Join-Path $RepoRoot $outDir }
$outJson = Convert-ToUewPath $outDir

# ------------------------------------------------------------------- safety pre-flight
$otherUe = @(Get-Process -Name "UnrealEditor" -ErrorAction SilentlyContinue)
$otherUeCmd = @(Get-Process -Name "UnrealEditor-Cmd" -ErrorAction SilentlyContinue)
if (($otherUe.Count + $otherUeCmd.Count) -gt 0 -and -not $Force) {
    throw "another UnrealEditor process is already running; only one UE at a time"
}
$thermal = $null
try {
    $counter = Get-Counter '\Thermal Zone Information(*)\Temperature' -ErrorAction Stop
    $thermal = [math]::Round(($counter.CounterSamples | Measure-Object -Property CookedValue -Maximum).Maximum - 273.15, 1)
} catch { $thermal = $null }
$gpuTemp = $null
try {
    $gpuTemp = [math]::Round([double](nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>$null | Select-Object -First 1), 1)
} catch { $gpuTemp = $null }
if (-not $Force) {
    if ($null -ne $thermal -and $thermal -ge 80) { throw "CPU temperature $thermal C >= 80 C, refusing to start UE (-Force overrides)" }
    if ($null -ne $gpuTemp -and $gpuTemp -ge 80) { throw "GPU temperature $gpuTemp C >= 80 C, refusing to start UE (-Force overrides)" }
}

# ------------------------------------------------------------------------- launch args
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $LogDir ("ue5_mission_" + $stamp + ".log")
$ErrLog = Join-Path $LogDir ("ue5_mission_" + $stamp + "_stderr.log")

$inv = [System.Globalization.CultureInfo]::InvariantCulture
$pyArgs = @(
    "--mission", $missionJson,
    "--out", $outJson,
    "--exposure", $Exposure.ToString($inv),
    "--sun", $Sun.ToString($inv)
)
if ($Limit -gt 0)     { $pyArgs += @("--limit", "$Limit") }
if ($ValFrames -gt 0) { $pyArgs += @("--val-frames", "$ValFrames") }
if ($Rebuild)         { $pyArgs += "--rebuild" }
$pyArgLine = ($pyArgs -join " ")

# Start-Process does not add quotes for us -> build the command line explicitly.  The
# -ExecutePythonScript value MUST be quoted (the editor FParse would otherwise split it).
$argLine = ($Project + " " +
            '-ExecutePythonScript="' + $PyScript + " " + $pyArgLine + '" ' +
            "-windowed -resx=960 -resy=540 -nosplash -unattended -nopause -stdout -FullStdOutLogOutput -log")

if ($DryRun) {
    Write-Host "=== DRY RUN (no editor launched) ==="
    Write-Host "editor  : $Editor"
    Write-Host "argLine : $argLine"
    Write-Host "mission : $missionAbs"
    Write-Host "outDir  : $outDir"
    Write-Host "log     : $Log"
    exit 0
}

Write-Host "=== UE5.8 mission render ==="
Write-Host "editor  : $Editor"
Write-Host "project : $Project"
Write-Host "python  : $PyScript $pyArgLine"
Write-Host "out     : $outDir"
Write-Host "log     : $Log"
Write-Host "temp    : cpu=$thermal C gpu=$gpuTemp C"
Write-Host "started : $(Get-Date -Format o)"

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $Editor -ArgumentList $argLine -RedirectStandardOutput $Log -RedirectStandardError $ErrLog -PassThru -WindowStyle Minimized

function Set-LowFootprint([System.Diagnostics.Process]$Process) {
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            $Process.ProcessorAffinity = [IntPtr]0x000F
            $Process.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
            return $true
        }
    } catch { }
    return $false
}
$affinitySet = $false
$timedOut = $false
while ($true) {
    $proc.Refresh()
    if ($proc.HasExited) { break }
    if (-not $affinitySet) {
        $affinitySet = Set-LowFootprint $proc
        if ($affinitySet) { Write-Host "applied affinity=0x000F priority=BelowNormal to pid $($proc.Id)" }
    }
    if ($sw.Elapsed.TotalSeconds -gt $TimeoutSec) {
        $timedOut = $true
        Write-Host "TIMEOUT after $TimeoutSec s -> killing pid $($proc.Id)"
        & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null
        break
    }
    Start-Sleep -Seconds 2
}
$sw.Stop()
$exitCode = $null
try { $exitCode = $proc.ExitCode } catch { $exitCode = -1 }
$elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)

# ---------------------------------------------------------------------------- verdict
$metaPath = Join-Path $outDir "metadata.json"
$frames = 0
$missionId = $null
if (Test-Path -LiteralPath $metaPath) {
    try {
        $meta = Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $frames = @($meta.frames).Count
        $missionId = $meta.mission.mission_id
    } catch { $frames = 0 }
}

$summary = @(
    "",
    "=== run_mission summary ===",
    "mission_id      : $missionId",
    "frames          : $frames",
    "metadata.json   : $metaPath",
    "out_dir         : $outDir",
    "elapsed_seconds : $elapsed",
    "timed_out       : $timedOut",
    "exit_code       : $exitCode",
    "affinity_applied: $affinitySet (0x000F, BelowNormal)",
    "ue_stdout_log   : $Log",
    "ue_stderr_log   : $ErrLog"
) -join [Environment]::NewLine
Write-Host $summary
try { Add-Content -LiteralPath $Log -Value $summary -Encoding UTF8 } catch { }

if ($timedOut) { exit 124 }
if ($frames -le 0) { exit 1 }
exit 0
