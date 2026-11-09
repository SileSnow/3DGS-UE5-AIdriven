"""test_rasterizer.py -- 纯 PyTorch 光栅化器正确性（对齐暴力参考实现）/ 可微性 / 速度显存测试。"""
import os, sys, time, json
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from puretorch_splatting.rasterizer import rasterize


def brute_force(mean2d, conic, colors, opacity, depth, H, W):
    """逐像素暴力参考: 按深度排序做 front-to-back 合成。"""
    N = mean2d.shape[0]
    img = np.zeros((H, W, colors.shape[1]), np.float64)
    alpha_img = np.zeros((H, W, 1), np.float64)
    m = mean2d.detach().cpu().numpy(); cc = conic.detach().cpu().numpy()
    col = colors.detach().cpu().numpy(); op = opacity.detach().cpu().numpy()
    dep = depth.detach().cpu().numpy()
    order = np.argsort(dep)
    ys, xs = np.mgrid[0:H, 0:W]
    for i in order:
        dx = xs - m[i, 0]; dy = ys - m[i, 1]
        power = -0.5 * (cc[i, 0] * dx * dx + 2 * cc[i, 1] * dx * dy + cc[i, 2] * dy * dy)
        a = np.where(power < 0, op[i] * np.exp(np.minimum(power, 0)), 0.0)
        a = np.clip(a, 0, 0.99)[..., None]
        img = img + (1 - alpha_img) * a * col[i][None, None, :]
        alpha_img = alpha_img + (1 - alpha_img) * a
    return img, alpha_img


def test_correctness(seed=0):
    torch.manual_seed(seed)
    H, W = 48, 64
    N = 3
    mean2d = torch.tensor([[20.0, 15.0], [32.5, 22.0], [40.0, 30.0]])
    # conic: 各向异性高斯
    conic = torch.tensor([[0.08, 0.01, 0.06], [0.03, -0.01, 0.05], [0.12, 0.0, 0.10]])
    colors = torch.tensor([[0.9, 0.2, 0.1], [0.1, 0.8, 0.2], [0.2, 0.3, 0.9]])
    opacity = torch.tensor([0.9, 0.7, 0.5])
    depth = torch.tensor([5.0, 3.0, 4.0])
    img, alpha = rasterize(mean2d, conic, colors, opacity, depth, (H, W), tile_size=16,
                           max_per_tile=16, max_radius=64.0)
    ref_img, ref_alpha = brute_force(mean2d, conic, colors, opacity, depth, H, W)
    diff = np.abs(img.numpy() - ref_img).max()
    diff_a = np.abs(alpha.numpy()[..., 0] - ref_alpha[..., 0]).max()
    print("[correctness] max |img diff| = %.3e, max |alpha diff| = %.3e (容差 1e-3: 3σ tile 包围盒裁剪)"
          % (diff, diff_a))
    return diff < 1e-3 and diff_a < 1e-3


def test_grad():
    torch.manual_seed(1)
    H, W = 32, 40
    N = 5
    target = torch.zeros(H, W, 3)
    target[10:20, 15:25] = torch.tensor([1.0, 0.5, 0.2])
    mean2d = torch.tensor([[15.0, 12.0], [20.0, 15.0], [18.0, 10.0], [22.0, 18.0], [16.0, 16.0]],
                          requires_grad=True)
    conic = torch.tensor([[0.2, 0.0, 0.2]] * N, requires_grad=True)
    colors = torch.rand(N, 3, requires_grad=True)
    opacity = torch.full((N,), 0.5, requires_grad=True)
    depth = torch.linspace(1.0, 2.0, N)
    opt = torch.optim.Adam([mean2d, conic, colors, opacity], lr=0.05)
    losses = []
    for it in range(200):
        opt.zero_grad()
        img, alpha = rasterize(mean2d, conic, colors, torch.sigmoid(opacity), depth,
                               (H, W), tile_size=16, max_per_tile=16, max_radius=40.0)
        loss = ((img - target) ** 2).mean()
        loss.backward()
        opt.step()
        losses.append(float(loss))
    print("[grad] loss %.5f -> %.5f (mean2d.grad norm=%.4f)" % (
        losses[0], losses[-1], float(mean2d.grad.norm())))
    return losses[-1] < losses[0] * 0.2


def test_speed(N=60000, H=360, W=480, K=64, iters=3):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(0)
    mean2d = torch.rand(N, 2, device=device) * torch.tensor([W, H], device=device)
    conic = torch.zeros(N, 3, device=device)
    cov = torch.rand(N, 2, device=device) * 6.0 + 1.0
    conic[:, 0] = 1.0 / cov[:, 0]; conic[:, 2] = 1.0 / cov[:, 1]
    colors = torch.rand(N, 3, device=device)
    opacity = torch.rand(N, device=device) * 0.6 + 0.2
    depth = torch.rand(N, device=device) * 100 + 10
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    # warmup
    with torch.no_grad():
        img, alpha = rasterize(mean2d, conic, colors, opacity, depth, (H, W), tile_size=16,
                               max_per_tile=K, max_radius=16.0)
    t0 = time.time()
    for _ in range(iters):
        img, alpha = rasterize(mean2d, conic, colors, opacity, depth, (H, W), tile_size=16,
                               max_per_tile=K, max_radius=16.0)
    fwd = (time.time() - t0) / iters
    # 训练一步（含反向）
    mean2d.requires_grad_(True); colors2 = colors.clone().requires_grad_(True)
    t0 = time.time()
    for _ in range(iters):
        img, alpha = rasterize(mean2d, conic, colors2, opacity, depth, (H, W), tile_size=16,
                               max_per_tile=K, max_radius=16.0)
        loss = img.mean() + alpha.mean()
        loss.backward()
        mean2d.grad = None; colors2.grad = None
    step = (time.time() - t0) / iters
    peak = torch.cuda.max_memory_allocated() / 1e6 if device == "cuda" else 0
    print("[speed] N=%d %dx%d K=%d: forward %.1f ms, fwd+bwd %.1f ms, peak_mem %.0f MB, tiles=%d" %
          (N, W, H, K, fwd * 1e3, step * 1e3, peak, ((W + 15) // 16) * ((H + 15) // 16)))
    return fwd, step


if __name__ == "__main__":
    ok1 = test_correctness()
    ok2 = test_grad()
    print("correctness:", ok1, "| gradient:", ok2)
    if torch.cuda.is_available():
        test_speed(N=60000, H=360, W=480, K=64)
        test_speed(N=150000, H=360, W=480, K=64)
