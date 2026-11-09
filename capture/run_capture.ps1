<#
.SYNOPSIS
    One-click UE5.8 synthetic DJI-Mini aerial capture (scene build + render + metadata).

.DESCRIPTION
    Launches UnrealEditor.exe with -ExecutePythonScript="capture_synth.py ...".
    The editor quits by itself when the python script returns (PythonScriptPlugin defers
    QUIT_EDITOR).  All UE output is tee'd to logs/capture/ue_<mode>_<timestamp>.log.

    The project is addressed through the ASCII junction C:\UEW (UE has known issues with
    non-ASCII paths).  C:\UEW -> C:\Users\Lenovo\Desktop\GAIA项目

.PARAMETER Mode
    build | probe | sample | full

.PARAMETER TrainFrames
    Limit the number of training views (0 = all; sample defaults to 30).

.PARAMETER ValFrames
    Number of held-out validation views (-1 = default: 10 for sample, 15 for full).

.PARAMETER Exposure
    Fixed exposure value (post process white point luminance; min == max so it is fixed).

.PARAMETER Sun
    Directional light intensity in lux.

.PARAMETER Rebuild
    Delete the saved campus map and regenerate the procedural scene from scratch.

.EXAMPLE
    .\run_capture.ps1 -Mode probe -Rebuild

.EXAMPLE
    .\run_capture.ps1 -Mode full
#>
param(
    [ValidateSet("build", "probe", "sample", "full")]
    [string]$Mode = "sample",
    [int]$TrainFrames = 0,
    [int]$ValFrames = -1,
    [double]$Exposure = 0.6,
    [double]$Sun = 30.0,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

$UERoot      = "C:\Program Files\Epic Games\UE_5.8"
$Editor      = Join-Path $UERoot "Engine\Binaries\Win64\UnrealEditor.exe"
$ProjectRoot = "C:\UEW\dji_ue5_3dgs"
$Project     = Join-Path $ProjectRoot "capture\UE5Synth\UE5Synth.uproject"
$PyScript    = "C:/UEW/dji_ue5_3dgs/capture/scripts/capture_synth.py"
$LogDir      = Join-Path $ProjectRoot "logs\capture"

if (-not (Test-Path $Editor))   { throw "UnrealEditor.exe not found: $Editor" }
if (-not (Test-Path $Project))  { throw "project not found: $Project" }
if (-not (Test-Path $PyScript)) { throw "python script not found: $PyScript" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $LogDir (("ue_{0}_{1}.log" -f $Mode, $stamp))

$pyArgs = "--mode $Mode --exposure $Exposure --sun $Sun"
if ($TrainFrames -gt 0) { $pyArgs += " --train-frames $TrainFrames" }
if ($ValFrames -ge 0)   { $pyArgs += " --val-frames $ValFrames" }
if ($Rebuild)           { $pyArgs += " --rebuild" }

$editorArgs = @(
    $Project,
    "-ExecutePythonScript=$PyScript $pyArgs",
    "-windowed",
    "-resx=960",
    "-resy=540",
    "-nosplash",
    "-unattended",
    "-nopause",
    "-stdout",
    "-FullStdOutLogOutput",
    "-log"
)

Write-Host "=== UE5.8 synthetic DJI-Mini capture ==="
Write-Host "editor   : $Editor"
Write-Host "project  : $Project"
Write-Host "python   : $PyScript $pyArgs"
Write-Host "log      : $Log"
Write-Host "started  : $(Get-Date -Format o)"

$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    & $Editor @editorArgs 2>&1 | Tee-Object -FilePath $Log
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host "editor launch failed: $($_.Exception.Message)"
    $exitCode = -1
}
$sw.Stop()
$elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)
Write-Host "=== editor exited code=$exitCode elapsed=$($elapsed)s ==="
exit $exitCode
