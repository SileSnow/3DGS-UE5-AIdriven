"""puretorch_splatting -- 纯 PyTorch 可微 3DGS 光栅化器（8GB 显存可跑的兜底实现）。

设计: tile-based（16x16 tile），对每个 tile 取候选高斯（按其 3 sigma 包围盒覆盖），
按视深排序后逐候选项做 front-to-back alpha 合成（与 3DGS CUDA 光栅化器同构，仅把
per-tile 排序在 PyTorch 张量上实现）。全部由 autograd 求导，无需编译 CUDA 扩展。

模块:
  sh.py         -- 球谐（SH）颜色求值（degree 0-2）
  rasterizer.py -- 光栅化核心 rasterize()
  renderer.py   -- 3D 高斯参数 -> 2D 投影/协方差 -> 图像；gsplat 后端适配器
"""
from .rasterizer import rasterize  # noqa: F401
from .renderer import GaussianModel, render_from_view, project_gaussians  # noqa: F401
