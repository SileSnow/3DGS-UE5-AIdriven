"""try_gsplat3.py -- 第三次 gsplat 可行性尝试：解析 vcvars64 环境后在本进程内配置
CUDA_HOME(pip nvidia/cu13) + NVCC_PREPEND_FLAGS=-allow-unsupported-compiler，再依次
跑 (1) torch cpp_extension 冒烟 (2) import gsplat + fwd/bwd。结果写 logs/pipeline/gsplat_attempt3.log。
"""
import json, os, re, subprocess, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, ".venv", "Scripts", "python.exe")
LOGDIR = os.path.abspath(os.path.join(HERE, "..", "logs", "pipeline"))
os.makedirs(LOGDIR, exist_ok=True)
LOG = os.path.join(LOGDIR, "gsplat_attempt3.log")
RESULT = os.path.join(LOGDIR, "gsplat_attempt3.json")
VCVARS = r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"
T0 = time.time()

def log(msg):
    line = "[%7.1fs] %s" % (time.time() - T0, msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run(cmd, env=None, timeout=None):
    log("RUN: " + (" ".join(cmd) if isinstance(cmd, list) else cmd))
    p = subprocess.run(cmd, env=env, timeout=timeout, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                       errors="replace", shell=isinstance(cmd, str))
    out = p.stdout or ""
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(out[-40000:] + "\n")
    tail = [l for l in out.strip().splitlines() if l.strip()][-6:]
    log("exit=%s tail=%s" % (p.returncode, tail))
    return p.returncode, out

result = {"ok": False, "stage": "start", "note": ""}
try:
    # ---- 1) 解析 vcvars64 环境 ----
    if os.path.isfile(LOG):
        os.remove(LOG)
    log("== stage 1: parse vcvars64 env ==")
    rc, out = run('cmd /c "call ""%s"" >nul 2>&1 && set"' % VCVARS, timeout=120)
    if rc != 0:
        raise RuntimeError("vcvars64 failed rc=%d" % rc)
    env = {}
    for line in out.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m:
            env[m.group(1)] = m.group(2)
    log("vcvars env vars: %d, cl in PATH: %s" % (len(env), "cl.exe" in out.lower()))
    path_dirs = [d for d in env.get("PATH", "").split(os.pathsep) if d]
    log("cl path sample: %s" % [d for d in path_dirs if "MSVC" in d][:2])

    # ---- 2) 定位 pip CUDA 13 工具链 ----
    log("== stage 2: locate CUDA_HOME ==")
    import numpy, site
    sps = {os.path.dirname(os.path.dirname(os.path.abspath(numpy.__file__)))}
    sps.update(site.getsitepackages())
    nvcc = None
    for sp in sps:
        for root, dirs, files in os.walk(sp):
            if "nvcc.exe" in files:
                nvcc = os.path.join(root, "nvcc.exe"); break
        if nvcc: break
    if not nvcc:
        raise RuntimeError("nvcc.exe not found in site-packages")
    CUDA_HOME = os.path.dirname(os.path.dirname(nvcc))
    log("CUDA_HOME = " + CUDA_HOME)
    result["cuda_home"] = CUDA_HOME
    env["CUDA_HOME"] = CUDA_HOME
    env["CUDA_PATH"] = CUDA_HOME
    nvvm_bin = os.path.join(CUDA_HOME, "nvvm", "bin")
    env["PATH"] = os.pathsep.join([os.path.join(CUDA_HOME, "bin"), nvvm_bin, env.get("PATH", "")])
    env["NVCC_PREPEND_FLAGS"] = "-allow-unsupported-compiler"
    env["TORCH_CUDA_ARCH_LIST"] = "12.0"
    env["DISTUTILS_USE_SDK"] = "1"
    env["MAX_JOBS"] = "16"
    env["CC"] = "cl"
    env["CXX"] = "cl"
    result["nvcc_version"] = [l for l in run([nvcc, "--version"], env=env, timeout=120)[1].splitlines()
                              if "release" in l][:1]

    # ---- 3) 冒烟 ----
    result["stage"] = "smoke"
    log("== stage 3: cpp_extension smoke ==")
    smoke = os.path.join(HERE, "_smoke3.py")
    with open(smoke, "w", encoding="utf-8") as f:
        f.write('''import torch
from torch.utils.cpp_extension import load_inline
src = "torch::Tensor f(torch::Tensor x){ return x + 1; }"
mod = load_inline(name="smoke_cuda13c", cpp_sources="torch::Tensor f(torch::Tensor x);",
                  cuda_sources=src, functions=["f"], verbose=False,
                  extra_cuda_cflags=["-allow-unsupported-compiler"])
x = torch.zeros(4, device="cuda")
print("SMOKE_OK", mod.f(x).tolist())
''')
    rc, out = run([PY, smoke], env=env, timeout=900)
    if rc != 0:
        raise RuntimeError("smoke failed rc=%d" % rc)

    # ---- 4) import gsplat ----
    result["stage"] = "gsplat"
    log("== stage 4: import gsplat (JIT, may take 10-25min) ==")
    test = os.path.join(HERE, "_gsplat_test3.py")
    with open(test, "w", encoding="utf-8") as f:
        f.write('''import torch, gsplat, time
print("gsplat", gsplat.__version__)
from gsplat import rasterization
N, D = 512, 6
torch.manual_seed(0)
means = torch.randn(N, 3, device="cuda", requires_grad=True)
quats = torch.nn.functional.normalize(torch.randn(N, 4, device="cuda"), dim=-1).requires_grad_(True)
scales = (torch.rand(N, 3, device="cuda", requires_grad=True) * 0.1)
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
    rc, out = run([PY, test], env=env, timeout=3600)
    if rc != 0:
        raise RuntimeError("gsplat failed rc=%d" % rc)
    result.update(ok=True, stage="done", note="gsplat JIT OK")
    log("== GSPLAT OK ==")
except subprocess.TimeoutExpired as e:
    result["note"] = "timeout: %s" % e
    log("TIMEOUT: %s" % e)
except Exception as e:
    result["note"] = result.get("note") or ("%s: %s" % (type(e).__name__, e))
    log("FAILED at %s: %s" % (result.get("stage"), result["note"]))
    log(traceback.format_exc())
finally:
    result["elapsed_sec"] = round(time.time() - T0, 1)
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log("RESULT: " + json.dumps(result, ensure_ascii=False))
