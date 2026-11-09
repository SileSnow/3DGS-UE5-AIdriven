"""sh.py -- 球谐（SH）颜色求值，与 3DGS 官方实现一致（degree 0-2 可扩展）。"""
from __future__ import annotations

import torch

SH_C0 = 0.28209479177387814
SH_C1 = 0.4886025119029199
SH_C2 = [1.0925484305920792, -1.0925484305920792, 0.31539156525252005,
         -1.0925484305920792, 0.5462742152960396]
SH_C3 = [-0.5900435899266435, 2.890611442640554, -0.4570457994644658, 0.3731763325901154,
         -0.4570457994644658, 1.445305721320277, -0.5900435899266435]


def num_sh_coeffs(deg):
    return (deg + 1) ** 2


def eval_sh(deg, sh, dirs):
    """sh: (N, (deg+1)^2, 3) 原始 SH 系数；dirs: (N,3) 单位视线方向（世界->相机? 3DGS 用相机坐标方向）。

    返回 rgb: (N,3)，为 SH 求值结果（未加 0.5 偏移；调用方按 3DGS 约定 +0.5）。
    """
    N = sh.shape[0]
    result = SH_C0 * sh[:, 0]                      # (N,3)
    if deg >= 1:
        x, y, z = dirs[:, 0:1], dirs[:, 1:2], dirs[:, 2:3]
        result = result - SH_C1 * y * sh[:, 1] + SH_C1 * z * sh[:, 2] - SH_C1 * x * sh[:, 3]
    if deg >= 2:
        xx, yy, zz = x * x, y * y, z * z
        xy, yz, xz = x * y, y * z, x * z
        result = (result
                  + SH_C2[0] * xy * sh[:, 4]
                  + SH_C2[1] * yz * sh[:, 5]
                  + SH_C2[2] * (2.0 * zz - xx - yy) * sh[:, 6]
                  + SH_C2[3] * xz * sh[:, 7]
                  + SH_C2[4] * (xx - yy) * sh[:, 8])
    if deg >= 3:
        result = (result
                  + SH_C3[0] * y * (3.0 * xx - yy) * sh[:, 9]
                  + SH_C3[1] * xy * z * sh[:, 10]
                  + SH_C3[2] * y * (4.0 * zz - xx - yy) * sh[:, 11]
                  + SH_C3[3] * z * (2.0 * zz - 3.0 * xx - 3.0 * yy) * sh[:, 12]
                  + SH_C3[4] * x * (4.0 * zz - xx - yy) * sh[:, 13]
                  + SH_C3[5] * z * (xx - yy) * sh[:, 14]
                  + SH_C3[6] * x * (xx - 3.0 * yy) * sh[:, 15])
    return result
