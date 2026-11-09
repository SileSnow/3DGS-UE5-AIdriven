# run_pipeline.ps1 -- 3DGS 重建流水线一键端到端（参数化）
#
# 流程: [0] 环境自检(可选) -> [1] 位姿准备/COLMAP(known) -> [2] 3DGS 训练 -> [3] 导出 PLY -> [4] held-out 评测
#
# 用法示例:
#   powershell -ExecutionPolicy Bypass -File pipeline/run_pipeline.ps1 -Data data/synthetic/capture -Out data/trained/capture/run1 -Iters 2000 -ResScale 0.4
#   # 只训练（跳过 known 位姿准备）:
#   powershell -ExecutionPolicy Bypass -File pipeline/run_pipeline.ps1 -Data data/synthetic/capture -SkipPose
#   # COLMAP 数据集:
#   powershell -ExecutionPolicy Bypass -File pipeline/run_pipeline.ps1 -Data data/sample/some_colmap -SkipPose
param(
    [Parameter(Mandatory = $true)][string]$Data,
    [string]$Out = "",
    [int]$Iters = 2000,
    [double]$ResScale = 0.4,
    [int]$MaxSplats = 200000,
    [int]$InitPoints = 30000,
    [int]$MaxFrames = 0,
    [int]$MaxPerTile = 64,
    [string]$Val = "",
    [string]$Backend = "puretorch",
    [int]$EvalEvery = 500,
    [int]$SaveEvery = 1000,
    [switch]$SkipPose,
    [switch]$SkipSetup,
    [switch]$SkipEval
)
# 注意：原生程序（python）的 stderr 在 2>&1 时会变成 ErrorRecord；若 EAP=Stop 会被当作终止错误，
# 导致"python 只打了一句 warning 脚本就退出"。这里用 Continue + 逐个检查 $LASTEXITCODE。
$ErrorActionPreference = "Continue"
$PipelineDir = $PSScriptRoot
$ProjectRoot = Split-Path $PipelineDir -Parent
$Py = Join-Path $PipelineDir ".venv\Scripts\python.exe"
$LogDir = Join-Path $ProjectRoot "logs\pipeline"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$DataAbs = if ([System.IO.Path]::IsPathRooted($Data)) { $Data } else { Join-Path $ProjectRoot $Data }
$DataAbs = (Resolve-Path $DataAbs).Path
if (-not $Out) {
    $Name = Split-Path $DataAbs -Leaf
    $Out = Join-Path $ProjectRoot ("data/trained/" + $Name + "/run1")
}
$OutAbs = if ([System.IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path $ProjectRoot $Out }
New-Item -ItemType Directory -Force -Path $OutAbs | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $LogDir ("run_pipeline_" + $Stamp + ".log")
function Log($msg) { $msg | Tee-Object -FilePath $Log -Append }
Log "[run_pipeline] data=$DataAbs out=$OutAbs"
Log "[run_pipeline] args: iters=$Iters res_scale=$ResScale max_splats=$MaxSplats max_frames=$MaxFrames backend=$Backend"

# [0] 环境
if (-not (Test-Path $Py)) {
    if ($SkipSetup) { throw "缺少 venv: $Py" }
    Log "[run_pipeline] venv 不存在，运行 setup_env.ps1"
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PipelineDir "setup_env.ps1")
    if ($LASTEXITCODE -ne 0) { throw "setup_env.ps1 失败" }
}

# [1] 位姿准备（已知位姿直通 metadata.json -> COLMAP + 重投影自检）
if (-not $SkipPose) {
    $Meta = Join-Path $DataAbs "metadata.json"
    if (Test-Path $Meta) {
        Log "[run_pipeline] 位姿准备: 02_sfm.py --mode known"
        & $Py (Join-Path $PipelineDir "02_sfm.py") --mode known --data $DataAbs --out (Join-Path $DataAbs "colmap") 2>&1 | Tee-Object -FilePath $Log -Append
        if ($LASTEXITCODE -ne 0) { throw "02_sfm.py known 失败" }
    } else {
        Log "[run_pipeline] 未发现 metadata.json，跳过 known 位姿准备（假定已有 COLMAP sparse）"
    }
} else {
    Log "[run_pipeline] -SkipPose: 跳过位姿准备"
}

# [2] 训练
$TrainArgs = @((Join-Path $PipelineDir "03_train_3dgs.py"),
    "--data", $DataAbs, "--out", $OutAbs,
    "--iters", $Iters, "--res-scale", $ResScale,
    "--max-splats", $MaxSplats, "--init-points", $InitPoints,
    "--max-per-tile", $MaxPerTile, "--backend", $Backend,
    "--eval-every", $EvalEvery, "--save-every", $SaveEvery)
if ($MaxFrames -gt 0) { $TrainArgs += @("--max-frames", $MaxFrames) }
if ($Val) {
    $ValAbs = if ([System.IO.Path]::IsPathRooted($Val)) { $Val } else { Join-Path $ProjectRoot $Val }
    if (Test-Path $ValAbs) { $TrainArgs += @("--val", $ValAbs) }
}
Log "[run_pipeline] 训练: " + ($TrainArgs -join " ")
& $Py @TrainArgs 2>&1 | Tee-Object -FilePath $Log -Append
if ($LASTEXITCODE -ne 0) { throw "03_train_3dgs.py 失败（见 $Log）" }

# [3] 导出 PLY
Log "[run_pipeline] 导出 PLY: 04_export_ply.py"
& $Py (Join-Path $PipelineDir "04_export_ply.py") --run $OutAbs --out (Join-Path $OutAbs "gaussians.ply") --stats 2>&1 | Tee-Object -FilePath $Log -Append
if ($LASTEXITCODE -ne 0) { throw "04_export_ply.py 失败" }

# [4] held-out 评测
if (-not $SkipEval) {
    if ($Val) {
        $ValRoot = if ([System.IO.Path]::IsPathRooted($Val)) { $Val } else { Join-Path $ProjectRoot $Val }
    } else {
        $ValRoot = $DataAbs
    }
    Log "[run_pipeline] 评测: 05_eval.py --val $ValRoot"
    & $Py (Join-Path $PipelineDir "05_eval.py") --run $OutAbs --val $ValRoot --res-scale $ResScale 2>&1 | Tee-Object -FilePath $Log -Append
    if ($LASTEXITCODE -ne 0) { throw "05_eval.py 失败" }
}

Log "[run_pipeline] DONE -> $OutAbs"
Write-Output "[run_pipeline] 完成: $OutAbs (log: $Log)"