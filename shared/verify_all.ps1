# verify_all.ps1 -- Lead 最终验收脚本（只读检查 + 轻量冒烟）
$ErrorActionPreference = 'Continue'
$base = 'C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs'
$pass = 0; $fail = 0; $warn = 0
function Check($name, $cond, $detail) { if ($cond) { Write-Host ('[PASS] ' + $name + '  ' + $detail) -ForegroundColor Green; $script:pass++ } else { Write-Host ('[FAIL] ' + $name + '  ' + $detail) -ForegroundColor Red; $script:fail++ } }
function CheckWarn($name, $cond, $detail) { if ($cond) { Write-Host ('[PASS] ' + $name + '  ' + $detail) -ForegroundColor Green; $script:pass++ } else { Write-Host ('[WARN] ' + $name + '  ' + $detail) -ForegroundColor Yellow; $script:warn++ } }

Write-Host '===== 1. 文档与代码交付物 ====='
Check 'README' (Test-Path (Join-Path $base 'README.md')) ''
Check 'CONVENTIONS' (Test-Path (Join-Path $base 'shared\CONVENTIONS.md')) ''
Check 'research 01' (Test-Path (Join-Path $base 'docs\research\01_DJI_Mini_SDK能力矩阵.md')) ''
Check 'research SUMMARY' (Test-Path (Join-Path $base 'docs\research\SUMMARY.md')) ''
CheckWarn 'research 02-05' ((Get-ChildItem (Join-Path $base 'docs\research') -Filter '0*.md' | Measure-Object).Count -ge 6) ''
Check 'pipeline colmap_io' (Test-Path (Join-Path $base 'pipeline\colmap_io.py')) ''
CheckWarn 'pipeline train script' ((Get-ChildItem (Join-Path $base 'pipeline') -Filter '*train*.py' | Measure-Object).Count -ge 1) ''
CheckWarn 'capture scripts' ((Get-ChildItem (Join-Path $base 'capture\scripts') -Filter '*.py' -ErrorAction SilentlyContinue | Measure-Object).Count -ge 2) ''
Check 'ue5 uproject' (Test-Path (Join-Path $base 'ue5\DJI3DGS_UE\DJI3DGS_UE.uproject')) ''
CheckWarn 'ue5 results' ((Get-ChildItem (Join-Path $base 'ue5\results') -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count -ge 1) ''

Write-Host '===== 2. 数据产物 ====='
CheckWarn 'synthetic images' ((Get-ChildItem (Join-Path $base 'data\synthetic') -Recurse -Filter '*.png' -ErrorAction SilentlyContinue | Measure-Object).Count -ge 20) ''
CheckWarn 'synthetic metadata' (Test-Path (Join-Path $base 'data\synthetic\capture\metadata.json')) ''
CheckWarn 'trained PLY' ((Get-ChildItem (Join-Path $base 'data\trained') -Recurse -Filter '*.ply' -ErrorAction SilentlyContinue | Measure-Object).Count -ge 1) ''

Write-Host '===== 3. 轻量冒烟测试 ====='
$py = Join-Path $base 'pipeline\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$out = & $py (Join-Path $base 'pipeline\colmap_io.py') 2>&1 | Out-String
Check 'colmap_io self-check' ($out -match 'max=.*e-1[0-9]|max=0') ('output: ' + ($out.Trim().Split([Environment]::NewLine)[-3..-1] -join ' | '))

Write-Host '===== 4. 报告 ====='
$report = Join-Path $base 'report\DJI_Mini_UE5_3DGS_可行性验证报告.md'
if (Test-Path $report) {
  $txt = Get-Content $report -Raw
  $ph = ([regex]::Matches($txt, '【[^】]*】')).Count
  CheckWarn 'report placeholders cleared' ($ph -eq 0) ('remaining ' + $ph)
  Check 'report length > 40k' ($txt.Length -gt 40000) ('chars=' + $txt.Length)
} else { Check 'report exists' $false '' }
Write-Host ''
Write-Host ('SUMMARY: PASS=' + $pass + ' FAIL=' + $fail + ' WARN=' + $warn)
