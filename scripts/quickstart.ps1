<#
.SYNOPSIS
    Phase-1 一键演示：启动仿真 Agent -> 跑演示场景 -> 关闭 Agent。
.DESCRIPTION
    需要本机已安装 Python 3.12+；真实 LLM 模式需要 Ollama + qwen3.5:4b。
    无 LLM 时使用 -NoLLM（全部场景 scripted，仍会完整走安全层与执行链路）。
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\quickstart.ps1
    powershell -ExecutionPolicy Bypass -File scripts\quickstart.ps1 -Scenario P1 -Model qwen3.5:4b
    powershell -ExecutionPolicy Bypass -File scripts\quickstart.ps1 -NoLLM
#>
param(
    [string]$Scenario = "all",
    [int]$Port = 8765,
    [string]$Model = "qwen3.5:4b",
    [switch]$NoLLM
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "llm_drone")

Write-Host "=== start sim agent on :$Port ===" -ForegroundColor Cyan
$server = Start-Process -FilePath "python" -ArgumentList @("-m", "sim.server", "--port", "$Port", "--time-scale", "20") -PassThru -WindowStyle Hidden
try {
    $ok = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/health" -TimeoutSec 2
            if ($h.ok) { $ok = $true; break }
        } catch { }
    }
    if (-not $ok) { throw "sim server did not become healthy on port $Port" }
    Write-Host "sim agent ready (backend=$($h.backend), time_scale=$($h.time_scale))" -ForegroundColor Green

    $demoArgs = @("-m", "orchestrator.run_demo", "--agent-url", "http://127.0.0.1:$Port", "--scenario", $Scenario, "--out", "demo/runs")
    if ($NoLLM) {
        $demoArgs += @("--scripted-for", "P1,P2,P3,A1,A2,A3,A4,A5,A6,A7,A8,A9,A10")
    } else {
        $demoArgs += @("--model", $Model)
    }
    Write-Host "=== run demo: $Scenario ===" -ForegroundColor Cyan
    python @demoArgs
    if ($LASTEXITCODE -ne 0) { throw "demo failed (exit $LASTEXITCODE)" }
    Write-Host "demo done -> llm_drone/demo/runs/ (see metrics.json / transcript.md)" -ForegroundColor Green
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force; Write-Host "sim agent stopped" }
}
