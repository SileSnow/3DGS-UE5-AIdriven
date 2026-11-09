<#
.SYNOPSIS
    Launch the UE5.8 virtual drone renderer for one mission JSON (task-6 / Phase-1 #4).

.DESCRIPTION
    Runs UnrealEditor.exe on capture/UE5Synth/UE5Synth.uproject with
    -ExecutePythonScript="llm_drone/ue5_mission/render_mission.py --mission ... --out ...".
    The Python script renders one 1600x1200 PNG per mission photo point into
    <Out>/images, plus <Out>/metadata.json and <Out>/poses_mission.json, then the editor
    quits by itself (PythonScriptPlugin defers QUIT_EDITOR, same as capture/run_capture.ps1).

    Paths: the project is addressed through the ASCII junction C:\UEW
    (C:\UEW -> C:\Users\Lenovo\Desktop\GAIA项目) because UE has known problems with
    non-ASCII launch paths.  The -Mission / -Out values are mapped through the same junction
    automatically; everything passed to UE uses forward slashes.

    Safety / machine constraints implemented here:
      * one UE at a time: aborts if another UnrealEditor.exe is already running
      * thermal pre-flight: refuses to start if CPU/GPU are already >= 80 C (-Force overrides)
      * CPU <= 4 cores + BelowNormal priority (applied right after launch)
      * timeout watchdog: kills the editor (and children) after -TimeoutSec
      * logs: llm_drone/logs/ue5-mission/ue_mission_<timestamp>.log (UE stdout),
        _stderr.log, run_<timestamp>.json (verdict) and a copy of the engine log

.PARAMETER Mission
    Mission JSON path (absolute, repo-relative or cwd-relative).
    Supports llm_drone.mission/v1 (frozen spec) and the llm_drone/orchestrator demo envelope.
    Default: llm_drone/spec/sample_mission.json

.PARAMETER Out
    Output dataset root. Default: data/synthetic/mission

.PARAMETER Exposure / Sun
    Fixed exposure and sun intensity (defaults match capture/RESULTS.md final look: 0.6 / 22).

.PARAMETER Limit
    Render only the first N photo points (0 = all).

.PARAMETER TimeoutSec
    Watchdog timeout for the editor process (default 900 s).

.PARAMETER Force
    Skip the thermal pre-flight and the "one UE at a time" check.

.PARAMETER DryRun
    Print the resolved command line and exit without launching the editor.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File llm_drone\ue5_mission\run_mission.ps1 -Mission llm_drone\spec\sample_mission.json
#>
param(
    [string]$Mission = "",
    [string]$Out = "",
    [double]$Exposure = 0.6,
    [double]$Sun = 22.0,
    [int]$Limit = 0,
    [int]$TimeoutSec = 900,
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------- paths (ASCII junction)
$Here      = $PSScriptRoot
$LlmDrone  = Split-Path $Here -Parent
$RepoRoot  = Split-Path $LlmDrone -Parent
$BaseDir   = Split-Path $RepoRoot -Parent
$AsciiBase = "C:\UEW"
$UERoot    = "C:\Program Files\Epic Games\UE_5.8"
$Editor    = Join-Path $UERoot "Engine\Binaries\Win64\UnrealEditor.exe"
$LogDir    = Join-Path $RepoRoot "llm_drone\logs\ue5-mission"
$ProjectLocal = Join-Path $RepoRoot "capture\UE5Synth\UE5Synth.uproject"

if (-not (Test-Path -LiteralPath $AsciiBase)) {
    throw "ASCII junction C:\UEW is missing (expected -> $BaseDir)"
}
if (-not (Test-Path -LiteralPath $Editor))            { throw "UnrealEditor.exe not found: $Editor" }
if (-not (Test-Path -LiteralPath $ProjectLocal))      { throw "UE project not found: $ProjectLocal" }
if (-not (Test-Path -LiteralPath (Join-Path $Here "render_mission.py"))) {
    throw "render_mission.py not found next to this script: $Here"
}
if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

function Resolve-RepoPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $Path }
    if ([System.IO.Path]::IsPathRooted($Path)) {
        if (Test-Path -LiteralPath $Path) { return (Resolve-Path -LiteralPath $Path).Path }
        return [System.IO.Path]::GetFullPath($Path)
    }
    foreach ($candidate in @((Join-Path $RepoRoot $Path), (Join-Path (Get-Location) $Path))) {
        if (Test-Path -LiteralPath $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Convert-ToAsciiUePath([string]$AbsPath) {
    $full = [System.IO.Path]::GetFullPath($AbsPath)
    $baseFull = [System.IO.Path]::GetFullPath($BaseDir)
    if ($full.StartsWith($baseFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        $full = $AsciiBase + $full.Substring($baseFull.Length)
    }
    if ($full -match '[^\x00-\x7F]') {
        throw "path is not ASCII after junction mapping: $full"
    }
    return ($full.Replace("\", "/"))
}

# ---------------------------------------------------------------- mission / out resolution
if ([string]::IsNullOrWhiteSpace($Mission)) {
    $Mission = "llm_drone/spec/sample_mission.json"
}
$missionAbs = Resolve-RepoPath $Mission
if (-not (Test-Path -LiteralPath $missionAbs)) { throw "mission JSON not found: $missionAbs" }
$missionUe = Convert-ToAsciiUePath $missionAbs

if ([string]::IsNullOrWhiteSpace($Out)) { $Out = "data/synthetic/mission" }
$outAbs = Resolve-RepoPath $Out
if (-not (Test-Path -LiteralPath $outAbs)) {
    New-Item -ItemType Directory -Force -Path $outAbs | Out-Null
}
$outUe = Convert-ToAsciiUePath $outAbs
$pyUe = Convert-ToAsciiUePath (Join-Path $Here "render_mission.py")
$projectUe = Convert-ToAsciiUePath $ProjectLocal

# ------------------------------------------------------------------- safety pre-flight
$otherUe = @(Get-Process -Name "UnrealEditor" -ErrorAction SilentlyContinue)
$otherUeCmd = @(Get-Process -Name "UnrealEditor-Cmd" -ErrorAction SilentlyContinue)
if (($otherUe.Count + $otherUeCmd.Count) -gt 0 -and -not $Force) {
    throw "another UnrealEditor process is already running; only one UE at a time (-Force overrides)"
}
$thermal = $null
$gpuTemp = $null
try {
    $counter = Get-Counter '\Thermal Zone Information(*)\Temperature' -ErrorAction Stop
    $thermal = [math]::Round(($counter.CounterSamples | Measure-Object -Property CookedValue -Maximum).Maximum - 273.15, 1)
} catch { $thermal = $null }
try {
    $gpuTemp = [math]::Round([double](nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>$null | Select-Object -First 1), 1)
} catch { $gpuTemp = $null }
if (-not $Force) {
    if ($null -ne $thermal -and $thermal -ge 80) { throw "CPU temperature $thermal C >= 80 C, refusing to start UE (-Force overrides)" }
    if ($null -ne $gpuTemp -and $gpuTemp -ge 80) { throw "GPU temperature $gpuTemp C, refusing to start UE (-Force overrides)" }
}

# ------------------------------------------------------------------------- launch args
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $LogDir ("ue_mission_" + $stamp + ".log")
$ErrLog = Join-Path $LogDir ("ue_mission_" + $stamp + "_stderr.log")
$RunJson = Join-Path $LogDir ("run_" + $stamp + ".json")

$inv = [System.Globalization.CultureInfo]::InvariantCulture
$pyArgs = @(
    "--mission", $missionUe,
    "--out", $outUe,
    "--exposure", $Exposure.ToString($inv),
    "--sun", $Sun.ToString($inv)
)
if ($Limit -gt 0) { $pyArgs += @("--limit", "$Limit") }
$pyArgLine = ($pyArgs -join " ")

$argLine = ($projectUe + " " +
            '-ExecutePythonScript="' + $pyUe + " " + $pyArgLine + '" ' +
            "-windowed -resx=960 -resy=540 -nosplash -unattended -nopause -stdout -FullStdOutLogOutput -log")

if ($DryRun) {
    Write-Host "=== DRY RUN (no editor launched) ==="
    Write-Host "editor       : $Editor"
    Write-Host "project      : $projectUe"
    Write-Host "python       : $pyUe $pyArgLine"
    Write-Host "argLine      : $argLine"
    Write-Host "mission      : $missionAbs"
    Write-Host "outDir       : $outAbs"
    Write-Host "exposure/sun : $Exposure / $Sun"
    Write-Host "log          : $Log"
    Write-Host "runJson      : $RunJson"
    exit 0
}

Write-Host "=== UE5.8 mission render ==="
Write-Host "editor       : $Editor"
Write-Host "project      : $projectUe"
Write-Host "python       : $pyUe $pyArgLine"
Write-Host "mission      : $missionAbs"
Write-Host "outDir       : $outAbs"
Write-Host "exposure/sun : $Exposure / $Sun"
Write-Host "log          : $Log"
Write-Host "temp         : cpu=$thermal C gpu=$gpuTemp C"
Write-Host "started      : $(Get-Date -Format o)"

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

$engineLog = Join-Path $RepoRoot "capture\UE5Synth\Saved\Logs\UE5Synth.log"
$engineCopy = $null
if (Test-Path -LiteralPath $engineLog) {
    $engineCopy = Join-Path $LogDir ("ue_engine_" + $stamp + ".log")
    try { Copy-Item -LiteralPath $engineLog -Destination $engineCopy -Force } catch { $engineCopy = $null }
}

# ---------------------------------------------------------------------------- verdict
$metaPath = Join-Path $outAbs "metadata.json"
$frames = 0
$missionId = $null
$frameWidth = $null
$frameHeight = $null
if (Test-Path -LiteralPath $metaPath) {
    try {
        $meta = Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $frames = @($meta.frames).Count
        $missionId = $meta.mission.mission_id
        $frameWidth = $meta.width
        $frameHeight = $meta.height
    } catch { $frames = 0 }
}

$verdict = @{
    timestamp = (Get-Date -Format o)
    mission_file = $missionAbs
    mission_id = $missionId
    out_dir = $outAbs
    metadata = $metaPath
    frames = $frames
    width = $frameWidth
    height = $frameHeight
    exposure = $Exposure
    sun = $Sun
    limit = $Limit
    elapsed_seconds = $elapsed
    timed_out = $timedOut
    exit_code = $exitCode
    affinity_applied = $affinitySet
    cpu_temp_c = $thermal
    gpu_temp_c = $gpuTemp
    ue_stdout_log = $Log
    ue_stderr_log = $ErrLog
    ue_engine_log_copy = $engineCopy
    command_line = $argLine
}
$verdictJson = $verdict | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($RunJson, $verdictJson, (New-Object System.Text.UTF8Encoding($false)))

$summaryText = @(
    "",
    "=== run_mission summary ===",
    "mission_id     : $missionId",
    "frames         : $frames ($frameWidth x $frameHeight)",
    "metadata.json  : $metaPath",
    "out_dir        : $outAbs",
    "elapsed_seconds: $elapsed",
    "timed_out      : $timedOut",
    "exit_code      : $exitCode",
    "affinity       : $affinitySet (0x000F, BelowNormal)",
    "run_json       : $RunJson",
    "ue_stdout_log  : $Log"
) -join [Environment]::NewLine
Write-Host $summaryText
try { Add-Content -LiteralPath $Log -Value $summaryText -Encoding UTF8 } catch { }

if ($timedOut) { exit 124 }
if ($frames -le 0) { exit 1 }
exit 0
