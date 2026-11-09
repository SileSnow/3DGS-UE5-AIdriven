param(
    [int]$TimeoutSec = 900,
    [switch]$Force,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$RepoRoot = Split-Path $Here -Parent
$BaseDir = Split-Path $RepoRoot -Parent
$AsciiBase = "C:\UEW"
$UERoot = "C:\Program Files\Epic Games\UE_5.8"
$Editor = Join-Path $UERoot "Engine\Binaries\Win64\UnrealEditor.exe"
$ProjectLocal = Join-Path $RepoRoot "capture\UE5Synth\UE5Synth.uproject"
$LogDir = Join-Path $RepoRoot "report\flight_logs"
if (-not (Test-Path -LiteralPath $AsciiBase)) { throw "ASCII junction C:\UEW missing" }
if (-not (Test-Path -LiteralPath $Editor)) { throw "UnrealEditor.exe not found: $Editor" }
if (-not (Test-Path -LiteralPath $ProjectLocal)) { throw "UE project missing" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Convert-ToAsciiUePath([string]$AbsPath) {
    $full = [System.IO.Path]::GetFullPath($AbsPath)
    $baseFull = [System.IO.Path]::GetFullPath($BaseDir)
    if ($full.StartsWith($baseFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        $full = $AsciiBase + $full.Substring($baseFull.Length)
    }
    if ($full -match '[^\x00-\x7F]') { throw "path not ASCII after junction: $full" }
    return ($full.Replace("\", "/"))
}

$otherUe = @(Get-Process -Name "UnrealEditor","UnrealEditor-Cmd" -ErrorAction SilentlyContinue)
if ($otherUe.Count -gt 0 -and -not $Force) { throw "another UnrealEditor is running ($($otherUe.Count)); -Force overrides" }
$thermal = $null; $gpuTemp = $null
try { $thermal = [math]::Round(((Get-Counter '\Thermal Zone Information(*)\Temperature' -ErrorAction Stop).CounterSamples | Measure-Object -Property CookedValue -Maximum).Maximum - 273.15, 1) } catch {}
try { $gpuTemp = [math]::Round([double](nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>$null | Select-Object -First 1), 1) } catch {}
if (-not $Force) {
    if ($null -ne $thermal -and $thermal -ge 80) { throw "CPU $thermal C >= 80 C" }
    if ($null -ne $gpuTemp -and $gpuTemp -ge 80) { throw "GPU $gpuTemp C >= 80 C" }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $LogDir ("flight_" + $stamp + ".log")
$ErrLog = Join-Path $LogDir ("flight_" + $stamp + "_stderr.log")
$projectUe = Convert-ToAsciiUePath $ProjectLocal
$pyUe = Convert-ToAsciiUePath (Join-Path $Here "render_flight.py")
$argLine = ($projectUe + ' -ExecutePythonScript="' + $pyUe + '" ' +
            "-windowed -resx=960 -resy=540 -nosplash -unattended -nopause -stdout -FullStdOutLogOutput -log")
if ($DryRun) { Write-Host $argLine; exit 0 }
Write-Host "=== cinematic flight render ==="
Write-Host "temp cpu=$thermal C gpu=$gpuTemp C"
Write-Host "log $Log"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $Editor -ArgumentList $argLine -RedirectStandardOutput $Log -RedirectStandardError $ErrLog -PassThru -WindowStyle Minimized
$affinitySet = $false
while ($true) {
    $proc.Refresh()
    if ($proc.HasExited) { break }
    if (-not $affinitySet) {
        try { $proc.ProcessorAffinity = [IntPtr]0x000F; $proc.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal; $affinitySet = $true; Write-Host "affinity=0x000F pid=$($proc.Id)" } catch {}
    }
    if ($sw.Elapsed.TotalSeconds -gt $TimeoutSec) {
        Write-Host "TIMEOUT -> killing pid $($proc.Id)"
        & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null
        break
    }
    Start-Sleep -Seconds 2
}
$sw.Stop()
Write-Host ("exit elapsed={0:N1}s code={1}" -f $sw.Elapsed.TotalSeconds, $proc.ExitCode)
$frames = @(Get-ChildItem (Join-Path $Here "flight_raw") -Filter "f*.png" -ErrorAction SilentlyContinue)
Write-Host ("frames={0}" -f $frames.Count)
