# try_gsplat2.ps1 -- 在 vcvars64 环境 + NVCC_PREPEND_FLAGS(-allow-unsupported-compiler) 下
# 重试 torch cpp_extension 冒烟 + gsplat JIT 编译。结果追加到 logs/pipeline/gsplat_attempt2.log
$ErrorActionPreference = "Continue"
$PipelineDir = $PSScriptRoot
$Log = Join-Path $PipelineDir "..\logs\pipeline\gsplat_attempt2.log"
$CudaHome = Join-Path $PipelineDir ".venv\Lib\site-packages\nvidia\cu13"
$Python = Join-Path $PipelineDir ".venv\Scripts\python.exe"
$VcVars = "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"
"" | Out-File -FilePath $Log -Encoding utf8 -Append
"[try_gsplat2] start $(Get-Date -Format o)" | Out-File -FilePath $Log -Encoding utf8 -Append
$Smoke = @'
import torch
from torch.utils.cpp_extension import load_inline
src = "torch::Tensor f(torch::Tensor x){ return x + 1; }"
mod = load_inline(name="smoke_cuda13b", cpp_sources="torch::Tensor f(torch::Tensor x);", cuda_sources=src, functions=["f"], verbose=True)
x = torch.zeros(4, device="cuda")
print("SMOKE_OK", mod.f(x).tolist())
'@
$SmokePy = Join-Path $PipelineDir "_gsplat_smoke2.py"
Set-Content -Path $SmokePy -Value $Smoke -Encoding UTF8
$GsplatTest = @'
import torch, gsplat, time
print("gsplat", gsplat.__version__)
print("cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0))
from gsplat import rasterization
N, D = 512, 6
torch.manual_seed(0)
means = torch.randn(N, 3, device="cuda", requires_grad=True)
quats = torch.nn.functional.normalize(torch.randn(N, 4, device="cuda"), dim=-1).requires_grad_(True)
scales = torch.rand(N, 3, device="cuda").requires_grad_(True) * 0.1
opac = torch.rand(N, device="cuda", requires_grad=True)
colors = torch.rand(N, D, device="cuda", requires_grad=True)
viewmats = torch.eye(4, device="cuda")[None]
K = torch.tensor([[100., 0, 32], [0, 100., 32], [0, 0, 1.]], device="cuda")[None]
t0 = time.time()
img, alpha, meta = rasterization(means, quats, scales, opac, colors, viewmats, K, 64, 64, sh_degree=1)
loss = img.square().mean() + alpha.mean()
loss.backward()
print("FORWARD_OK", img.shape, "grad", means.grad.abs().mean().item(), "t", round(time.time()-t0,3))
'@
$GsplatPy = Join-Path $PipelineDir "_gsplat_test2.py"
Set-Content -Path $GsplatPy -Value $GsplatTest -Encoding UTF8
$Inner = @"
call "$VcVars" >nul 2>&1
set DISTUTILS_USE_SDK=1
set CC=cl
set CXX=cl
set CUDA_HOME=$CudaHome
set CUDA_PATH=$CudaHome
set NVCC_PREPEND_FLAGS=-allow-unsupported-compiler
set TORCH_CUDA_ARCH_LIST=12.0
set MAX_JOBS=16
set PATH=$CudaHome\bin;$CudaHome\nvvm\bin;%PATH%
echo [try_gsplat2] vcvars done
where cl
"$Python" "$SmokePy"
echo [try_gsplat2] smoke exit=%ERRORLEVEL%
"$Python" "$GsplatPy"
echo [try_gsplat2] gsplat exit=%ERRORLEVEL%
"@
$InnerFile = Join-Path $PipelineDir "_try_gsplat2_inner.cmd"
Set-Content -Path $InnerFile -Value $Inner -Encoding OEM
cmd.exe /c $InnerFile *>> $Log
"[try_gsplat2] done $(Get-Date -Format o)" | Out-File -FilePath $Log -Encoding utf8 -Append