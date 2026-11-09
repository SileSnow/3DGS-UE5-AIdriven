# setup_env.ps1 -- 创建项目本地 venv（复用全局 torch）并安装 3DGS 重建流水线依赖
# 用法:
#   powershell -ExecutionPolicy Bypass -File pipeline\setup_env.ps1
#   powershell -ExecutionPolicy Bypass -File pipeline\setup_env.ps1 -Force   # 重建 venv
param(
    [switch]$Force,
    [switch]$InstallGsplat
)
$ErrorActionPreference = "Stop"
$PipelineDir = $PSScriptRoot
$ProjectRoot = Split-Path $PipelineDir -Parent
$VenvDir = Join-Path $PipelineDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "[setup_env] project root : $ProjectRoot"
Write-Host "[setup_env] venv dir     : $VenvDir"

# 0) 基础 Python（全局，带 torch 2.13.0+cu130）
$BasePython = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $BasePython) { throw "python not found on PATH" }
Write-Host "[setup_env] base python  : $BasePython"
& $BasePython -c "import torch, sys; print('[setup_env] base torch  :', torch.__version__, 'cuda', torch.version.cuda, 'avail', torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { throw "base python 缺少 torch，请先安装 torch" }

# 1) venv（--system-site-packages 复用全局 torch，避免重复下载 ~3GB）
if ($Force -and (Test-Path $VenvDir)) {
    Write-Host "[setup_env] -Force: 删除旧 venv"
    Remove-Item -Recurse -Force $VenvDir
}
if (-not (Test-Path $VenvPython)) {
    Write-Host "[setup_env] 创建 venv (--system-site-packages) ..."
    & $BasePython -m venv --system-site-packages $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "venv 创建失败" }
} else {
    Write-Host "[setup_env] venv 已存在，复用"
}

# 2) 安装依赖
$Req = Join-Path $PipelineDir "requirements.txt"
Write-Host "[setup_env] pip install -r $Req ..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $Req
if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements.txt 失败" }

if ($InstallGsplat) {
    Write-Host "[setup_env] 尝试安装 gsplat（可选后端）..."
    & $VenvPython -m pip install gsplat
}

# 3) 自检：导入 + 打印版本（同时写入 pipeline/ENV.md 的原始数据）
$Check = @'
import importlib, sys, json
mods = ["torch", "numpy", "scipy", "cv2", "PIL", "plyfile", "pycolmap", "tqdm", "matplotlib", "imageio_ffmpeg", "exifread"]
out = {"python": sys.version.split()[0], "executable": sys.executable}
for m in mods:
    try:
        mod = importlib.import_module(m)
        out[m] = getattr(mod, "__version__", "unknown")
    except Exception as e:
        out[m] = "MISSING: %s" % e
try:
    import torch
    out["torch_cuda"] = torch.version.cuda
    out["cuda_available"] = bool(torch.cuda.is_available())
    if torch.cuda.is_available():
        out["gpu"] = torch.cuda.get_device_name(0)
except Exception as e:
    out["torch_cuda"] = "ERR: %s" % e
print(json.dumps(out, indent=2))
'@
$Tmp = Join-Path $env:TEMP "gs_pipeline_env_check.py"
Set-Content -Path $Tmp -Value $Check -Encoding UTF8
& $VenvPython $Tmp
if ($LASTEXITCODE -ne 0) { throw "环境自检失败" }
Write-Host "[setup_env] OK. 用以下方式激活: & '$VenvPython' 或 .venv\Scripts\activate"
