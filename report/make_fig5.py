
# -*- coding: utf-8 -*-
import os, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import matplotlib.font_manager as fm
OUT = r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\report\figures"
fp = r"C:\Windows\Fonts\msyh.ttc"
if os.path.exists(fp):
    fm.fontManager.addfont(fp); plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots(figsize=(15, 6.4))
ax.set_xlim(0, 15); ax.set_ylim(0, 6.4); ax.axis("off")
ax.text(7.5, 6.05, "图5  DJI Mini 系列 SDK 支持分档与关键版本时间线", ha="center", fontsize=13, fontweight="bold")

rows = [
    ("A 档：SDK 全自动（MSDK v4；Android 已证实，iOS 待复核）", "#E8F0FE", "#1A73E8",
     "Mavic Mini | Mini SE | Mini 2", "Mavic Mini v4.13（二级证据）/ Mini 2·SE v4.16（2021-12-31）"),
    ("A′ 档：SDK 全自动（MSDK v5，仅 Android）", "#E6F4EA", "#137333",
     "Mini 4 Pro | Mini 3 Pro | Mini 3", "v5.13.0（2025-03-17）/ v5.3.0（2023-04-07）"),
    ("B 档：无 SDK，DJI Fly 航点半自动", "#FFF4E5", "#E8710A",
     "Mini 5 Pro", "无 SDK；DJI Fly 航点官方支持"),
    ("C 档：无 SDK 且无原生航点（手动）", "#FDECEA", "#C5221F",
     "Mini 2 SE | Mini 4K", "无"),
]
for i, (title, fc, ec, models, ver) in enumerate(rows):
    y = 4.85 - i * 1.1
    ax.add_patch(FancyBboxPatch((0.4, y - 0.42), 14.2, 0.84, boxstyle="round,pad=0.02,rounding_size=0.05",
                                fc=fc, ec=ec, lw=1.6))
    ax.text(0.65, y + 0.12, title, fontsize=10.5, fontweight="bold", va="center")
    ax.text(0.65, y - 0.18, "机型：" + models + "    版本：" + ver, fontsize=9.2, va="center", color="#333333")

ax.text(8.2, 0.35,
        "硬约束：RC-N2（手机夹持）才支持 MSDK，RC 2（带屏）不支持；Mini 4 Pro 自 v5.13.0（2025-03-17）起支持、RC-N3 到 v5.17.0（2025-11-04）才加入；MSDK v5 仅 Android。",
        ha="center", fontsize=9.2, color="#444444",
        bbox=dict(boxstyle="round,pad=0.3", fc="#F7F7F7", ec="#CCCCCC"))
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig5_sdk_tiers.png"), dpi=170, bbox_inches="tight"); plt.close(fig)
print("fig5 ok")
