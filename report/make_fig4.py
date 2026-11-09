
# -*- coding: utf-8 -*-
import os, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
OUT = r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\report\figures"
fp = r"C:\Windows\Fonts\msyh.ttc"
if os.path.exists(fp):
    fm.fontManager.addfont(fp); plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
plt.rcParams["axes.unicode_minus"] = False
risks = {
 (4,4):["R1","R5"], (4,3):["R2","R3","R4"], (3,3):["R6","R10"], (3,4):["R8"],
 (3,2):["R7"], (5,3):["R9"], (4,2):["R11","R12"]
}
fig, ax = plt.subplots(figsize=(12.5, 7.2))
for l in range(1,6):
    for i in range(1,6):
        ids = risks.get((l,i), [])
        sev = l*i
        color = "#E8F5E9" if sev <= 4 else ("#FFF8E1" if sev <= 9 else ("#FFE0B2" if sev <= 16 else "#FFCDD2"))
        ax.add_patch(plt.Rectangle((l-0.5, i-0.5), 1, 1, facecolor=color, edgecolor="#CCCCCC", lw=1))
        if ids:
            ax.text(l, i, "\n".join(ids), ha="center", va="center", fontsize=13, fontweight="bold", color="#B23A00")
ax.set_xlim(0.5, 5.5); ax.set_ylim(0.5, 5.5)
ax.set_xticks(range(1,6)); ax.set_yticks(range(1,6))
ax.set_xlabel("发生概率（1 低 → 5 高）", fontsize=11)
ax.set_ylabel("影响程度（1 低 → 5 高）", fontsize=11)
ax.set_title("图4  风险矩阵（R1–R12；格子内为风险编号，详见 8.1 表）", fontsize=13, fontweight="bold")
ax.set_xticklabels(["1 很低","2 低","3 中","4 高","5 很高"], fontsize=9)
ax.set_yticklabels(["1 很低","2 低","3 中","4 高","5 很高"], fontsize=9)
legend = ("R1 SDK机型/遥控器限制   R2 iOS MSDK缺失   R3 无RTK精度   R4 8GB显存\n"
          "R5 UE无原生GS支持   R6 半透明排序伪影   R7 非ASCII路径   R8 飞行合规\n"
          "R9 大场景PLY体积   R10 商业许可成本   R11 采集数据质量   R12 时间同步")
ax.text(0.5, -0.9, legend, fontsize=8.5, va="top", ha="left", color="#444444")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig4_risk_matrix.png"), dpi=170, bbox_inches="tight"); plt.close(fig)
print("fig4 grid ok")
