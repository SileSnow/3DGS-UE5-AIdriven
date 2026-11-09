"""renderer.py -- 3D 高斯参数（均值/四元数/尺度/不透明度/SH）-> 2D 投影 -> 图像。

支持两种后端:
  puretorch -- 本仓库 puretorch_splatting.rasterize（默认，无需编译）
  gsplat    -- 若 gsplat 的 JIT 扩展可用则调用其 CUDA 光栅化器（见 try_gsplat3.py 探测结果）
两者输入输出语义一致，训练脚本可用 --backend 切换。
"""
from __future__ import annotations

import torch

from .rasterizer import rasterize
from .sh import eval_sh, num_sh_coeffs

try:  # 可选后端：import 成功不代表 CUDA 扩展可用（gsplat 无 CUDA toolkit 时 _C=None）
    import gsplat as _gsplat  # noqa: F401
    from gsplat.cuda._backend import _C as _gsplat_C
    _HAS_GSPLAT = _gsplat_C is not None
except Exception:  # noqa: BLE001
    _HAS_GSPLAT = False


def has_gsplat():
    return _HAS_GSPLAT


def quat_to_rotmat(q):
    """(N,4) w,x,y,z（需已归一化）-> (N,3,3)"""
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    two = 2.0
    ww, xx, yy, zz = w * w, x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    R = torch.stack([
        torch.stack([ww + xx - yy - zz, two * (xy - wz), two * (xz + wy)], dim=-1),
        torch.stack([two * (xy + wz), ww - xx + yy - zz, two * (yz - wx)], dim=-1),
        torch.stack([two * (xz - wy), two * (yz + wx), ww - xx - yy + zz], dim=-1),
    ], dim=-2)
    return R


def compute_cov3d(quats, scales):
    """(N,4) 四元数 + (N,3) log 尺度 -> (N,3,3) 世界协方差。"""
    R = quat_to_rotmat(quats)
    S = torch.exp(scales).unsqueeze(1)          # (N,1,3)
    M = R * S                                   # 列向量乘尺度
    return M @ M.transpose(1, 2)


def project_gaussians(means3d, quats, scales, viewmat, K, near=0.05):
    """世界高斯 -> (mean2d, conic, depth)。viewmat: 4x4 world->camera（OpenCV）。"""
    N = means3d.shape[0]
    R = viewmat[:3, :3]
    t = viewmat[:3, 3]
    p_cam = means3d @ R.t() + t                  # (N,3)
    depth = p_cam[:, 2]
    z = depth.clamp(min=near)
    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]
    x, y = p_cam[:, 0], p_cam[:, 1]
    mean2d = torch.stack([fx * x / z + cx, fy * y / z + cy], dim=-1)

    J = torch.zeros(N, 2, 3, device=means3d.device, dtype=means3d.dtype)
    J[:, 0, 0] = fx / z
    J[:, 0, 2] = -fx * x / (z * z)
    J[:, 1, 1] = fy / z
    J[:, 1, 2] = -fy * y / (z * z)
    cov3d = compute_cov3d(quats, scales)
    JR = J @ R.unsqueeze(0)                      # (N,2,3)
    cov2d = JR @ cov3d @ JR.transpose(1, 2)      # (N,2,2)
    cov2d = cov2d + 0.3 * torch.eye(2, device=means3d.device, dtype=means3d.dtype)
    a, b, c = cov2d[:, 0, 0], cov2d[:, 0, 1], cov2d[:, 1, 1]
    det = a * c - b * b
    inv = 1.0 / det.clamp(min=1e-8)
    conic = torch.stack([c * inv, -b * inv, a * inv], dim=-1)
    # 病态协方差（极扁高斯/近奇异）会让 conic ~1e8、反向梯度爆炸 -> 限幅（视觉上等价于极小 alpha）
    conic = conic.clamp(min=-1e6, max=1e6)
    return mean2d, conic, depth


class GaussianModel:
    """3D 高斯参数容器。opacity 为 logit，scales 为 log 尺度，SH 为原始系数。"""

    def __init__(self, means, quats, scales, opacity, sh, sh_degree=0):
        self.means = means
        self.quats = quats
        self.scales = scales
        self.opacity = opacity
        self.sh = sh
        self.sh_degree = sh_degree

    @property
    def num_gaussians(self):
        return self.means.shape[0]

    def color_from_view(self, viewmat, camera_center):
        """计算视角相关颜色 (N,3)（未 clamp）。dirs 在相机坐标系。"""
        dirs = self.means - camera_center.unsqueeze(0)
        dirs = torch.nn.functional.normalize(dirs, dim=-1)
        dirs_cam = dirs @ viewmat[:3, :3].t()
        return eval_sh(self.sh_degree, self.sh, dirs_cam) + 0.5

    def state_dict(self):
        return {"means": self.means, "quats": self.quats, "scales": self.scales,
                "opacity": self.opacity, "sh": self.sh, "sh_degree": self.sh_degree}

    @classmethod
    def from_state_dict(cls, sd):
        return cls(sd["means"], sd["quats"], sd["scales"], sd["opacity"], sd["sh"],
                   sd.get("sh_degree", 0))


def viewmat_from_view(view):
    """dataset view -> 4x4 world->camera（torch）。"""
    M = torch.eye(4, dtype=torch.float64)
    R = torch.as_tensor(view["R_cw"], dtype=torch.float64)
    t = torch.as_tensor(view["t_cw"], dtype=torch.float64)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


def render_from_view(model, view, backend="puretorch", tile_size=16, max_per_tile=64,
                     max_radius=16.0, background=None, device="cuda", dtype=torch.float32,
                     return_extras=False, retain_mean2d_grad=False):
    """渲染一张图。返回 dict(image, alpha, mean2d)（mean2d 保留用于 densify 的梯度）。"""
    H, W = int(view["height"]), int(view["width"])
    means = model.means
    viewmat = viewmat_from_view(view).to(device=device, dtype=dtype)
    K = torch.as_tensor(view["K"], dtype=dtype, device=device)
    center = -viewmat[:3, :3].t() @ viewmat[:3, 3]

    if backend == "gsplat":
        if not _HAS_GSPLAT:
            raise RuntimeError("gsplat 后端不可用")
        from gsplat import rasterization as gs_raster
        viewmats = viewmat.unsqueeze(0)
        Ks = K.unsqueeze(0)
        colors = model.sh                          # (N, num_coeffs, 3) 原始 SH
        img, alpha, meta = gs_raster(
            means, model.quats, model.scales, torch.sigmoid(model.opacity), colors,
            viewmats, Ks, W, H, sh_degree=model.sh_degree)
        img = img[0]
        alpha = alpha[0]
        if background is not None:
            bg = torch.as_tensor(background, dtype=img.dtype, device=img.device)
            img = img + (1.0 - alpha) * bg
        return {"image": img, "alpha": alpha, "mean2d": meta.get("means2d", None)}

    mean2d, conic, depth = project_gaussians(means, model.quats, model.scales, viewmat, K)
    if retain_mean2d_grad and mean2d.requires_grad:
        mean2d.retain_grad()
    rgb = model.color_from_view(viewmat, center)
    rgb = rgb.clamp(min=0.0)
    image, alpha = rasterize(mean2d, conic, rgb, torch.sigmoid(model.opacity), depth,
                             (H, W), tile_size=tile_size, max_per_tile=max_per_tile,
                             max_radius=max_radius)
    if background is not None:
        bg = torch.as_tensor(background, dtype=image.dtype, device=image.device)
        image = image + (1.0 - alpha) * bg
    out = {"image": image, "alpha": alpha, "mean2d": mean2d}
    if return_extras:
        out.update({"conic": conic, "depth": depth, "rgb": rgb})
    return out
