$ErrorActionPreference = 'SilentlyContinue'
$log = 'C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\logs\thermal_monitor.log'
function T { $c = Get-Counter '\Thermal Zone Information(*)\Temperature' -ErrorAction SilentlyContinue; $m = ($c.CounterSamples | Measure-Object -Property CookedValue -Maximum).Maximum; if ($m) { return [math]::Round($m - 273.15, 1) } return $null }
function G { $v = nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>$null; if ($v) { return [math]::Round([double]($v | Select-Object -First 1), 1) } return $null }
function P { return @(Get-Process python,UnrealEditor -ErrorAction SilentlyContinue | Where-Object { $_.WorkingSet64 -gt 100MB }) }
while ($true) {
  $t = T; $g = G; $ts = Get-Date -Format 'HH:mm:ss'
  $ps = P
  $ids = ($ps | ForEach-Object { $_.ProcessName + '#' + $_.Id }) -join ','
  $hot = (($t -ne $null -and $t -ge 70) -or ($g -ne $null -and $g -ge 70))
  foreach ($p in $ps) {
    try {
      if ($hot) { $p.PriorityClass = 'Idle'; $p.ProcessorAffinity = [IntPtr]15 } else { $p.PriorityClass = 'BelowNormal'; $p.ProcessorAffinity = [IntPtr]255 }
    } catch {}
  }
  $line = ('{0} cpu={1}C gpu={2}C mode={3} procs={4}' -f $ts, $t, $g, $(if($hot){'LIMIT4'}else{'LIMIT8'}), $ids)
  Add-Content -Path $log -Value $line
  if ($t -ne $null -and $t -ge 85) { foreach ($p in $ps) { if ($p.ProcessName -eq 'python') { Stop-Process -Id $p.Id -Force; Add-Content -Path $log -Value ('{0} KILLED python#{1} temp={2}C' -f $ts, $p.Id, $t) } } }
  Start-Sleep -Seconds 10
}
