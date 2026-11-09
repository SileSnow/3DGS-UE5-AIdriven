"""utils.py -- 指标（PSNR/SSIM）、图像读写、日志小工具。"""
from __future__ import annotations

import os

import numpy as np
import torch
import torch.nn.functional as F


def psnr(pred, target, eps=1e-8):
    """pred/target: (H,W,3) 或 (B,H,W,3)，取值 [0,1]。"""
    mse = torch.mean((pred.detach() - target.detach()) ** 2)
    return float((-10.0 * torch.log10(mse + eps)).item())


def _gaussian_window(window_size=11, sigma=1.5, device="cpu", dtype=torch.float32):
    xs = torch.arange(window_size, device=device, dtype=dtype) - window_size // 2
    g = torch.exp(-(xs ** 2) / (2 * sigma ** 2))
    w = g[:, None] @ g[None, :]
    return w / w.sum()


def ssim(pred, target, window_size=11, device="cpu"):
    """单张图 (H,W,3) 的 SSIM（与 3DGS 评测一致：11x11 高斯窗，各通道平均）。"""
    if pred.dim() == 3:
        pred = pred.permute(2, 0, 1).unsqueeze(0)
        target = target.permute(2, 0, 1).unsqueeze(0)
    win = _gaussian_window(window_size, device=device, dtype=pred.dtype)
    win = win.expand(pred.shape[1], 1, window_size, window_size)
    mu1 = F.conv2d(pred, win, padding=window_size // 2, groups=pred.shape[1])
    mu2 = F.conv2d(target, win, padding=window_size // 2, groups=target.shape[1])
    sigma1 = F.conv2d(pred * pred, win, padding=window_size // 2, groups=pred.shape[1]) - mu1 * mu1
    sigma2 = F.conv2d(target * target, win, padding=window_size // 2, groups=target.shape[1]) - mu2 * mu2
    sigma12 = F.conv2d(pred * target, win, padding=window_size // 2, groups=pred.shape[1]) - mu1 * mu2
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ssim_map = ((2 * mu1 * mu2 + c1) * (2 * sigma12 + c2)) / \
               ((mu1 * mu1 + mu2 * mu2 + c1) * (sigma1 + sigma2 + c2))
    return float(ssim_map.mean().detach().item())


def to_numpy_img(t):
    """torch (H,W,3) [0,1] -> uint8 numpy"""
    return (t.detach().clamp(0, 1).cpu().numpy() * 255.0 + 0.5).astype(np.uint8)


def save_png(img_uint8, path):
    import cv2
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cv2.imwrite(path, cv2.cvtColor(img_uint8, cv2.COLOR_RGB2BGR))


def psnr_ssim(pred, target):
    return psnr(pred, target), ssim(pred, target)
