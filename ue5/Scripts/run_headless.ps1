<#
.SYNOPSIS
    Run the DJI3DGS_UE 3DGS viewer headless (windowed -game) on a PLY file and collect metrics + screenshots.

.DESCRIPTION
    Launches UnrealEditor.exe -game -windowed -resx/-resy with the ASplatTestActor harness:
      * loads the PLY at runtime (C++ parser, no editor import step)
      * renders it with the ported Italink Niagara GPU splat renderer
      * orbits a camera for -Warmup seconds, then measures -Measure seconds of frame times
      * saves -Shots screenshots (SceneCapture2D -> PNG) plus metrics.json / frames.csv
      * samples nvidia-smi GPU memory during the run and merges peak/avg MiB into metrics.json

    GPU serialization: UE RHI rendering must not overlap with capture-synth's editor. The script
    refuses to start when another UnrealEditor process is already running unless -Force is given.

.NOTES
    Paths use the ASCII junction C:\UEW because the workspace path contains CJK characters.

.EXAMPLE
    pwsh -File Scripts/run_headless.ps1 -Ply C:/UEW/dji_ue5_3dgs/ue5/test_data/sphere_50k.ply
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Ply,
    [string]$OutDir = '',
    [int]$ResX = 1280,
    [int]$ResY = 720,
    [double]$Warmup = 6,
    [double]$Measure = 8,
    [int]$Shots = 2,
    [double]$OrbitSpeed = 12,
    [int]$SortIters = 5,
    [int]$OrbitFrames = 0,
    [double]$OrbitStep = 0,
    [ValidateSet(0, 1)][int]$UECoords = 1,
    [double]$Scale = 0,
    [int]$TimeoutSec = 420,
    [int]$NoNiagara = 0,
    [int]$DiagViews = 0,
    [int]$HDRCapture = 1,
    [int]$DebugPoints = 0,
    [double]$ScaleMul = 1.0,
    [double]$PosMul = 1.0,
    [int]$ViewportShots = 0,
    [double]$Exposure = 1.0,
    [double]$CamDistance = 0,
    [switch]$NullRHI,
    [switch]$Force,
    [switch]$NoGpuSample
)

$ErrorActionPreference = 'Stop'
$UE_ROOT = 'C:/Program Files/Epic Games/UE_5.8'
$EDITOR = Join-Path $UE_ROOT 'Engine/Binaries/Win64/UnrealEditor.exe'
$PROJECT = 'C:/UEW/dji_ue5_3dgs/ue5/DJI3DGS_UE/DJI3DGS_UE.uproject'
$RESULT_ROOT = 'C:/UEW/dji_ue5_3dgs/ue5/results'

if (-not (Test-Path 'C:/UEW')) { throw 'ASCII junction C:\UEW is missing.' }
if (-not (Test-Path $EDITOR)) { throw "UnrealEditor.exe not found: $EDITOR" }
if (-not (Test-Path $Ply)) { throw "PLY not found: $Ply" }
if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = Join-Path $RESULT_ROOT ("run_" + (Get-Date -Format 'yyyyMMdd_HHmmss'))
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$running = Get-Process -Name 'UnrealEditor', 'UnrealEditor-Cmd' -ErrorAction SilentlyContinue
if ($running -and -not $Force) {
    Write-Host '[run] Another UnrealEditor process is running:' -ForegroundColor Yellow
    $running | ForEach-Object { Write-Host ("  pid=" + $_.Id + " " + $_.ProcessName + " mem=" + [math]::Round($_.WorkingSet64 / 1MB) + "MB") }
    throw 'Refusing to start a second UE RHI session (GPU/memory serialization). Use -Force to override.'
}

$logFile = Join-Path $OutDir 'ue5_run.log'
$gpuCsv = Join-Path $OutDir 'gpu_samples.csv'

$sampler = $null
if (-not $NoGpuSample) {
    $sampler = Start-Process -FilePath 'nvidia-smi' -ArgumentList @(
        '-lms', '500',
        '--query-gpu=timestamp,memory.used,memory.free,utilization.gpu',
        '--format=csv,noheader', '-f', $gpuCsv
    ) -PassThru -WindowStyle Hidden -ErrorAction SilentlyContinue
}

$argString = '"' + $PROJECT + '" -game'
$argString += ' -windowed -resx=' + $ResX + ' -resy=' + $ResY
$argString += ' -nosound -NoSplash -Unattended -nopause'
if ($NullRHI) { $argString += ' -nullrhi' }
$argString += ' -log -stdout'
$argString += ' -SplatPly="' + $Ply + '"'
$argString += ' -SplatOutDir="' + $OutDir + '"'
$argString += ' -SplatUECoords=' + $UECoords
$argString += ' -SplatWarmup=' + $Warmup
$argString += ' -SplatMeasure=' + $Measure
$argString += ' -SplatShots=' + $Shots
$argString += ' -SplatOrbitSpeed=' + $OrbitSpeed
$argString += ' -SplatSortIters=' + $SortIters
$argString += ' -SplatOrbitFrames=' + $OrbitFrames
if ($OrbitStep -gt 0) { $argString += ' -SplatOrbitStep=' + $OrbitStep }
$argString += ' -SplatResX=' + $ResX + ' -SplatResY=' + $ResY
if ($Scale -gt 0) { $argString += ' -SplatScale=' + $Scale }
$argString += ' -SplatNoNiagara=' + $NoNiagara
$argString += ' -SplatDiagViews=' + $DiagViews
$argString += ' -SplatHDRCapture=' + $HDRCapture
$argString += ' -SplatDebugPoints=' + $DebugPoints
$argString += ' -SplatScaleMul=' + $ScaleMul
$argString += ' -SplatPosMul=' + $PosMul
$argString += ' -SplatViewportShots=' + $ViewportShots
$argString += ' -SplatExposure=' + $Exposure
if ($CamDistance -gt 0) { $argString += ' -SplatCameraDistance=' + $CamDistance }

Write-Host ("[run] Args:   " + $argString)
Write-Host ("[run] PLY:    " + $Ply)
Write-Host ("[run] OutDir: " + $OutDir)
Write-Host ("[run] Editor: " + $EDITOR)

Write-Host ("[run] Log:    " + $logFile)

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $EDITOR -ArgumentList $argString -PassThru -NoNewWindow -RedirectStandardOutput $logFile -RedirectStandardError ($logFile + '.err')
# Load limiting (user requirement: CPU not saturated, temperature <= 80C): below-normal priority + 14-core affinity
Start-Sleep -Milliseconds 800
try {
    $limitProc = Get-Process -Id $proc.Id -ErrorAction Stop
    $limitProc.PriorityClass = 'BelowNormal'
    $limitProc.ProcessorAffinity = [IntPtr]0x000F
    Write-Host ("[run] load limit applied: priority=BelowNormal affinity=0x000F(4 cores) pid=" + $proc.Id)
} catch {
    Write-Host ("[run] WARNING: could not apply load limiting: " + $_.Exception.Message) -ForegroundColor Yellow
}

$exited = $proc.WaitForExit($TimeoutSec * 1000)
if (-not $exited) {
    Write-Host ("[run] TIMEOUT after " + $TimeoutSec + "s, killing pid " + $proc.Id) -ForegroundColor Red
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
$stopwatch.Stop()
$exitCode = -999
if ($exited) { $exitCode = $proc.ExitCode }
if ($sampler) { Stop-Process -Id $sampler.Id -Force -ErrorAction SilentlyContinue }
Write-Host ("[run] exit=" + $exitCode + " wall=" + [math]::Round($stopwatch.Elapsed.TotalSeconds, 1) + "s")

$metricsPath = Join-Path $OutDir 'metrics.json'
if ((Test-Path $gpuCsv) -and (Test-Path $metricsPath)) {
    try {
        $rows = @()
        foreach ($line in (Get-Content $gpuCsv)) {
            if ($line -notmatch ',') { continue }
            $parts = $line -split ','
            if ($parts.Count -ge 3) {
                $used = 0.0
                $free = 0.0
                $util = 0.0
                [void][double]::TryParse($parts[1].Trim(), [ref]$used)
                [void][double]::TryParse($parts[2].Trim(), [ref]$free)
                if ($parts.Count -ge 4) { [void][double]::TryParse($parts[3].Trim(), [ref]$util) }
                if ($used -gt 0) {
                    $rows += [pscustomobject]@{ timestamp = $parts[0].Trim(); usedMiB = $used; freeMiB = $free; utilPct = $util }
                }
            }
        }
        if ($rows.Count -gt 0) {
            $metrics = Get-Content $metricsPath -Raw | ConvertFrom-Json
            $sumUsed = 0.0; $peakUsed = 0.0; $minFree = 999999.0; $sumUtil = 0.0
            foreach ($r in $rows) {
                $sumUsed += $r.usedMiB
                if ($r.usedMiB -gt $peakUsed) { $peakUsed = $r.usedMiB }
                if ($r.freeMiB -lt $minFree) { $minFree = $r.freeMiB }
                $sumUtil += $r.utilPct
            }
            $gpu = [pscustomobject]@{
                source       = 'nvidia-smi -lms 500'
                samples      = $rows.Count
                samplesCsv   = 'gpu_samples.csv'
                usedMiB_avg  = [math]::Round($sumUsed / $rows.Count, 1)
                usedMiB_peak = [math]::Round($peakUsed, 1)
                freeMiB_min  = [math]::Round($minFree, 1)
                utilPct_avg  = [math]::Round($sumUtil / $rows.Count, 1)
            }
            $metrics | Add-Member -NotePropertyName gpu -NotePropertyValue $gpu -Force
            $metrics | Add-Member -NotePropertyName wallSeconds -NotePropertyValue ([math]::Round($stopwatch.Elapsed.TotalSeconds, 1)) -Force
            $metrics | Add-Member -NotePropertyName processExitCode -NotePropertyValue $exitCode -Force
            ($metrics | ConvertTo-Json -Depth 12) | Set-Content -Path $metricsPath -Encoding utf8
            Write-Host ("[run] GPU used avg=" + $gpu.usedMiB_avg + " MiB peak=" + $gpu.usedMiB_peak + " MiB, util avg=" + $gpu.utilPct_avg + "%")
        }
    } catch {
        Write-Host ("[run] WARNING: failed to merge GPU samples: " + $_.Exception.Message) -ForegroundColor Yellow
    }
} elseif (-not (Test-Path $metricsPath)) {
    Write-Host '[run] WARNING: metrics.json was not produced. Check the run log.' -ForegroundColor Yellow
}

if (Test-Path $metricsPath) {
    $m = Get-Content $metricsPath -Raw | ConvertFrom-Json
    Write-Host ('[run] splats=' + $m.ply.splatCount + ' avgFps=' + $m.measure.avgFps + ' avgFrameMs=' + $m.measure.avgFrameMs + ' parseMs=' + $m.ply.parseMs + ' sortMs=' + $m.cpu.depthSortMsAvg + ' shots=' + @($m.screenshots).Count)
}
Get-ChildItem (Join-Path $OutDir 'screenshots') -ErrorAction SilentlyContinue | ForEach-Object { Write-Host ("[run] screenshot: " + $_.FullName) }
exit 0