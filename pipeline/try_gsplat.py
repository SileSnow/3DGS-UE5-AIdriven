"""try_gsplat.py -- 实测 gsplat 是否可在本机（Windows / Python 3.14 / torch 2.13.0+cu130 / sm_120）
JIT 编译成功。失败则记录原因，训练回退到 pipeline/puretorch_splatting。

实测布局（2026-11-08）：pip 安装 nvidia-cuda-nvcc / nvidia-cuda-runtime 后，CUDA 13 工具链位于
  <venv>/Lib/site-packages/nvidia/cu13/{bin/nvcc.exe, include/, lib/x64/cudart.lib, nvvm/bin/cicc.exe}
直接把该目录当作 CUDA_HOME 使用。

阶段: 1) pip install  2) 定位 CUDA_HOME  3) load_inline 冒烟  4) import gsplat + fwd/bwd
结果: logs/pipeline/gsplat_attempt.json / .log
"""
import json, os, shutil, subprocess, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(HERE, ".venv", "Scripts", "python.exe")
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable
LOGDIR = os.path.normpath(os.path.join(HERE, "..", "logs", "pipeline"))
os.makedirs(LOGDIR, exist_ok=True)
LOG = os.path.join(LOGDIR, "gsplat_attempt.log")
RESULT = os.path.join(LOGDIR, "gsplat_attempt.json")

_started = time.time()
def log(msg):
    line = "[%7.1fs] %s" % (time.time() - _started, msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run(cmd, env=None, timeout=None):
    log("RUN: " + " ".join(str(c) for c in cmd))
    try:
        p = subprocess.run(cmd, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", errors="replace")
        out = (p.stdout or "")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(out[-30000:] + "\n")
        tail = [l for l in out.strip().splitlines() if l.strip()][-4:]
        log("exit=%s tail=%s" % (p.returncode, tail))
        return p.returncode, out
    except subprocess.TimeoutExpired:
        log("TIMEOUT %ss" % timeout)
        return 124, "timeout"

result = {"ok": False, "stage": "start", "note": "", "gsplat_version": None,
          "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
try:
    # ---------- 1) pip install ----------
    result["stage"] = "pip-install"
    log("== stage 1: pip install gsplat + pip CUDA toolchain ==")
    rc, out = run([PY, "-m", "pip", "install", "gsplat==1.5.3",
                   "nvidia-cuda-nvcc", "nvidia-cuda-runtime", "nvidia-cuda-cccl"], timeout=1800)
    if rc != 0:
        raise RuntimeError("pip install failed (rc=%d)" % rc)

    # ---------- 2) 定位 CUDA_HOME（pip 包 nvidia/cu13） ----------
    result["stage"] = "locate-cuda-home"
    log("== stage 2: locate CUDA_HOME ==")
    import numpy, site
    sp_candidates = set()
    for mod in (numpy,):
        sp_candidates.add(os.path.dirname(os.path.dirname(os.path.abspath(mod.__file__))))
    for s in site.getsitepackages():
        sp_candidates.add(s)
    nvcc = None
    for sp in sp_candidates:
        for root, dirs, files in os.walk(sp):
            if "nvcc.exe" in files:
                nvcc = os.path.join(root, "nvcc.exe")
                break
        if nvcc:
            break
    if not nvcc:
        raise RuntimeError("nvcc.exe not found in site-packages")
    CUDA_HOME = os.path.dirname(os.path.dirname(nvcc))   # .../nvidia/cu13
    log("nvcc: " + nvcc)
    log("CUDA_HOME: " + CUDA_HOME)
    result["cuda_home"] = CUDA_HOME
    for rel in ["bin", "include", "lib/x64"]:
        log("  %s exists=%s" % (rel, os.path.exists(os.path.join(CUDA_HOME, rel))))
    rc, out = run([nvcc, "--version"], timeout=120)
    result["nvcc_version"] = [l for l in out.splitlines() if "release" in l or "Cuda compilation" in l][:2]

    env = dict(os.environ)
    env["CUDA_HOME"] = CUDA_HOME
    env["CUDA_PATH"] = CUDA_HOME
    nvvm_bin = os.path.join(CUDA_HOME, "nvvm", "bin")
    env["PATH"] = os.pathsep.join([os.path.join(CUDA_HOME, "bin"), nvvm_bin, env.get("PATH", "")])
    env["TORCH_CUDA_ARCH_LIST"] = "12.0"
    env["DISTUTILS_USE_SDK"] = "1"
    env["MAX_JOBS"] = "16"

    # ---------- 3) load_inline 冒烟测试 ----------
    result["stage"] = "cpp-extension-smoke"
    log("== stage 3: torch cpp_extension load_inline smoke test ==")
    smoke = os.path.join(HERE, "_gsplat_smoke.py")
    with open(smoke, "w", encoding="utf-8") as f:
        f.write('''
import os, torch
from torch.utils.cpp_extension import load_inline
src = "torch::Tensor f(torch::Tensor x){ return x + 1; }"
mod = load_inline(name="smoke_cuda13", cpp_sources="torch::Tensor f(torch::Tensor x);",
                  cuda_sources=src, functions=["f"], verbose=True)
x = torch.zeros(4, device="cuda")
print("SMOKE_OK", mod.f(x).tolist())
''')
    rc, out = run([PY, smoke], env=env, timeout=900)
    if rc != 0:
        raise RuntimeError("cpp_extension smoke failed (rc=%d)" % rc)

    # ---------- 4) import gsplat（触发完整 JIT） ----------
    result["stage"] = "gsplat-import"
    log("== stage 4: import gsplat (full JIT compile, may take 10-25 min) ==")
    test = os.path.join(HERE, "_gsplat_test.py")
    with open(test, "w", encoding="utf-8") as f:
        f.write('''
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
''')
    rc, out = run([PY, test], env=env, timeout=3000)
    if rc != 0:
        raise RuntimeError("gsplat import/compile failed (rc=%d)" % rc)
    result.update(ok=True, stage="done", note="gsplat JIT compile + fwd/bwd OK")
    log("== GSPLAT OK ==")
except Exception as e:
    result["note"] = result.get("note") or ("%s: %s" % (type(e).__name__, e))
    log("FAILED at stage=%s: %s" % (result.get("stage"), result["note"]))
    log(traceback.format_exc())
finally:
    result["elapsed_sec"] = round(time.time() - _started, 1)
    result["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log("RESULT: " + json.dumps(result, ensure_ascii=False))
