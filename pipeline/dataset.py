"""dataset.py -- 统一数据集加载：CONVENTIONS metadata.json / COLMAP sparse / NeRF transforms.json。

统一的内部相机表示（便于 puretorch/gsplat 两种光栅化器复用）:
  world : 右手世界坐标系（UE 数据经 F=diag(1,-1,1) 转换：x=north, y=-east, z=up，单位 cm）
  camera: OpenCV/COLMAP 约定（x 右, y 下, z 前）—— x_cam = R_cw @ X + t_cw
  K     : 3x3 像素内参（res_scale 缩放后）
  image : HxWx3 uint8 RGB（可选）
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np

from colmap_io import F_UE_RH, frames_from_metadata, load_metadata, read_colmap_frames


# --------------------------------------------------------------------------- #
# 图片 / 内参
# --------------------------------------------------------------------------- #
def _resize_K(K, scale):
    if scale == 1.0:
        return K.copy()
    K2 = K.copy()
    K2[0, 0] *= scale
    K2[1, 1] *= scale
    K2[0, 2] = (K[0, 2] + 0.5) * scale - 0.5
    K2[1, 2] = (K[1, 2] + 0.5) * scale - 0.5
    return K2


def read_image(path, scale=1.0):
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise IOError("无法读取图片: %s" % path)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    if scale != 1.0:
        h, w = rgb.shape[:2]
        size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
    return rgb


def _check_rigid(R, name, tol=1e-6):
    """位姿旋转必须正交且 det=+1（防 capture 数据 c2w 非正交 bug 再次混入）。"""
    R = np.asarray(R, dtype=np.float64)
    err = float(np.abs(R @ R.T - np.eye(3)).max())
    det = float(np.linalg.det(R))
    if err > tol or abs(det - 1.0) > tol:
        raise ValueError("位姿旋转非正交: %s (|R R^T - I|max=%.3e, det=%.6f, 容差 %.0e)"
                         % (name, err, det, tol))


def _make_view(name, image_path, K, R_cw, t_cw, width, height, image, world,
               c2w_ue=None, gps=None, gimbal=None):
    return {"name": name, "image_path": image_path,
            "K": np.asarray(K, dtype=np.float64),
            "R_cw": np.asarray(R_cw, dtype=np.float64).reshape(3, 3),
            "t_cw": np.asarray(t_cw, dtype=np.float64).reshape(3),
            "width": int(width), "height": int(height),
            "image": image, "world": world,
            "c2w_ue": c2w_ue, "gps": gps, "gimbal": gimbal}


# --------------------------------------------------------------------------- #
# 各类数据源 -> views
# --------------------------------------------------------------------------- #
def _views_from_conventions(root, meta_path, image_root, res_scale, load_images):
    meta = load_metadata(meta_path)
    frames = frames_from_metadata(meta, image_root=image_root, check_images=False)
    views = []
    for fr, mf in zip(frames, meta["frames"]):
        image = None
        if load_images:
            image = read_image(fr["image_path"], res_scale)
        h, w = (image.shape[:2] if image is not None else (fr["height"], fr["width"]))
        K = _resize_K(fr["K"], res_scale)
        _check_rigid(fr["R_cw"], fr["name"])
        views.append(_make_view(fr["name"], fr["image_path"], K, fr["R_cw"], fr["t_cw"],
                                w, h, image, "ue_rh_cm",
                                c2w_ue=fr["c2w_ue"], gps=fr["gps"], gimbal=fr["gimbal_deg"]))
    return {"kind": "conventions", "root": root, "metadata": meta, "views": views,
            "world": "ue_rh_cm", "width": meta["width"], "height": meta["height"],
            "dataset": meta.get("dataset", os.path.basename(root))}


def _views_from_colmap(root, sparse_dir, image_root, res_scale, load_images):
    frames, points = read_colmap_frames(sparse_dir, image_root=image_root)
    views = []
    for fr in frames:
        image = None
        if load_images:
            image = read_image(fr["image_path"], res_scale)
        h, w = (image.shape[:2] if image is not None else (fr["height"], fr["width"]))
        K = _resize_K(fr["K"], res_scale)
        views.append(_make_view(fr["name"], fr["image_path"], K, fr["R_cw"], fr["t_cw"],
                                w, h, image, "colmap"))
    return {"kind": "colmap", "root": root, "views": views, "world": "colmap",
            "points": points, "width": views[0]["width"] if views else 0,
            "height": views[0]["height"] if views else 0,
            "dataset": os.path.basename(os.path.normpath(root))}


def _views_from_transforms(root, image_root, res_scale, load_images):
    """NeRF synthetic / instant-ngp 风格 transforms.json（可选支持公开数据集）。"""
    with open(os.path.join(root, "transforms.json"), "r", encoding="utf-8") as f:
        tf = json.load(f)
    W = tf.get("w") or tf.get("width")
    H = tf.get("h") or tf.get("height")
    fx = tf.get("fl_x", tf.get("fx"))
    fy = tf.get("fl_y", tf.get("fy"))
    cx = tf.get("cx", W / 2.0)
    cy = tf.get("cy", H / 2.0)
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    views = []
    for i, fr in enumerate(tf["frames"]):
        c2w_gl = np.asarray(fr.get("transform_matrix", fr.get("c2w")), dtype=np.float64).reshape(4, 4)
        # OpenGL/Blender 相机 (x右,y上,z后) -> OpenCV (x右,y下,z前)
        c2w_cv = c2w_gl.copy()
        c2w_cv[:3, :3] = c2w_gl[:3, :3] @ np.diag([1.0, -1.0, -1.0])
        C = c2w_cv[:3, 3]
        R_cw = c2w_cv[:3, :3].T
        t_cw = -R_cw @ C
        name = fr.get("file_path", "images/%04d.png" % i)
        image_path = os.path.join(image_root, name)
        image = None
        if load_images:
            image = read_image(image_path, res_scale)
        h, w = (image.shape[:2] if image is not None else (H, W))
        views.append(_make_view(name, image_path, _resize_K(K, res_scale), R_cw, t_cw,
                                w, h, image, "gltf"))
    return {"kind": "transforms", "root": root, "views": views, "world": "gltf",
            "width": W, "height": H, "dataset": os.path.basename(os.path.normpath(root))}


def load_dataset(root, res_scale=1.0, load_images=True, metadata=None, image_root=None):
    """自动识别数据集类型并加载。

    root: 目录；metadata: 显式指定 metadata.json 路径（默认 root/metadata.json）
    """
    root = os.path.abspath(root)
    meta_path = metadata or os.path.join(root, "metadata.json")
    img_root = image_root or root
    if os.path.isfile(meta_path):
        return _views_from_conventions(root, meta_path, img_root, res_scale, load_images)
    if os.path.isfile(os.path.join(root, "sparse", "0", "cameras.bin")) or \
       os.path.isfile(os.path.join(root, "sparse", "0", "cameras.txt")):
        sparse_dir = os.path.join(root, "sparse", "0")
    elif os.path.isfile(os.path.join(root, "sparse", "cameras.bin")) or \
            os.path.isfile(os.path.join(root, "sparse", "cameras.txt")):
        sparse_dir = os.path.join(root, "sparse")
    else:
        sparse_dir = None
    if sparse_dir:
        for cand in [os.path.join(root, "images"), root]:
            if os.path.isdir(cand):
                img_root = cand
                break
        return _views_from_colmap(root, sparse_dir, img_root, res_scale, load_images)
    if os.path.isfile(os.path.join(root, "transforms.json")):
        return _views_from_transforms(root, img_root, res_scale, load_images)
    raise ValueError("无法识别数据集类型（缺 metadata.json / sparse / transforms.json）: %s" % root)


def load_val(root, res_scale=1.0, load_images=True):
    """验证集：优先 root/val/metadata_val.json；其次 root/metadata_val.json；否则 None。"""
    root = os.path.abspath(root)
    cands = [
        (os.path.join(root, "val", "metadata_val.json"), os.path.join(root, "val")),
        (os.path.join(root, "metadata_val.json"), root),
        (os.path.join(root, "val", "metadata.json"), os.path.join(root, "val")),
    ]
    for meta_path, img_root in cands:
        if os.path.isfile(meta_path):
            return _views_from_conventions(root, meta_path, img_root, res_scale, load_images)
    # 也允许验证集目录中含 COLMAP / transforms
    if os.path.isdir(os.path.join(root, "val")):
        try:
            return load_dataset(os.path.join(root, "val"), res_scale=res_scale,
                                load_images=load_images)
        except ValueError:
            return None
    return None


def views_to_ply_world(means, world):
    """把内部右手世界坐标转回 PLY 契约坐标系（UE 数据 -> UE LHS: x, -y, z）。"""
    if world == "ue_rh_cm":
        out = means.copy()
        out[..., 1] = -out[..., 1]
        return out
    return means


def ply_world_to_views(means, world):
    if world == "ue_rh_cm":
        out = means.copy()
        out[..., 1] = -out[..., 1]
        return out
    return means


# --------------------------------------------------------------------------- #
# 场景统计（用于初始化 / 学习率 / 归一化）
# --------------------------------------------------------------------------- #
def scene_info(data):
    cs = np.stack([-v["R_cw"].T @ v["t_cw"] for v in data["views"]], axis=0)
    center = cs.mean(axis=0)
    dists = np.linalg.norm(cs - center, axis=1)
    extent = float(np.median(dists) * 2.0)
    return {"center": center, "extent": max(extent, 1e-3),
            "n_views": len(data["views"]),
            "min_cam_dist": float(dists.min()), "max_cam_dist": float(dists.max())}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--scale", type=float, default=0.5)
    args = ap.parse_args()
    d = load_dataset(args.data, res_scale=args.scale, load_images=True)
    print("kind=%s world=%s n_views=%d size=%dx%d" % (
        d["kind"], d["world"], len(d["views"]), d["views"][0]["width"], d["views"][0]["height"]))
    print("scene:", json.dumps({k: (v.tolist() if hasattr(v, "tolist") else v)
                                for k, v in scene_info(d).items()}, ensure_ascii=False))
    v = d["views"][0]
    print("view0 name=%s K=\n%s\nR_cw=\n%s\nt_cw=%s image=%s" % (
        v["name"], v["K"], v["R_cw"], v["t_cw"], None if v["image"] is None else v["image"].shape))
