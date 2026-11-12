<#
.SYNOPSIS
    Build the DJI3DGS_UE project (UE 5.8.4) with UnrealBuildTool.

.DESCRIPTION
    IMPORTANT - non-ASCII path constraint:
    The workspace lives under "<repo-parent>" which contains CJK characters.
    MSVC 14.5 / Unreal Build Accelerator split such paths and fail with C1083, so all builds and
    editor runs MUST go through the ASCII junction:
        C:\UEW  ->  <repo-parent>
    The junction is created once by the team lead (mklink /J). This script refuses to run without it.

.PARAMETER Clean
    Delete Intermediate/ and Binaries/ of the project and its plugins before building.

.EXAMPLE
    pwsh -File Scripts/build.ps1
    pwsh -File Scripts/build.ps1 -Clean
#>
param(
    [ValidateSet('DJI3DGS_UEEditor', 'DJI3DGS_UE')]
    [string]$Target = 'DJI3DGS_UEEditor',
    [ValidateSet('Win64')]
    [string]$Platform = 'Win64',
    [ValidateSet('Development', 'Debug')]
    [string]$Configuration = 'Development',
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$UE_ROOT = 'C:/Program Files/Epic Games/UE_5.8'
$BUILD_BAT = Join-Path $UE_ROOT 'Engine/Build/BatchFiles/Build.bat'
$PROJECT = 'C:/UEW/dji_ue5_3dgs/ue5/DJI3DGS_UE/DJI3DGS_UE.uproject'
$LOG_DIR = 'C:/UEW/dji_ue5_3dgs/logs/ue5'
$PROJECT_DIR = Split-Path $PROJECT -Parent

if (-not (Test-Path 'C:/UEW')) {
    throw "ASCII junction C:\UEW is missing. Create it with: cmd /c mklink /J C:\UEW <repo-parent>"
}
if (-not (Test-Path $BUILD_BAT)) { throw "Build.bat not found: $BUILD_BAT" }
if (-not (Test-Path $PROJECT)) { throw "uproject not found: $PROJECT" }
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

if ($Clean) {
    foreach ($dir in @("$PROJECT_DIR/Intermediate", "$PROJECT_DIR/Binaries", "$PROJECT_DIR/Saved")) {
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir; Write-Host "[clean] removed $dir" }
    }
    $pluginDir = Join-Path $PROJECT_DIR 'Plugins/GaussianSplattingForUnrealEngine'
    foreach ($dir in @("$pluginDir/Intermediate", "$pluginDir/Binaries")) {
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir; Write-Host "[clean] removed $dir" }
    }
}

$logFile = Join-Path $LOG_DIR ("build_" + $Target + "_" + $Configuration + "_" + (Get-Date -Format 'yyyyMMdd_HHmmss') + ".log")
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host "[build] " $BUILD_BAT $Target $Platform $Configuration -Project=$PROJECT -WaitMutex -FromMsBuild
Write-Host "[build] log: $logFile"
$output = & $BUILD_BAT $Target $Platform $Configuration "-Project=$PROJECT" -WaitMutex -FromMsBuild 2>&1
$exitCode = $LASTEXITCODE
$stopwatch.Stop()
$elapsed = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
$output | Tee-Object -FilePath $logFile
$summary = "EXITCODE=$exitCode ELAPSED_SEC=$elapsed TARGET=$Target CONFIG=$Configuration"
Write-Host "[build] $summary"
Add-Content -Path $logFile -Value $summary
if ($exitCode -ne 0) {
    $errors = $output | Select-String -Pattern 'error C|error LNK|error MSB' | Select-Object -First 20
    Write-Host "[build] FAILED. First errors:" -ForegroundColor Red
    $errors | ForEach-Object { Write-Host ("  " + $_.Line) -ForegroundColor Red }
    exit $exitCode
}

$dll = Join-Path $PROJECT_DIR "Binaries/Win64/UnrealEditor-DJI3DGS_UE.dll"
if (Test-Path $dll) {
    $dllInfo = Get-Item $dll
    Write-Host ("[build] OK: " + $dllInfo.FullName + " (" + $dllInfo.Length + " bytes, " + $dllInfo.LastWriteTime + ")")
} else {
    Write-Host "[build] WARNING: expected binary not found: $dll"
}
exit 0
