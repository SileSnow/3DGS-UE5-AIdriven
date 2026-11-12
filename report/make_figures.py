
# -*- coding: utf-8 -*-
import os, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.font_manager as fm

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")
os.makedirs(OUT, exist_ok=True)
fp = r"C:\Windows\Fonts\msyh.ttc"
if os.path.exists(fp):
    fm.fontManager.addfont(fp)
    plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
plt.rcParams["axes.unicode_minus"] = False

def box(ax, x, y, w, h, text, fc="#E8F0FE", ec="#1A73E8", fs=10):
    ax.add_patch(FancyBboxPatch((x-w/2, y-h/2), w, h, boxstyle="round,pad=0.02,rounding_size=0.02",
                                fc=fc, ec=ec, lw=1.5, zorder=2))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, zorder=3)

def arrow(ax, x1, y1, x2, y2, color="#555555", text=None, fs=8, dx=0.0, dy=0.04):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14,
                                  lw=1.5, color=color, zorder=1, shrinkA=3, shrinkB=3))
    if text:
        ax.text((x1+x2)/2+dx, (y1+y2)/2+dy, text, ha="center", va="bottom", fontsize=fs, color="#333333")

# ================= 图1 =================
fig, ax = plt.subplots(figsize=(16, 5.8))
ax.set_xlim(0, 16); ax.set_ylim(0, 5.8); ax.axis("off")
ax.text(8, 5.45, "图1  DJI Mini → 3DGS → UE5 端到端验证链路（蓝色：本次实测主链路；橙色：官方/替代链路）",
        ha="center", fontsize=13, fontweight="bold")
y = 3.85
coords = [(1.5, "① DJI Mini 3/3 Pro/4 Pro\n(RC-N2 + Android)\n航拍采集"),
          (4.2, "② 数据资产\n照片(12/48MP)+EXIF\nGPS/云台/时间戳"),
          (6.9, "③ 位姿求解\npycolmap/COLMAP\n或已知位姿直通"),
          (9.6, "④ 3DGS 训练\ngsplat / 纯PyTorch\nSH+opacity+scale+rot"),
          (12.3, "⑤ PLY 导出\n标准 3DGS 字段\n+ PSNR/SSIM 评估"),
          (14.85, "⑥ UE5 渲染\n插件加载 PLY\n实时浏览")]
for x, t in coords:
    box(ax, x, y, 2.15, 1.05, t, fs=9.2)
for i in range(len(coords)-1):
    arrow(ax, coords[i][0]+1.08, y, coords[i+1][0]-1.08, y)
y2 = 1.75
box(ax, 4.2, y2, 2.5, 1.0, "DJI Terra v5.0+\n(Flagship)\n可见光 GS 重建", fc="#FFF4E5", ec="#E8710A", fs=9.2)
box(ax, 7.9, y2, 2.7, 1.0, "3D Tiles / PLY / GeoTIFF\n输出 <Project>/3dgs/results", fc="#FFF4E5", ec="#E8710A", fs=9.2)
box(ax, 11.7, y2, 2.9, 1.0, "Cesium for Unreal\n(2026-04 起支持 3DGS\n3D Tiles + LOD)", fc="#FFF4E5", ec="#E8710A", fs=9.2)
arrow(ax, 5.45, y2, 6.55, y2, text="官方一键重建")
arrow(ax, 9.25, y2, 10.25, y2, text="流式加载")
arrow(ax, 12.6, y2+0.35, 14.3, y-0.55, text="替代集成路线", dx=0.2, dy=0.05)
ax.text(8, 0.55,
        "关键判据：① 机型+遥控器+MSDK 版本；② 采集重叠率/画质；③ 位姿精度（无 RTK）；④ 8GB 显存训练；⑤ UE5 无原生 GS 支持 → 第三方插件/官方链。",
        ha="center", va="center", fontsize=9.2, color="#444444",
        bbox=dict(boxstyle="round,pad=0.3", fc="#F7F7F7", ec="#CCCCCC"))
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig1_pipeline.png"), dpi=170, bbox_inches="tight"); plt.close(fig)

# ================= 图2 =================
fig, ax = plt.subplots(figsize=(14, 6.6))
ax.set_xlim(0, 14); ax.set_ylim(0, 6.6); ax.axis("off")
ax.text(7, 6.25, "图2  UE5.8 内的 3DGS 渲染集成方案（以开源插件为例）", ha="center", fontsize=13, fontweight="bold")
box(ax, 1.9, 5.0, 2.5, 0.95, "gaussians.ply\n(binary LE, 3DGS 字段)", fc="#E6F4EA", ec="#137333", fs=9)
box(ax, 5.2, 5.0, 3.2, 0.95, "解析器(C++)\nSH→颜色, opacity→α\nscale/rot→协方差", fs=9)
box(ax, 9.2, 5.0, 3.2, 0.95, "GPU 缓冲\n位置/协方差/颜色/透明度\n(可压缩: SPZ/LCC/SOG)", fs=9)
arrow(ax, 3.18, 5.0, 3.57, 5.0); arrow(ax, 6.83, 5.0, 7.57, 5.0)

box(ax, 3.2, 3.25, 3.0, 0.95, "每帧视锥剔除 +\n深度排序\n(CPU argsort / GPU radix)", fs=9)
box(ax, 7.1, 3.25, 3.2, 0.95, "2D 高斯投影(EWA)\nNiagara GPU 粒子 / Mesh Shader\n→ billboard quad", fs=9)
box(ax, 11.2, 3.25, 2.9, 0.95, "半透明 α 合成\n(排序 / 近似 OIT)", fs=9)
arrow(ax, 6.6, 4.52, 6.6, 3.75, text="", dx=0)
arrow(ax, 4.72, 3.25, 5.48, 3.25, text="排序索引", fs=8, dy=0.06)
arrow(ax, 8.72, 3.25, 9.73, 3.25)

box(ax, 5.2, 1.45, 4.2, 0.95, "UE 场景渲染 / 后处理 / TAA / 景深\n(启用深度通道则与网格正确遮挡)", fs=9)
arrow(ax, 11.2, 2.77, 7.4, 1.95, text="")
box(ax, 11.0, 1.45, 3.4, 0.95, "输出：viewport / 截图 / 序列帧\n统计：FPS、VRAM、加载时间", fc="#FFF4E5", ec="#E8710A", fs=9)
arrow(ax, 7.35, 1.45, 9.25, 1.45)
ax.text(7, 0.45, "能力边界：3DGS 为半透明图元，无物理光照/阴影；超大场景需 LOD/分块；UE 5.8 无内置支持（Epic 2025-10 官方声明）。",
        ha="center", fontsize=9.2, color="#444444")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig2_ue5_architecture.png"), dpi=170, bbox_inches="tight"); plt.close(fig)

# ================= 图3 =================
fig, ax = plt.subplots(figsize=(14, 4.8))
ax.set_xlim(0, 14); ax.set_ylim(0, 4.8); ax.axis("off")
ax.text(7, 4.5, "图3  坐标系统与位姿先验：DJI EXIF/WGS84 → COLMAP 相机 → UE 世界", ha="center", fontsize=13, fontweight="bold")
items = [
    (1.55, "DJI EXIF/XMP\nGPS(lat,lon,alt)\nGimbal 角、焦距、尺寸"),
    (4.35, "局部 ENU 世界系\nWGS84→ENU\n(选原点, 米/厘米)"),
    (7.15, "COLMAP 相机\nX右 Y下 Z前 (RH)\nqvec/tvec fx,fy,cx,cy"),
    (9.95, "UE 世界/相机\nX前 Y右 Z上 (LH, cm)\nc2w 4x4"),
    (12.65, "重投影自检\n< 1 px\n否则拒绝"),
]
for i, (x, t) in enumerate(items):
    box(ax, x, 2.75, 2.2, 1.45, t, fs=8.6)
    if i < len(items)-1:
        arrow(ax, x+1.12, 2.75, items[i+1][0]-1.12, 2.75)
ax.text(7, 1.1,
        "先验使用原则：GPS 1–3 m、云台角约 0.1° 仅作 COLMAP 初始化/约束（缩短匹配时间、抑制漂移）；最终位姿必须 SfM/BA 精化。\n"
        "合成数据链路直接使用 UE 真值 c2w（跳过 SfM，用于隔离验证 3DGS 与 UE 环节）。",
        ha="center", va="center", fontsize=9.2, color="#444444",
        bbox=dict(boxstyle="round,pad=0.35", fc="#F7F7F7", ec="#CCCCCC"))
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig3_coordinates.png"), dpi=170, bbox_inches="tight"); plt.close(fig)

# ================= 图4 =================
fig, ax = plt.subplots(figsize=(12.5, 7.6))
ax.set_xlim(1.2, 6.3); ax.set_ylim(1.2, 5.5)
risks = [
    ("R1", "SDK 机型/遥控器限制\n(Mini 5 Pro 不支持; RC-N2; Android)", 4, 4),
    ("R2", "iOS MSDK 缺失", 4, 3),
    ("R3", "无 RTK 定位精度\n(测绘级不达标)", 4, 3),
    ("R4", "8GB 显存限制\n(大场景训练/渲染)", 4, 3),
    ("R5", "UE 无原生 GS 支持\n插件维护/升级风险", 4, 4),
    ("R6", "半透明排序伪影\n(高质量要求场景)", 3, 3),
    ("R7", "非 ASCII 路径/工具链坑", 3, 2),
    ("R8", "飞行合规/空域审批", 3, 4),
    ("R9", "大场景 PLY 体积\n(加载/流送)", 5, 3),
    ("R10", "商业插件许可成本", 3, 3),
]
for (rid, label, l, i) in risks:
    ax.scatter(l, i, s=700, c="#FF6D00", edgecolor="#B34700", alpha=0.9, zorder=3)
    ax.text(l, i, rid, ha="center", va="center", fontsize=9, color="white", fontweight="bold", zorder=4)
ax.set_xlim(1.3, 6.3); ax.set_ylim(1.2, 5.6)
ax.set_xlabel("发生概率（1 低 → 5 高）", fontsize=11); ax.set_ylabel("影响程度（1 低 → 5 高）", fontsize=11)
ax.set_title("图4  风险矩阵（初版；实测后更新）", fontsize=13, fontweight="bold")
ax.grid(alpha=0.25, linestyle="--")
ax.text(2.3, 4.95, "低概率/高影响", fontsize=10, color="#AAAAAA")
ax.text(5.1, 4.95, "高概率/高影响", fontsize=10, color="#AAAAAA")
ax.text(2.3, 1.45, "低概率/低影响", fontsize=10, color="#AAAAAA")
ax.text(5.1, 1.45, "高概率/低影响", fontsize=10, color="#AAAAAA")
legend = "\n".join([f"{rid}: {lbl.replace(chr(10), ' ')}" for rid, lbl, _, _ in risks])
ax.text(6.45, 3.4, legend, fontsize=8.2, va="center", ha="left",
        bbox=dict(boxstyle="round,pad=0.4", fc="#FAFAFA", ec="#DDDDDD"))
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig4_risk_matrix.png"), dpi=170, bbox_inches="tight"); plt.close(fig)

print("FIGURES OK", sorted(os.listdir(OUT)))
