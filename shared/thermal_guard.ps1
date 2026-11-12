# thermal_guard.ps1 -- 温度/负载守护：超温自动降载，降温恢复
$ErrorActionPreference = 'Continue'
$base = Split-Path $PSScriptRoot -Parent
$log = Join-Path $base 'logs\thermal_monitor.log'
New-Item -ItemType Directory -Force -Path (Join-Path $base 'logs') | Out-Null
function GetCpuTempC { try { $c = Get-Counter '\Thermal Zone Information(*)\Temperature' -ErrorAction Stop; $m = ($c.CounterSamples | Measure-Object -Property CookedValue -Maximum).Maximum; if ($null -ne $m) { [math]::Round($m - 273.15, 1) } else { $null } } catch { $null } }
function GetGpuTempC { try { $v = (nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>$null) -split "`n"; if ($v.Count -gt 0) { [math]::Round([double]$v[0], 1) } else { $null } } catch { $null } }
function GetLoadPct { try { [math]::Round((Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average, 0) } catch { $null } }
function GetHeavyProcs { Get-Process -Name python,UnrealEditor -ErrorAction SilentlyContinue | Where-Object { $_.WorkingSet64 -gt 300MB } }
$state = 'normal'
$hotSamples = 0; $coolSamples = 0
while ($true) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  $ct = GetCpuTempC; $gt = GetGpuTempC; $ld = GetLoadPct
  $hot = (($ct -ne $null -and $ct -ge 78) -or ($gt -ne $null -and $gt -ge 78))
  if ($hot) { $hotSamples++; $coolSamples = 0 } else { $coolSamples++; $hotSamples = 0 }
  $procs = @(GetHeavyProcs)
  $names = ($procs | ForEach-Object { $_.ProcessName + '#' + $_.Id }) -join ','
  if ($hot -and $hotSamples -ge 2 -and $state -eq 'normal') {
    foreach ($p in $procs) { try { $p.PriorityClass = 'Idle'; $p.ProcessorAffinity = [IntPtr]0x0FFF } catch {} }
    $state = 'throttled'
    Add-Content -Path $log -Value ($ts + ' THROTTLE cpu=' + $ct + 'C gpu=' + $gt + 'C load=' + $ld + '% procs=' + $names)
  } elseif ((-not $hot) -and $coolSamples -ge 3 -and $state -eq 'throttled') {
    foreach ($p in $procs) { try { $p.PriorityClass = 'BelowNormal'; $p.ProcessorAffinity = [IntPtr]0x3FFF } catch {} }
    $state = 'normal'
    Add-Content -Path $log -Value ($ts + ' RESTORE cpu=' + $ct + 'C gpu=' + $gt + 'C load=' + $ld + '% procs=' + $names)
  } else {
    Add-Content -Path $log -Value ($ts + ' cpu=' + $ct + 'C gpu=' + $gt + 'C load=' + $ld + '% state=' + $state + ' procs=' + $names)
  }
  Start-Sleep -Seconds 15
}
