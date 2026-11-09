<#
.SYNOPSIS
    一键运行 Phase-1 单测 + Lead 独立黑盒验收。
.DESCRIPTION
    - 单元测试：llm_drone/tests（sim/safety/orchestrator，纯标准库，无需 LLM）
    - 黑盒验收：llm_drone/logs/lead/verify_acceptance.py（自动启动 sim server，端口 8766）
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "llm_drone")

Write-Host "=== [1/2] unit tests ===" -ForegroundColor Cyan
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "unit tests failed (exit $LASTEXITCODE)" }

Write-Host "=== [2/2] lead black-box acceptance ===" -ForegroundColor Cyan
python "logs\lead\verify_acceptance.py" --port 8766
if ($LASTEXITCODE -ne 0) { throw "acceptance failed (exit $LASTEXITCODE)" }

Write-Host "ALL PASS ✔" -ForegroundColor Green
