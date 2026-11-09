# thermal_guard2.ps1 -- 严格限核守护：常驻限核 + 超温降载/熔断
$ErrorActionPreference = 'Continue'
$base = 'C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs'
$log = Join-Path $base 'logs\thermal_monitor.log'
New-Item -ItemType Directory -Force -Path (Join-Path $base 'logs') | Out-Null
function GetCpuTempC { try { $c = Get-Counter '\Thermal Zone Information(*)\Temperature' -ErrorAction Stop; $m = ($c.CounterSamples | Measure-Object -Property CookedValue -Maximum).Maximum; if ($null -ne $m) { [math]::Round($m - 273.15, 1) } else { $null } } catch { $null } }
function GetGpuTempC { try { $v = (nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>$null) -split "`n"; if ($v.Count -gt 0) { [math]::Round([double]$v[0], 1) } else { $null } } catch { $null } }
function GetLoadPct { try { [math]::Round((Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average, 0) } catch { $null } }
function GetHeavyProcs { Get-Process -Name python,UnrealEditor -ErrorAction SilentlyContinue | Where-Object { $_.WorkingSet64 -gt 100MB } }
$state = 'normal'; $hotCnt = 0; $coolCnt = 0
while ($true) {
  $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  $ct = GetCpuTempC; $gt = GetGpuTempC; $ld = GetLoadPct
  $procs = @(GetHeavyProcs)
  $names = ($procs | ForEach-Object { $_.ProcessName + '#' + $_.Id }) -join ','
  $maxT = $ct; if ($gt -ne $null -and ($maxT -eq $null -or $gt -gt $maxT)) { $maxT = $gt }
  if ($maxT -eq $null) { $maxT = 0 }
  if ($maxT -ge 72) { $hotCnt++; $coolCnt = 0 } elseif ($maxT -le 68) { $coolCnt++; $hotCnt = 0 }
  if ($state -eq 'normal' -and $hotCnt -ge 1) {
    foreach ($p in $procs) { try { $p.PriorityClass = 'Idle'; $p.ProcessorAffinity = [IntPtr]0x000F } catch {} }
    $state = 'throttled'
    Add-Content -Path $log -Value ($ts + ' THROTTLE cpu=' + $ct + 'C gpu=' + $gt + 'C load=' + $ld + '% procs=' + $names)
  } elseif ($state -eq 'throttled' -and $coolCnt -ge 3) {
    foreach ($p in $procs) { try { $p.PriorityClass = 'BelowNormal'; $p.ProcessorAffinity = [IntPtr]0x00FF } catch {} }
    $state = 'normal'; $hotCnt = 0
    Add-Content -Path $log -Value ($ts + ' RESTORE cpu=' + $ct + 'C gpu=' + $gt + 'C load=' + $ld + '% procs=' + $names)
  } elseif ($state -eq 'normal') {
    foreach ($p in $procs) { try { if ($p.PriorityClass -ne 'BelowNormal') { $p.PriorityClass = 'BelowNormal' }; $p.ProcessorAffinity = [IntPtr]0x00FF } catch {} }
    Add-Content -Path $log -Value ($ts + ' cpu=' + $ct + 'C gpu=' + $gt + 'C load=' + $ld + '% state=' + $state + ' procs=' + $names)
  } else {
    Add-Content -Path $log -Value ($ts + ' cpu=' + $ct + 'C gpu=' + $gt + 'C load=' + $ld + '% state=' + $state + ' procs=' + $names)
  }
  if ($maxT -ge 82) { foreach ($p in $procs) { if ($p.ProcessName -eq 'python') { try { Stop-Process -Id $p.Id -Force; Add-Content -Path $log -Value ($ts + ' KILLED python#' + $p.Id + ' (temp=' + $maxT + 'C)') } catch {} } } }
  Start-Sleep -Seconds 10
}
