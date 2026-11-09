"""ply_io.py -- 标准 3DGS PLY 读写（字段契约见 shared/CONVENTIONS.md §2）。

顶点字段（binary_little_endian 1.0）:
  x y z nx ny nz f_dc_0 f_dc_1 f_dc_2 f_rest_0..44 opacity scale_0..2 rot_0..3
  - x,y,z 世界坐标（与训练数据集同一坐标系/尺度；UE 数据集为 UE LHS cm）
  - nx,ny,nz 法向（3DGS 标准不用，写 0）
  - f_dc_* 原始 SH DC 系数（未激活；查看端按 3DGS 公式 rgb = 0.5 + C0*f_dc + ... 解码）
  - f_rest_* SH 1-3 阶（45 项）；若训练 sh_degree < 3，用 0 填充（3DGS 标准公式下等价于无高阶项）
  - opacity sigmoid 前 logit
  - scale_* 对数尺度
  - rot_0..3 四元数 (w,x,y,z)，未归一化
"""
from __future__ import annotations

import numpy as np

SH_C0 = 0.28209479177387814


def save_3dgs_ply(path, means, quats, scales_log, opacity_logit, sh, sh_degree,
                  normals=None, extra_props=None):
    """保存标准 3DGS PLY。

    means: (N,3) 世界坐标; quats (N,4) w,x,y,z; scales_log (N,3); opacity_logit (N,)
    sh: (N,num_coeffs,3) 原始 SH；sh_degree 决定 f_rest 有效项数（其余填 0）
    """
    from plyfile import PlyData, PlyElement
    means = np.asarray(means, np.float32)
    quats = np.asarray(quats, np.float32)
    scales_log = np.asarray(scales_log, np.float32)
    opacity_logit = np.asarray(opacity_logit, np.float32).reshape(-1)
    sh = np.asarray(sh, np.float32)
    N = means.shape[0]
    if normals is None:
        normals = np.zeros((N, 3), np.float32)
    f_dc = sh[:, 0, :]                       # (N,3)
    f_rest = np.zeros((N, 45), np.float32)
    n_rest = sh.shape[1] - 1
    if n_rest > 0:
        # 官方 3DGS 布局: features_rest (N,n_rest,3) -> transpose(1,2) -> (N,3,n_rest) -> flatten
        f_rest[:, :n_rest * 3] = sh[:, 1:, :].transpose(0, 2, 1).reshape(N, -1)[:, :45]
    min_rest = 0
    if sh_degree < 3:
        min_rest = 0  # 仍写满 45 项（0 填充），保证 UE/标准 viewer 兼容

    names = (["x", "y", "z", "nx", "ny", "nz"] + ["f_dc_0", "f_dc_1", "f_dc_2"]
             + ["f_rest_%d" % i for i in range(45)]
             + ["opacity"] + ["scale_%d" % i for i in range(3)]
             + ["rot_%d" % i for i in range(4)])
    dtype = [(n, "f4") for n in names]
    if extra_props:
        for n in extra_props:
            names.append(n)
            dtype.append((n, "f4"))
    data = np.empty(N, dtype=dtype)
    data["x"], data["y"], data["z"] = means[:, 0], means[:, 1], means[:, 2]
    data["nx"], data["ny"], data["nz"] = normals[:, 0], normals[:, 1], normals[:, 2]
    for i in range(3):
        data["f_dc_%d" % i] = f_dc[:, i]
    for i in range(45):
        data["f_rest_%d" % i] = f_rest[:, i]
    data["opacity"] = opacity_logit
    for i in range(3):
        data["scale_%d" % i] = scales_log[:, i]
    for i in range(4):
        data["rot_%d" % i] = quats[:, i]
    if extra_props:
        for n, arr in extra_props.items():
            data[n] = np.asarray(arr, np.float32).reshape(-1)
    el = PlyElement.describe(data, "vertex")
    PlyData([el], byte_order="<").write(path)
    verify_ply_roundtrip(path, data, names)
    return path


def verify_ply_roundtrip(path, data, expected_names, n_check=8):
    """读回断言：字段名/顺序/长度一致，且抽样数值与写入一致（防止 header 与数据字节错位）。"""
    from plyfile import PlyData
    ply = PlyData.read(path)
    v = ply["vertex"]
    got_names = list(v.data.dtype.names)
    assert got_names == list(expected_names), (
        "PLY 字段顺序不一致：\n写入: %s\n读回: %s" % (expected_names, got_names))
    assert v.count == len(data), "PLY 顶点数不一致: %d != %d" % (v.count, len(data))
    rng = np.random.default_rng(0)
    idx = rng.choice(len(data), size=min(n_check, len(data)), replace=False)
    for name in ["x", "y", "z", "f_dc_0", "opacity", "scale_0", "rot_0"]:
        if name in expected_names:
            a = np.asarray(v.data[name][idx], np.float64)
            b = np.asarray(data[name][idx], np.float64)
            assert np.allclose(a, b, atol=1e-6), "PLY 数值不一致: %s" % name
    return {"path": path, "num_vertices": int(v.count), "props": len(got_names),
            "byte_order": str(ply.byte_order), "first_props": got_names[:10]}


def load_3dgs_ply(path):
    """读回标准 3DGS PLY，返回 dict(means, quats, scales_log, opacity_logit, sh, sh_degree)。"""
    from plyfile import PlyData
    ply = PlyData.read(path)
    v = ply["vertex"].data
    means = np.stack([v["x"], v["y"], v["z"]], axis=1).astype(np.float32)
    quats = np.stack([v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], axis=1).astype(np.float32)
    scales_log = np.stack([v["scale_0"], v["scale_1"], v["scale_2"]], axis=1).astype(np.float32)
    opacity = np.asarray(v["opacity"], np.float32)
    f_dc = np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], axis=1).astype(np.float32)
    f_rest_names = [n for n in v.dtype.names if n.startswith("f_rest_")]
    f_rest_names.sort(key=lambda s: int(s.split("_")[-1]))
    if f_rest_names:
        f_rest = np.stack([v[n] for n in f_rest_names], axis=1).astype(np.float32)
        f_rest = f_rest.reshape(-1, 3, 15).transpose(0, 2, 1)  # (N,15,3)
        sh = np.concatenate([f_dc[:, None, :], f_rest], axis=1)  # (N,16,3)
        # 判断真实 degree：若高阶全 0 则 degree 0
        deg = 3
        if f_rest_names and np.allclose(f_rest[:, 0:3, :], 0.0):
            deg = 1
            if np.allclose(f_rest, 0.0):
                deg = 0
    else:
        sh = f_dc[:, None, :]
        deg = 0
    return {"means": means, "quats": quats, "scales_log": scales_log,
            "opacity_logit": opacity, "sh": sh, "sh_degree": deg}


def ply_stats(path):
    d = load_3dgs_ply(path)
    import os
    return {"path": path, "num_gaussians": int(d["means"].shape[0]),
            "sh_degree": d["sh_degree"], "size_bytes": os.path.getsize(path),
            "size_mb": round(os.path.getsize(path) / 1e6, 3),
            "x_range": [float(d["means"][:, 0].min()), float(d["means"][:, 0].max())],
            "y_range": [float(d["means"][:, 1].min()), float(d["means"][:, 1].max())],
            "z_range": [float(d["means"][:, 2].min()), float(d["means"][:, 2].max())]}
