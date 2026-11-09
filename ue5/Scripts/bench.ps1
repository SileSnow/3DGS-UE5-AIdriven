<#
.SYNOPSIS
    Run the 3DGS performance sweep (50k / 200k / 500k / 1M splats) through run_headless.ps1
    and aggregate the per-count metrics.json files into ue5/results/<run>/summary.json + summary.md.
#>
param(
    [string[]]$SplatCounts = @('50000', '200000', '500000', '1000000'),
    [string]$Kind = 'sphere',
    [string]$RunName = '',
    [int]$Warmup = 6,
    [int]$Measure = 8,
    [int]$Shots = 2,
    [int]$ResX = 1280,
    [int]$ResY = 720,
    [int]$SortIters = 5,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$UE5 = 'C:/UEW/dji_ue5_3dgs/ue5'
$DATA = Join-Path $UE5 'test_data'
if ([string]::IsNullOrWhiteSpace($RunName)) { $RunName = 'bench_' + (Get-Date -Format 'yyyyMMdd_HHmmss') }
$RUN_DIR = Join-Path (Join-Path $UE5 'results') $RunName
New-Item -ItemType Directory -Force -Path $RUN_DIR | Out-Null
$RUNNER = Join-Path $UE5 'Scripts/run_headless.ps1'

Write-Host "[bench] run=$RunName dir=$RUN_DIR"
$rows = @()
foreach ($count in $SplatCounts) {
    $k = [int]([double]$count / 1000)
    $ply = Join-Path $DATA ("{0}_{1}k.ply" -f $Kind, $k)
    if (-not (Test-Path $ply)) { Write-Host "[bench] SKIP missing $ply" -ForegroundColor Yellow; continue }
    $outDir = Join-Path $RUN_DIR $count
    Write-Host "[bench] === $Kind $count splats ==="
    & $RUNNER -Ply $ply -OutDir $outDir -Warmup $Warmup -Measure $Measure -Shots $Shots -ResX $ResX -ResY $ResY -SortIters $SortIters -Force:$Force
    $metricsPath = Join-Path $outDir 'metrics.json'
    if (Test-Path $metricsPath) {
        $m = Get-Content $metricsPath -Raw | ConvertFrom-Json
        $gpuAvg = $null
        $gpuPeak = $null
        $gpuUtil = $null
        if ($null -ne $m.gpu) {
            $gpuAvg = [double]$m.gpu.usedMiB_avg
            $gpuPeak = [double]$m.gpu.usedMiB_peak
            $gpuUtil = [double]$m.gpu.utilPct_avg
        }
        $rows += [pscustomobject]@{
            splats         = [int]$m.ply.splatCount
            plyMB          = [math]::Round([double]$m.ply.fileBytes / 1MB, 1)
            parseMs        = [math]::Round([double]$m.ply.parseMs, 1)
            setPointsMs    = [math]::Round([double]$m.ply.setPointsMs, 1)
            niagaraSetupMs = [math]::Round([double]$m.scene.niagaraSetupMs, 1)
            avgFps         = [math]::Round([double]$m.measure.avgFps, 2)
            avgFrameMs     = [math]::Round([double]$m.measure.avgFrameMs, 2)
            p99FrameMs     = [math]::Round([double]$m.measure.p99FrameMs, 2)
            cpuSortMs      = [math]::Round([double]$m.cpu.depthSortMsAvg, 2)
            cpuFrontEndMs  = [math]::Round([double]$m.cpu.frontEndMsAvg, 2)
            visibleSplats  = [int]$m.cpu.visibleSplatsAfterScreenSizeCull
            gpuUsedAvgMiB  = $gpuAvg
            gpuUsedPeakMiB = $gpuPeak
            gpuUtilPct     = $gpuUtil
            screenshots    = (@($m.screenshots) -join ";")
            metricsPath    = (Join-Path $count "metrics.json")
        }
    } else {
        Write-Host "[bench] WARNING: no metrics for $count" -ForegroundColor Yellow
    }
}

$summary = [pscustomobject]@{
    schema     = 'dji_ue5_3dgs/ue5_bench/v1'
    runName    = $RunName
    timestamp  = (Get-Date).ToString('o')
    kind       = $Kind
    resolution = ("" + $ResX + "x" + $ResY)
    warmupSec  = $Warmup
    measureSec = $Measure
    gpu        = 'NVIDIA RTX 5060 Laptop 8GB'
    engine     = 'UE 5.8.4'
    rows       = $rows
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $RUN_DIR 'summary.json') -Encoding utf8

$md = @()
$md += "# UE5 3DGS 性能测试 $RunName"
$md += ''
$md += ("- 时间：" + (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))
$md += "- 引擎：UE 5.8.4；渲染器：移植的 Italink GaussianSplattingForUnrealEngine（Niagara GPU 粒子）"
$md += ("- 分辨率：" + $ResX + "x" + $ResY + "；warmup=" + $Warmup + "s，measure=" + $Measure + "s；数据：" + $Kind + "（UE 坐标/厘米）")
$md += ''
$md += "| splats | PLY MB | parse ms | setPoints ms | avg FPS | avg frame ms | p99 ms | CPU sort ms | CPU front-end ms | GPU used avg/peak MiB |"
$md += "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
foreach ($r in $rows) {
    $gpu = 'n/a'
    if ($null -ne $r.gpuUsedAvgMiB) { $gpu = ("" + $r.gpuUsedAvgMiB + "/" + $r.gpuUsedPeakMiB) }
    $md += ("| " + $r.splats + " | " + $r.plyMB + " | " + $r.parseMs + " | " + $r.setPointsMs + " | " + $r.avgFps + " | " + $r.avgFrameMs + " | " + $r.p99FrameMs + " | " + $r.cpuSortMs + " | " + $r.cpuFrontEndMs + " | " + $gpu + " |")
}
$md += ''
$md += "原始数据：各档位 metrics.json / frames.csv / gpu_samples.csv / screenshots/。"
$md | Set-Content -Path (Join-Path $RUN_DIR 'summary.md') -Encoding utf8
Write-Host "[bench] summary: $RUN_DIR/summary.md"
$rows | Format-Table -AutoSize | Out-String | Write-Host
