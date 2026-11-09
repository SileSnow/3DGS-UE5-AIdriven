"""colmap_io.py -- COLMAP 数据读写 + UE<->COLMAP 坐标换算（shared/CONVENTIONS.md §3）。

约定（务必与 shared/CONVENTIONS.md 保持一致）:
  UE 世界: 左手系, +X 前(north), +Y 右(east), +Z 上, 单位 cm
  右手世界: p_rh = F @ p_ue, F = diag(1, -1, 1)
  OpenCV/COLMAP 相机: x 右, y 下, z 前
  R_cw = P @ R_ue^T @ F,  P = [[0,1,0],[0,0,-1],[1,0,0]]
      （R_ue = c2w_ue[:3,:3], 列为相机轴 fwd/right/up 在 UE 世界的方向）
  t_cw = -R_cw @ C_rh,  C_rh = F @ C_ue
  反变换: R_ue = F @ R_cw^T @ P^T ; C_ue = F @ C_rh, C_rh = -R_cw^T @ t_cw

提供:
  - quat/rotmat 互转（COLMAP qvec = w,x,y,z）
  - ue_c2w_to_colmap / colmap_to_ue_c2w
  - 两个独立投影函数（UE 直接投影 vs COLMAP 投影）用于重投影自检
  - metadata.json 读取（CONVENTIONS 合成数据格式）
  - COLMAP text 格式写出 + 读回校验（cameras.txt/images.txt/points3D.txt）
  - 从 COLMAP sparse 读取相机位姿（training/eval 用）
"""
from __future__ import annotations

import json
import os

import numpy as np

F_UE_RH = np.diag([1.0, -1.0, 1.0])                       # UE -> 右手世界
P_UE_CV = np.array([[0.0, 1.0, 0.0],
                    [0.0, 0.0, -1.0],
                    [1.0, 0.0, 0.0]])                      # UE 相机轴 -> OpenCV 相机轴


# --------------------------------------------------------------------------- #
# 四元数 / 旋转矩阵（COLMAP qvec = (w, x, y, z)）
# --------------------------------------------------------------------------- #
def qvec_to_rotmat(qvec):
    q = np.asarray(qvec, dtype=np.float64)
    n = np.linalg.norm(q)
    if n < 1e-12:
        return np.eye(3)
    w, x, y, z = q / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def rotmat_to_qvec(R):
    """旋转矩阵 -> 四元数 (w,x,y,z)，w >= 0，数值稳定。"""
    R = np.asarray(R, dtype=np.float64)
    tr = np.trace(R)
    if tr > 0.0:
        s = np.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float64)
    q /= np.linalg.norm(q)
    if q[0] < 0:
        q = -q
    return q


# --------------------------------------------------------------------------- #
# UE <-> COLMAP 位姿换算
# --------------------------------------------------------------------------- #
def ue_c2w_to_colmap(c2w_ue):
    """UE 4x4 c2w(相机->UE 世界) -> (R_cw 3x3, t_cw 3, C_rh 3)。"""
    M = np.asarray(c2w_ue, dtype=np.float64).reshape(4, 4)
    R_ue = M[:3, :3]
    C_ue = M[:3, 3]
    R_cw = P_UE_CV @ R_ue.T @ F_UE_RH
    C_rh = F_UE_RH @ C_ue
    t_cw = -R_cw @ C_rh
    return R_cw, t_cw, C_rh


def colmap_to_ue_c2w(R_cw, t_cw):
    """COLMAP (R_cw, t_cw) -> UE 4x4 c2w。"""
    R_cw = np.asarray(R_cw, dtype=np.float64)
    t_cw = np.asarray(t_cw, dtype=np.float64)
    R_ue = F_UE_RH @ R_cw.T @ P_UE_CV
    C_rh = -R_cw.T @ t_cw
    C_ue = F_UE_RH @ C_rh
    M = np.eye(4)
    M[:3, :3] = R_ue
    M[:3, 3] = C_ue
    return M


def intrinsics_matrix(fx, fy, cx, cy):
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)


def project_ue(R_ue, C_ue, K, pts_ue):
    """UE 相机直接投影: x_cam = R_ue^T (X - C), u = fx*y/x+cx, v = fy*(-z)/x+cy。"""
    pts_ue = np.asarray(pts_ue, dtype=np.float64).reshape(-1, 3)
    pc = (pts_ue - C_ue) @ R_ue            # == R_ue^T (X-C) 逐行
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    depth = pc[:, 0]
    ok = depth > 1e-6
    d = np.where(ok, depth, 1.0)
    u = fx * (pc[:, 1] / d) + cx
    v = fy * (-pc[:, 2] / d) + cy
    return np.stack([u, v], axis=1), ok


def project_colmap(R_cw, t_cw, K, pts_rh):
    """COLMAP 投影: x_cam = R_cw X + t_cw, u = fx x/z + cx, v = fy y/z + cy。"""
    pts_rh = np.asarray(pts_rh, dtype=np.float64).reshape(-1, 3)
    pc = pts_rh @ R_cw.T + t_cw
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    depth = pc[:, 2]
    ok = depth > 1e-6
    d = np.where(ok, depth, 1.0)
    u = fx * (pc[:, 0] / d) + cx
    v = fy * (pc[:, 1] / d) + cy
    return np.stack([u, v], axis=1), ok


def reprojection_selfcheck(c2w_ue_list, K_list, n_points=64, seed=0, max_depth_cm=8000.0):
    """重投影自检: 同一批 3D 点分别用 UE 直接投影 与 COLMAP 投影, 比较像素差。

    返回 (max_err_px, mean_err_px, n_checked)。
    """
    rng = np.random.default_rng(seed)
    max_err, errs, n = 0.0, [], 0
    for c2w, K in zip(c2w_ue_list, K_list):
        M = np.asarray(c2w, dtype=np.float64).reshape(4, 4)
        R_ue, C_ue = M[:3, :3], M[:3, 3]
        # 在相机前方 2~80m 随机取点
        depth = rng.uniform(200.0, max_depth_cm, size=(n_points, 1))
        u = rng.uniform(-0.9 * K[0, 2], 1.8 * K[0, 2], size=(n_points, 1))   # ~[-0.9cx, 0.9cx]
        v = rng.uniform(-0.9 * K[1, 2], 1.8 * K[1, 2], size=(n_points, 1))
        dir_cam = np.concatenate([depth, (u - K[0, 2]) / K[0, 0] * depth,
                                  -(v - K[1, 2]) / K[1, 1] * depth], axis=1)
        pts_ue = dir_cam @ R_ue.T + C_ue          # (N,3)
        R_cw, t_cw, _ = ue_c2w_to_colmap(M)
        pts_rh = pts_ue @ F_UE_RH.T
        uv_ue, ok1 = project_ue(R_ue, C_ue, K, pts_ue)
        uv_cm, ok2 = project_colmap(R_cw, t_cw, K, pts_rh)
        ok = ok1 & ok2
        if ok.any():
            e = np.linalg.norm(uv_ue[ok] - uv_cm[ok], axis=1)
            errs.extend(e.tolist())
            max_err = max(max_err, float(e.max()))
            n += int(ok.sum())
    mean_err = float(np.mean(errs)) if errs else 0.0
    return max_err, mean_err, n


# --------------------------------------------------------------------------- #
# metadata.json（CONVENTIONS §1 合成数据格式 与 DJI EXIF 转换共用）
# --------------------------------------------------------------------------- #
def load_metadata(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def frames_from_metadata(meta, image_root=None, check_images=True):
    """CONVENTIONS metadata.json -> 统一 frame 列表（含 UE c2w 与 COLMAP 位姿）。"""
    K = intrinsics_matrix(meta["fx"], meta["fy"], meta["cx"], meta["cy"])
    W, H = int(meta["width"]), int(meta["height"])
    frames = []
    for i, fr in enumerate(meta["frames"]):
        c2w = np.asarray(fr["c2w"], dtype=np.float64).reshape(4, 4)
        R_cw, t_cw, C_rh = ue_c2w_to_colmap(c2w)
        name = fr["file"]
        img_path = os.path.join(image_root, name) if image_root else None
        if check_images and image_root and not os.path.exists(img_path):
            raise FileNotFoundError("metadata 引用的图片不存在: %s" % img_path)
        frames.append({
            "index": i,
            "name": name,
            "image_path": img_path,
            "width": W,
            "height": H,
            "K": K.copy(),
            "c2w_ue": c2w,
            "R_cw": R_cw,
            "t_cw": t_cw,
            "C_rh": C_rh,
            "gps": fr.get("gps"),
            "gimbal_deg": fr.get("gimbal_deg"),
            "timestamp": fr.get("timestamp"),
        })
    return frames


# --------------------------------------------------------------------------- #
# COLMAP text 格式读写
# --------------------------------------------------------------------------- #
COLMAP_CAMERA_MODEL = "PINHOLE"


def write_colmap_text(out_dir, frames, points3D=None):
    """写出 COLMAP text 格式（cameras.txt / images.txt / points3D.txt）。

    frames: 上面 frames_from_metadata 的列表（需含 K/R_cw/t_cw/name/width/height）。
    points3D: 可选 [(xyz(3), rgb(3))] 列表，写入 points3D.txt（COLMAP 需要 3D 点才可读）；
              若为空则写 header 注释行。
    返回 out_dir。
    """
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "cameras.txt"), "w", encoding="utf-8") as f:
        f.write("# Camera list with one line of data per camera:\n")
        f.write("#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        f.write("# Number of cameras: 1\n")
        K = frames[0]["K"]
        f.write("1 %s %d %d %.10f %.10f %.10f %.10f\n" % (
            COLMAP_CAMERA_MODEL, int(frames[0]["width"]), int(frames[0]["height"]),
            K[0, 0], K[1, 1], K[0, 2], K[1, 2]))

    with open(os.path.join(out_dir, "images.txt"), "w", encoding="utf-8") as f:
        f.write("# Image list with two lines of data per image:\n")
        f.write("#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        f.write("#   POINTS2D[] as (X, Y, POINT3D_ID)\n")
        f.write("# Number of images: %d\n" % len(frames))
        for i, fr in enumerate(frames, start=1):
            q = rotmat_to_qvec(fr["R_cw"])
            t = fr["t_cw"]
            # 用相对路径（相对于 out_dir 的父目录的 images/ 约定不强制；保留 name 原样）
            name = fr["name"].replace("\\", "/")
            f.write("%d %.10f %.10f %.10f %.10f %.10f %.10f %.10f 1 %s\n" % (
                i, q[0], q[1], q[2], q[3], t[0], t[1], t[2], name))
            f.write("\n")

    with open(os.path.join(out_dir, "points3D.txt"), "w", encoding="utf-8") as f:
        f.write("# 3D point list with one line of data per point:\n")
        f.write("#   POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)\n")
        pts = points3D or []
        f.write("# Number of points: %d\n" % len(pts))
        for i, p in enumerate(pts, start=1):
            xyz = np.asarray(p[0], dtype=np.float64)
            rgb = np.asarray(p[1] if len(p) > 1 else (255, 255, 255), dtype=np.int64)
            f.write("%d %.6f %.6f %.6f %d %d %d 0.5\n" % (
                i, xyz[0], xyz[1], xyz[2], rgb[0], rgb[1], rgb[2]))
    return out_dir


def read_colmap_frames(sparse_dir, image_root=None, name_to_index=None):
    """用 pycolmap 读回 COLMAP reconstruction，转为统一 frame 列表（OpenCV 位姿）。

    返回 (frames, points) —— points: (N,3) xyz + (N,3) rgb。
    """
    import pycolmap
    rec = pycolmap.Reconstruction(sparse_dir)
    frames = []
    for img_id in sorted(rec.images.keys()):
        img = rec.images[img_id]
        cam = rec.cameras[img.camera_id]
        # pycolmap 4.x: img.cam_from_world 可能是属性或方法（Rigid3d: cam 相对 world）
        cfw = img.cam_from_world
        if callable(cfw):
            cfw = cfw()
        try:
            R = cfw.rotation.matrix()
        except AttributeError:
            R = np.asarray(cfw.rotation, dtype=np.float64)
        t = cfw.translation
        params = np.asarray(cam.params, dtype=np.float64)
        if cam.model_name in ("PINHOLE", "OPENCV", "FULL_OPENCV", "OPENCV_FISHEYE"):
            fx, fy, cx, cy = params[0], params[1], params[2], params[3]
        elif cam.model_name in ("SIMPLE_RADIAL", "RADIAL"):
            fx = fy = params[0]
            cx, cy = params[1], params[2]
        elif cam.model_name in ("SIMPLE_PINHOLE",):
            fx = fy = params[0]
            cx, cy = params[1], params[2]
        else:
            raise ValueError("不支持的相机模型: %s" % cam.model_name)
        frames.append({
            "name": img.name,
            "image_path": os.path.join(image_root, img.name) if image_root else None,
            "width": int(cam.width), "height": int(cam.height),
            "K": intrinsics_matrix(fx, fy, cx, cy),
            "R_cw": np.asarray(R, dtype=np.float64).reshape(3, 3),
            "t_cw": np.asarray(t, dtype=np.float64).reshape(3),
            "gps": None, "gimbal_deg": None,
        })
    pts_xyz, pts_rgb = [], []
    for pid in sorted(rec.points3D.keys()):
        p = rec.points3D[pid]
        pts_xyz.append([p.xyz[0], p.xyz[1], p.xyz[2]])
        pts_rgb.append([p.color[0], p.color[1], p.color[2]])
    points = (np.asarray(pts_xyz, dtype=np.float64).reshape(-1, 3),
              np.asarray(pts_rgb, dtype=np.int64).reshape(-1, 3))
    return frames, points


def verify_colmap_write(sparse_dir, frames, n_points=48, max_err_px=1.0):
    """写出的 COLMAP 与 UE 元数据之间做重投影自检（读回 → 投影 → 与 UE 直接投影比）。"""
    import pycolmap
    rec = pycolmap.Reconstruction(sparse_dir)
    rec_frames = {f["name"]: f for f in read_colmap_frames(sparse_dir)[0]}
    rng = np.random.default_rng(1)
    errs = []
    for fr in frames:
        rf = rec_frames.get(fr["name"].replace("\\", "/"))
        if rf is None:
            raise RuntimeError("COLMAP 中缺少图片: %s" % fr["name"])
        M = fr["c2w_ue"]
        R_ue, C_ue = M[:3, :3], M[:3, 3]
        K = fr["K"]
        depth = rng.uniform(200.0, 8000.0, size=(n_points, 1))
        du = rng.uniform(-0.9 * K[0, 2], 0.9 * K[0, 2], size=(n_points, 1))
        dv = rng.uniform(-0.9 * K[1, 2], 0.9 * K[1, 2], size=(n_points, 1))
        pts_ue = np.concatenate([
            depth, du / K[0, 0] * depth, -dv / K[1, 1] * depth], axis=1) @ R_ue.T + C_ue
        uv_ue, ok1 = project_ue(R_ue, C_ue, K, pts_ue)
        pts_rh = pts_ue @ F_UE_RH.T
        uv_cm, ok2 = project_colmap(rf["R_cw"], rf["t_cw"], rf["K"], pts_rh)
        ok = ok1 & ok2
        errs.extend(np.linalg.norm(uv_ue[ok] - uv_cm[ok], axis=1).tolist())
    errs = np.asarray(errs)
    mx, mean = float(errs.max()) if errs.size else 0.0, float(errs.mean()) if errs.size else 0.0
    return {"max_reproj_err_px": mx, "mean_reproj_err_px": mean,
            "n_checked": int(errs.size), "ok": bool(mx < max_err_px)}


if __name__ == "__main__":
    # 自检: 构造随机 UE c2w，验证换算闭环 + 重投影误差
    rng = np.random.default_rng(0)
    c2w_list, K_list = [], []
    for _ in range(5):
        # 随机朝向的 UE 相机（相机轴 fwd/right/up）
        fwd = rng.normal(size=3); fwd /= np.linalg.norm(fwd)
        up_ref = np.array([0.0, 0.0, 1.0])
        if abs(fwd @ up_ref) > 0.95:
            up_ref = np.array([1.0, 0.0, 0.0])
        right = np.cross(up_ref, fwd); right /= np.linalg.norm(right)
        up = np.cross(fwd, right)
        R = np.stack([fwd, right, up], axis=1)
        M = np.eye(4); M[:3, :3] = R; M[:3, 3] = rng.uniform(-3000, 3000, size=3)
        c2w_list.append(M)
        K_list.append(intrinsics_matrix(700.0, 700.0, 480.0, 360.0))
    mx, mean, n = reprojection_selfcheck(c2w_list, K_list)
    print("UE<->COLMAP 重投影自检: max=%.3e px mean=%.3e px (n=%d)" % (mx, mean, n))
    # 闭环：colmap -> ue -> colmap
    M = c2w_list[0]
    R_cw, t_cw, _ = ue_c2w_to_colmap(M)
    M2 = colmap_to_ue_c2w(R_cw, t_cw)
    print("c2w 闭环误差: %.3e" % np.abs(M - M2).max())
    print("rotmat->quat->rotmat 误差: %.3e" % np.abs(qvec_to_rotmat(rotmat_to_qvec(R_cw)) - R_cw).max())
