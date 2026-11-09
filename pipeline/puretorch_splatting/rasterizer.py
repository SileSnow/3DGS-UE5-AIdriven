"""rasterizer.py -- tile-based 纯 PyTorch 可微 3DGS 光栅化器。

算法（与 3DGS CUDA 光栅化器同构）:
  1) 每个高斯的 2D 协方差 -> conic；3 sigma 半径（clamp 到 max_radius）-> 覆盖的 tile 集合
  2) 展开 (tile, gaussian) 对，按 (tile_id, view_depth) 排序（两次稳定排序）
  3) 每个 tile 取前 K 个候选，逐候选做 front-to-back alpha 合成（(T, tile_pixels) 张量）
  4) 结果散射回图像

完全由 autograd 求导；不需要 CUDA 扩展。8GB 显存下 480x360 / 64 tile 候选 / 15 万高斯可跑。
"""
from __future__ import annotations

import math

import torch

_PIXEL_CACHE = {}


def _tile_pixels(TW, TH, tile, H, W, device, dtype):
    """返回每 tile 的像素坐标 (T, tile*tile) 与有效掩码 (T, tile*tile)。行主序 (oy, ox)。"""
    key = (TW, TH, tile, H, W, str(device), dtype)
    cached = _PIXEL_CACHE.get(key)
    if cached is not None:
        return cached
    ty = torch.arange(TH, device=device, dtype=torch.long).repeat_interleave(TW)
    tx = torch.arange(TW, device=device, dtype=torch.long).repeat(TH)
    oy = torch.arange(tile, device=device, dtype=torch.long)
    ox = torch.arange(tile, device=device, dtype=torch.long)
    px = (tx[:, None, None] * tile + ox[None, None, :]).expand(-1, tile, -1).reshape(-1, tile * tile)
    py = (ty[:, None, None] * tile + oy[None, :, None]).expand(-1, tile, tile).reshape(-1, tile * tile)
    valid = (px < W) & (py < H)
    out = (px.to(dtype), py.to(dtype), valid, TW, TH)
    _PIXEL_CACHE[key] = out
    return out


def _pair_tiles(mean2d, radius, depth, valid, H, W, tile):
    """构造排序后的 (tile, gaussian) 候选列表。返回 (global_idx, starts, ends) 或 None。"""
    TW = (W + tile - 1) // tile
    TH = (H + tile - 1) // tile
    T = TW * TH
    device = mean2d.device
    x, y = mean2d[:, 0], mean2d[:, 1]
    r = radius.clamp(max=1e6)

    tx0 = ((x - r) / tile).floor().clamp(min=0, max=TW - 1).long()
    tx1 = ((x + r) / tile).floor().clamp(min=0, max=TW - 1).long()
    ty0 = ((y - r) / tile).floor().clamp(min=0, max=TH - 1).long()
    ty1 = ((y + r) / tile).floor().clamp(min=0, max=TH - 1).long()
    covers = (x + r >= 0) & (x - r <= W - 1) & (y + r >= 0) & (y - r <= H - 1)
    mask = valid & covers
    idx = mask.nonzero(as_tuple=False).squeeze(1)
    if idx.numel() == 0:
        return None

    w = (tx1[idx] - tx0[idx] + 1)
    h = (ty1[idx] - ty0[idx] + 1)
    cnt = w * h
    total = int(cnt.sum().item())
    if total == 0:
        return None

    splat_pos = torch.repeat_interleave(torch.arange(idx.numel(), device=device), cnt)
    seg = torch.repeat_interleave(torch.cumsum(cnt, 0) - cnt, cnt)
    local = torch.arange(total, device=device, dtype=torch.long) - seg
    ww = w[splat_pos]
    dx = local % ww
    dy = local // ww
    tx = tx0[idx][splat_pos] + dx
    ty = ty0[idx][splat_pos] + dy
    tile_id = ty * TW + tx
    depth_pair = depth[idx][splat_pos]

    # 先按 depth 升序，再按 tile_id 稳定排序 => 每个 tile 内部 depth 升序
    o1 = torch.argsort(depth_pair)
    tile1 = tile_id[o1]
    sp1 = splat_pos[o1]
    o2 = torch.argsort(tile1, stable=True)
    tile_sorted = tile1[o2]
    sp_sorted = sp1[o2]
    gidx = idx[sp_sorted]

    ar = torch.arange(T, device=device, dtype=torch.long)
    starts = torch.searchsorted(tile_sorted, ar)
    ends = torch.searchsorted(tile_sorted, ar + 1)
    return gidx, starts, ends, T


def rasterize(mean2d, conic, colors, opacity, depth, image_size, tile_size=16,
              max_per_tile=64, max_radius=16.0):
    """可微 3DGS 光栅化。

    参数:
      mean2d  : (N,2) 像素坐标
      conic   : (N,3) 2D 协方差逆矩阵 (a,b,c)，即 [[a,b],[b,c]]
      colors  : (N,C) 高斯颜色（已做 SH 求值 + 0.5 偏移，clamp>=0）
      opacity : (N,)  不透明度 (0..1)
      depth   : (N,)  相机 z（正前）
      image_size: (H, W)
      tile_size: tile 边长（16）
      max_per_tile: 每个 tile 最多参与合成的高斯数
      max_radius : 3 sigma 半径上限（像素）；超出部分贡献 < 1%，可裁剪
    返回:
      image (H,W,C), alpha (H,W,1)
    """
    H, W = int(image_size[0]), int(image_size[1])
    device = mean2d.device
    dtype = mean2d.dtype
    C = colors.shape[1]
    tile = int(tile_size)

    a, b, c = conic[:, 0], conic[:, 1], conic[:, 2]
    det = a * c - b * b
    inv_det = 1.0 / det.clamp(min=1e-12)
    cov_a = c * inv_det
    cov_c = a * inv_det
    cov_b = -b * inv_det
    half = 0.5 * (cov_a + cov_c)
    disc = torch.sqrt(((0.5 * (cov_a - cov_c)) ** 2 + cov_b ** 2).clamp(min=0.0))
    eigmax = half + disc
    radius = 3.0 * torch.sqrt(eigmax.clamp(min=0.0))
    radius = radius.clamp(max=max_radius)

    valid = (torch.isfinite(mean2d).all(dim=-1)
             & torch.isfinite(conic).all(dim=-1)
             & torch.isfinite(opacity)
             & (depth > 0.05) & (opacity > 0.5 / 255.0) & (det > 1e-12))

    pairs = _pair_tiles(mean2d, radius, depth, valid, H, W, tile)
    TW = (W + tile - 1) // tile
    TH = (H + tile - 1) // tile
    T = TW * TH
    TT = tile * tile
    if pairs is None:
        return (torch.zeros(H, W, C, device=device, dtype=dtype),
                torch.zeros(H, W, 1, device=device, dtype=dtype))

    gidx, starts, ends, _ = pairs
    px, py, valid_pix, _, _ = _tile_pixels(TW, TH, tile, H, W, device, dtype)

    m_sorted = mean2d[gidx]        # (P,2)
    conic_sorted = conic[gidx]     # (P,3)
    col_sorted = colors[gidx]      # (P,C)
    op_sorted = opacity[gidx]      # (P,)
    P = m_sorted.shape[0]

    k_max = int((ends - starts).max().item()) if T > 0 else 0
    K = min(int(max_per_tile), k_max)

    Tbuf = torch.ones(T, TT, device=device, dtype=dtype)
    Cbuf = torch.zeros(T, TT, C, device=device, dtype=dtype)
    opdt = op_sorted.dtype

    for k in range(K):
        idx = starts + k
        ok = idx < ends
        idxc = idx.clamp(max=P - 1)
        m = m_sorted[idxc]                     # (T,2)
        cc = conic_sorted[idxc]                # (T,3)
        col = col_sorted[idxc]                 # (T,C)
        op = op_sorted[idxc] * ok.to(opdt)     # (T,)
        dx = px - m[:, 0:1]
        dy = py - m[:, 1:2]
        power = -0.5 * (cc[:, 0:1] * dx * dx + 2.0 * cc[:, 1:2] * dx * dy + cc[:, 2:3] * dy * dy)
        # clamp(max=0) 代替 where：数值上等价（power>0 的像素 alpha 应为 0），但避免 exp 溢出与
        # exp/where 反向的 0*inf=NaN（实测 30k 高斯训练第 8 步会出现 NaN）
        power = power.clamp(max=0.0)
        alpha = op[:, None] * torch.exp(power)
        alpha = alpha.clamp(max=0.99) * valid_pix
        Tcur = Tbuf
        Cbuf = Cbuf + (Tcur * alpha).unsqueeze(-1) * col.unsqueeze(1)
        Tbuf = Tcur * (1.0 - alpha)

    Cimg = Cbuf.reshape(TH, TW, tile, tile, C).permute(0, 2, 1, 3, 4).reshape(TH * tile, TW * tile, C)
    Aimg = (1.0 - Tbuf).reshape(TH, TW, tile, tile).permute(0, 2, 1, 3).reshape(TH * tile, TW * tile, 1)
    return Cimg[:H, :W], Aimg[:H, :W]
