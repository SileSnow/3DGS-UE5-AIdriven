
# -*- coding: utf-8 -*-
"""生成《DJI Mini x UE5 x 3DGS 技术可行性验证》演示简报（python-pptx）。"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(BASE, "report", "figures")
OUT = os.path.join(BASE, "report", "DJI_Mini_UE5_3DGS_可行性验证_简报.pptx")

BLUE = RGBColor(0x1A, 0x73, 0xE8)
DARK = RGBColor(0x20, 0x21, 0x24)
GREY = RGBColor(0x5F, 0x63, 0x68)
LIGHT = RGBColor(0xF1, 0xF3, 0xF4)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ORANGE = RGBColor(0xE8, 0x71, 0x0A)
GREEN = RGBColor(0x13, 0x73, 0x33)
RED = RGBColor(0xC5, 0x22, 0x1F)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
W = prs.slide_width
H = prs.slide_height

def add_slide():
    return prs.slides.add_slide(BLANK)

def rect(slide, l, t, w, h, fill, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, l, t, w, h)
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    shp.shadow.inherit = False
    return shp

def title_bar(slide, title, sub=None):
    rect(slide, 0, 0, W, Inches(1.02), BLUE)
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.16), W - Inches(1.0), Inches(0.7))
    tf = tb.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.text = title
    p.font.size = Pt(26); p.font.bold = True; p.font.color.rgb = WHITE
    if sub:
        tb2 = slide.shapes.add_textbox(Inches(0.52), Inches(0.72), W - Inches(1.0), Inches(0.35))
        p2 = tb2.text_frame.paragraphs[0]; p2.text = sub
        p2.font.size = Pt(12); p2.font.color.rgb = RGBColor(0xDD, 0xE7, 0xFB)

def footer(slide, idx):
    tb = slide.shapes.add_textbox(Inches(0.5), H - Inches(0.42), Inches(8), Inches(0.3))
    p = tb.text_frame.paragraphs[0]
    p.text = "DJI Mini × UE5 × 3DGS 技术可行性验证  |  2026-11-08"
    p.font.size = Pt(9); p.font.color.rgb = GREY
    tb2 = slide.shapes.add_textbox(W - Inches(1.2), H - Inches(0.42), Inches(0.7), Inches(0.3))
    p2 = tb2.text_frame.paragraphs[0]; p2.text = str(idx)
    p2.font.size = Pt(10); p2.font.color.rgb = GREY; p2.alignment = PP_ALIGN.RIGHT

def bullets(slide, items, l, t, w, h, size=16, color=DARK, spacing=8):
    tb = slide.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = 0; tf.margin_right = 0
    first = True
    for it in items:
        if isinstance(it, tuple):
            text, level = it
        else:
            text, level = it, 0
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_after = Pt(spacing)
        p.text = ("• " if level == 0 else "– ") + text
        p.font.size = Pt(size - 2 * level)
        p.font.color.rgb = color
    return tb

def table(slide, data, l, t, w, h, font=11, header_fill=BLUE, col_widths=None, first_col_bold=False):
    rows, cols = len(data), len(data[0])
    shape = slide.shapes.add_table(rows, cols, l, t, w, h)
    tbl = shape.table
    if col_widths:
        total = sum(col_widths)
        for i, cw in enumerate(col_widths):
            tbl.columns[i].width = Emu(int(w * cw / total))
    for r in range(rows):
        for c in range(cols):
            cell = tbl.cell(r, c)
            cell.text = str(data[r][c])
            cell.margin_left = Inches(0.06); cell.margin_right = Inches(0.06)
            cell.margin_top = Inches(0.03); cell.margin_bottom = Inches(0.03)
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(font)
                if r == 0:
                    p.font.bold = True; p.font.color.rgb = WHITE
                elif first_col_bold and c == 0:
                    p.font.bold = True; p.font.color.rgb = DARK
                else:
                    p.font.color.rgb = DARK
            cell.fill.solid()
            cell.fill.fore_color.rgb = header_fill if r == 0 else (WHITE if r % 2 else LIGHT)
    return tbl

def add_image_fit(slide, path, l, t, w, h, border=True):
    if not os.path.exists(path):
        tb = slide.shapes.add_textbox(l, t, w, h)
        p = tb.text_frame.paragraphs[0]; p.text = "[待生成] " + os.path.basename(path)
        p.font.size = Pt(12); p.font.color.rgb = GREY
        return False
    iw, ih = Image.open(path).size
    scale = min(w / iw, h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    nl = l + int((w - nw) / 2); nt = t + int((h - nh) / 2)
    slide.shapes.add_picture(path, nl, nt, Emu(nw), Emu(nh))
    return True

# ---------------- 1 封面 ----------------
s = add_slide()
rect(s, 0, 0, W, H, RGBColor(0x0B, 0x2E, 0x59))
rect(s, 0, Inches(4.55), W, Inches(0.08), ORANGE)
tb = s.shapes.add_textbox(Inches(0.9), Inches(1.7), W - Inches(1.8), Inches(1.9))
tf = tb.text_frame; tf.word_wrap = True
p = tf.paragraphs[0]; p.text = "以大疆 Mini 系列为基础的\nUE5 3DGS 技术可行性验证"
p.font.size = Pt(40); p.font.bold = True; p.font.color.rgb = WHITE
p.line_spacing = 1.15
tb2 = s.shapes.add_textbox(Inches(0.95), Inches(3.85), W - Inches(1.9), Inches(0.6))
p2 = tb2.text_frame.paragraphs[0]
p2.text = "从 DJI Mobile SDK 采集 → 3DGS 重建 → Unreal Engine 5 实时渲染的端到端实测"
p2.font.size = Pt(17); p2.font.color.rgb = RGBColor(0xC9, 0xD8, 0xF0)
tb3 = s.shapes.add_textbox(Inches(0.95), Inches(5.0), W - Inches(1.9), Inches(1.6))
tf3 = tb3.text_frame; tf3.word_wrap = True
for i, line in enumerate([
    "验证环境：Windows 11 / RTX 5060 Laptop 8GB / UE 5.8.4 / PyTorch 2.13.0+cu130",
    "证据形态：可复现代码 + 本机实测指标 + 官方一手资料",
    "报告日期：2026-11-08  |  验证执行：Lead + 4 个专职智能体（dji-research / gs-pipeline / ue5-splat / capture-synth）",
]):
    p = tf3.paragraphs[0] if i == 0 else tf3.add_paragraph()
    p.text = line; p.font.size = Pt(12.5); p.font.color.rgb = RGBColor(0xB8, 0xC7, 0xE0)

# ---------------- 2 结论速览 ----------------
s = add_slide()
title_bar(s, "结论速览：五维能力评估", "有条件可行 —— 关键路径已在本机跑通，限制条件明确")
data = [
    ["能力", "结论", "等级", "关键依据"],
    ["① SDK 自动化采集", "有条件可行", "L1–L2", "Mini 3/3 Pro/4 Pro 支持 MSDK v5（仅 Android；Mini 4 Pro 需 RC-N2）"],
    ["② 航拍数据满足 3DGS", "可行", "L1–L2", "1/1.3\" 48MP、24mm、f/1.7；40m 航高 GSD≈1.4cm；1 公顷约 77 张"],
    ["③ 3DGS 重建（8GB/限载）", "可行（欠训练）", "L2", "纯 PyTorch 管线跑通：3000 iter / 10.9 万 splat / 显存 1.15GB / val PSNR 13.28"],
    ["④ UE5 实时渲染", "可行（需适配）", "L2", "插件 5.8 编译通过；Path B 点云 30.8fps；Niagara 渲染部分可用（scale 待修）"],
    ["⑤ 端到端工程化", "可行（PoC 级）", "L2–L3", "链路打通，30/90/180 天路线；主要风险=SDK 机型/精度/显存/插件维护"],
]
table(s, data, Inches(0.45), Inches(1.35), W - Inches(0.9), Inches(4.4), font=11,
      col_widths=[1.35, 1.25, 0.75, 4.2], first_col_bold=True)
bullets(s, [
    "推荐方案：Mini 4 Pro（RC-N2 + Android 自研 MSDK App）采集 → 开源 COLMAP/3DGS → PLY → UE5.8 插件渲染",
    "三个硬限制：Mini 5 Pro 无 SDK；无 RTK 定位精度仅视觉级；UE5 无原生 3DGS（Epic 官方明确无计划）",
], Inches(0.45), Inches(5.95), W - Inches(0.9), Inches(1.1), size=12.5)
footer(s, 2)

# ---------------- 3 验证方法 ----------------
s = add_slide()
title_bar(s, "验证方法：两条互补路径 + 可量化判据", "路径 A 提供质量/性能数字；路径 B 验证真实 DJI 数据接口")
rect(s, Inches(0.45), Inches(1.35), Inches(6.1), Inches(2.5), LIGHT)
bullets(s, [
    ("路径 A（主链路，L3）：UE5 合成航拍 → 3DGS → UE5", 0),
    ("程序化校园场景 + 模拟 Mini 4 Pro 相机/航线（真值位姿）", 1),
    ("SceneCapture2D 渲染 160–200 训练视角 + 验证视角", 1),
    ("真值位姿直通训练 → 标准 PLY → UE5 加载渲染", 1),
    ("评估：PSNR/SSIM、渲染图、FPS/显存/耗时", 1),
], Inches(0.7), Inches(1.55), Inches(5.7), Inches(2.2), size=13)
rect(s, Inches(6.8), Inches(1.35), Inches(6.1), Inches(2.5), LIGHT)
bullets(s, [
    ("路径 B（真实接口，L1→L2）：DJI EXIF → 位姿先验 → COLMAP", 0),
    ("真实样片 EXIF/XMP 字段实测（GPS/云台/焦距）", 1),
    ("WGS84→局部 ENU→COLMAP 初始位姿（先验）", 1),
    ("COLMAP/BA 精化 → 3DGS 训练", 1),
    ("用于验证“实拍数据能否进入同一流水线”", 1),
], Inches(7.05), Inches(1.55), Inches(5.7), Inches(2.2), size=13)
data = [
    ["环境", "配置"],
    ["主机 / GPU", "Windows 11 / 32 核 / 16 GB RAM / RTX 5060 Laptop 8 GB（sm_120）"],
    ["软件", "UE 5.8.4 + VS2026(MSVC14.50) + Python 3.14.6 + PyTorch 2.13.0+cu130"],
    ["约束", "无真实无人机；显存紧张；中文路径需 ASCII junction（C:\\UEW）"],
]
table(s, data, Inches(0.45), Inches(4.15), W - Inches(0.9), Inches(2.0), font=11.5,
      col_widths=[1.2, 6.2], first_col_bold=True)
footer(s, 3)

# ---------------- 4 SDK 分档 ----------------
s = add_slide()
title_bar(s, "DJI Mini 系列 SDK 支持分档", "官方兼容表 + MSDK v5 仓库 + Release Notes 交叉验证（2026-11-08）")
add_image_fit(s, os.path.join(FIG, "fig5_sdk_tiers.png"), Inches(0.35), Inches(1.2), W - Inches(0.7), Inches(4.5))
bullets(s, [
    "A′ 档是本次推荐：Mini 4 Pro / Mini 3 Pro / Mini 3 走 MSDK v5（仅 Android；Mini 4 Pro 自 v5.13.0，需 RC-N2，RC-N3 到 v5.17.0）",
    "Mini 5 Pro 无任何 SDK（仅 DJI Fly 原生航点，半自动）；Mini 2 SE / Mini 4K 无 SDK 无航点（手动）",
], Inches(0.45), Inches(5.9), W - Inches(0.9), Inches(1.1), size=12.5)
footer(s, 4)

# ---------------- 5 采集方案与数据量 ----------------
s = add_slide()
title_bar(s, "采集方案对比与数据量估算", "以 3DGS 重建需求反推航线/参数/张数")
data = [
    ["方案", "自动化", "位姿元数据", "成本/门槛", "建议"],
    ["DJI Fly 手动 + 定时拍照", "低", "有 EXIF，一致性差", "零成本", "小场景/验证期"],
    ["DJI Fly 原生航点（仅部分机型）", "中", "有 EXIF", "零成本", "Mini 4/5 Pro 半自动"],
    ["自研 MSDK App（Android+RC-N2）", "高", "GPS/云台/时间戳可回传", "1–3 人周", "生产首选"],
    ["第三方 App（Litchi/Dronelink）", "高", "依 App 导出", "订阅/买断", "快速起步"],
    ["DJI Terra（官方后处理，不采集）", "—", "—", "Flagship 授权；32GB RAM", "官方链替代"],
]
table(s, data, Inches(0.45), Inches(1.3), W - Inches(0.9), Inches(2.75), font=10.5,
      col_widths=[2.3, 0.9, 1.9, 1.6, 1.6], first_col_bold=False)
data2 = [
    ["航高（Mini 4 Pro）", "GSD（12MP）", "单张覆盖", "1 公顷照片数"],
    ["30 m", "1.04 cm/px", "41.8×31.3 m", "≈112"],
    ["40 m", "1.39 cm/px", "55.7×41.8 m", "≈77"],
    ["50 m", "1.74 cm/px", "69.7×52.2 m", "≈54"],
]
table(s, data2, Inches(0.45), Inches(4.35), Inches(7.0), Inches(2.0), font=11,
      col_widths=[1.9, 1.35, 1.6, 1.35], first_col_bold=True)
bullets(s, [
    "重叠率：航向 75% / 旁向 65–75%；固定曝光/白平衡；快门 ≥1/500 s",
    "48MP 模式 GSD 减半（40m 约 0.69 cm/px），但训练显存/时间更高",
], Inches(7.8), Inches(4.4), Inches(5.1), Inches(2.0), size=12)
footer(s, 5)

# ---------------- 6 元数据与位姿先验 ----------------
s = add_slide()
title_bar(s, "元数据与位姿先验：真实 DJI 数据怎么用", "5 张 CC 许可真实样片实测 + WGS84→COLMAP→UE 链路")
bullets(s, [
    "关键字段：GPS(lat/lon/alt)、GimbalYaw/Pitch/Roll（drone-dji XMP）、FocalLength、DateTimeOriginal、GpsStatus",
    "实测发现：修图/导出会剥离 EXIF GPS；全景拼接会改写云台角；UTCAtExposure 可能为空 → 必须用 SD 卡原始文件 + EXIF/XMP 双解析",
    "精度：GPS 绝对误差约 1–5 m（无 RTK）；云台角偏航 1–3°、俯仰/横滚 0.5–2° → 只能做 COLMAP 初始化/约束",
    "本机验证：UE↔COLMAP 坐标换算重投影自检 max = 1.256e-12 px（实现正确）",
], Inches(0.45), Inches(1.3), W - Inches(0.9), Inches(2.6), size=13.5)
add_image_fit(s, os.path.join(FIG, "fig3_coordinates.png"), Inches(0.5), Inches(3.85), W - Inches(1.0), Inches(3.1))
footer(s, 6)

# ---------------- 7 3DGS 重建 ----------------
s = add_slide()
title_bar(s, "3DGS 重建链路实测（本机 8GB 显存）", "自研纯 PyTorch 光栅化器（gsplat JIT 在 Windows/VS2026 下不可用）")
data = [
    ["项目", "实测结果"],
    ["光栅化器正确性", "vs 暴力参考：max|img diff|=1.66e-4、max|alpha diff|=1.85e-4（容差 1e-3）"],
    ["可微性", "梯度反传正常（loss 0.01837→0.00299）"],
    ["速度（RTX 5060）", "150k 高斯 @480×360：forward 53.1 ms，fwd+bwd 136.1 ms，峰值显存 558 MB"],
    ["训练质量（iter 3000）", "val PSNR 13.28 / SSIM 0.347；train 18.44；10.9 万 splat；318 s；峰值显存 1153 MB"],
]
table(s, data, Inches(0.45), Inches(1.35), W - Inches(0.9), Inches(2.7), font=11.5,
      col_widths=[1.65, 5.7], first_col_bold=True)
add_image_fit(s, os.path.join(BASE, "data", "trained", "capture", "run1", "renders", "val_000.png"), Inches(0.5), Inches(4.3), Inches(5.8), Inches(2.7))
add_image_fit(s, os.path.join(BASE, "data", "trained", "capture", "run1", "renders", "gt_000.png"), Inches(6.6), Inches(4.3), Inches(5.8), Inches(2.7))
footer(s, 7)

# ---------------- 8 UE5 集成 ----------------
s = add_slide()
title_bar(s, "UE5.8 集成：生态选型与移植结果", "UE5 无原生 3DGS（Epic 官方 2025-10 明确无计划）→ 第三方插件")
data = [
    ["方案", "类型/许可", "UE 版本", "评价"],
    ["Italink/GaussianSplattingForUnrealEngine", "MIT 开源", "5.5+（已移植 5.8）", "本次采用：Niagara GPU 粒子、代码量小"],
    ["yandex/yags（YaGS）", "开源", "5.5–5.7", "Mesh Shader/深度渲染，5.8 需移植"],
    ["DazaiStudio/SplatRenderer", "Apache-2.0", "5.5+", "仅有预编译 DLL"],
    ["xgrids LCC-3DGS-Unreal-Plugin", "商业 Free+Pro", "5.1–5.8", "十亿点/LOD/VR，生产首选"],
    ["Cesium for Unreal（3DGS 3D Tiles）", "开源插件", "UE5", "配合 DJI Terra 3DTiles 大场景流送（待验证）"],
]
table(s, data, Inches(0.45), Inches(1.3), W - Inches(0.9), Inches(2.9), font=10.5,
      col_widths=[2.9, 1.25, 1.7, 2.9], first_col_bold=False)
bullets(s, [
    "移植 UE5.8 的 3 类改动：①UPackage::SavePackage 9 参→4 参（FSavePackageArgs）②HLODBuilder GetCRC 改为非 override ③工程路径必须 ASCII（中文路径导致 MSVC C1083）",
    "编译结果：UnrealEditor-*.dll 全部链接成功，增量编译 147.7 s；运行时 harness 编译通过（PLY 解析 50k/6.4 ms）",
], Inches(0.45), Inches(4.5), W - Inches(0.9), Inches(2.2), size=12.5)
footer(s, 8)

# ---------------- 9 UE5 渲染结果 ----------------
s = add_slide()
title_bar(s, "UE5 渲染实测结果", "【截图与性能数据待 ue5-splat 回填】")
add_image_fit(s, os.path.join(BASE, "ue5", "results", "final_v2", "ue_pathb_4views_grid_v2.png"), Inches(0.5), Inches(1.3), Inches(6.0), Inches(3.6))
data = [
    ["splat 数", "分辨率", "FPS", "显存", "备注"],
    ["50k（Niagara）", "1280×720", "95.4", "—", "吞吐口径"],
    ["200k（Niagara）", "1280×720", "104.7", "—", "吞吐口径"],
    ["109k（Path B 点云）", "1280×720", "30.8", "—", "含 CPU 排序"],
    ["500k/1M", "—", "未测", "—", "时间预算不足"],
]
table(s, data, Inches(6.8), Inches(1.3), Inches(6.1), Inches(2.4), font=11,
      col_widths=[1.0, 1.1, 0.9, 0.9, 1.6], first_col_bold=True)
bullets(s, [
    "真实训练 PLY 109,376 splat：解析 28.2 ms / SetPoints 23.5 ms",
    "Path B 点云预览成功（final_v2 4 视角）；Niagara splat 可见但存在 ×100 尺度失配",
], Inches(6.8), Inches(4.0), Inches(6.1), Inches(1.8), size=12)
footer(s, 9)

# ---------------- 10 端到端链路 ----------------
s = add_slide()
title_bar(s, "端到端验证链路", "本次实测路径（蓝）与官方/替代路径（橙）")
add_image_fit(s, os.path.join(FIG, "fig1_pipeline.png"), Inches(0.3), Inches(1.25), W - Inches(0.6), Inches(4.6))
bullets(s, [
    "实测结论：合成航拍采集 → 3DGS 训练 → 标准 PLY → UE5 加载渲染的全链路可跑通；真实 DJI 数据接口（EXIF→先验）通过坐标自检",
], Inches(0.45), Inches(6.0), W - Inches(0.9), Inches(0.9), size=12.5)
footer(s, 10)

# ---------------- 11 风险 ----------------
s = add_slide()
title_bar(s, "风险矩阵与缓解", "R1–R12（详见报告第 8 章）")
add_image_fit(s, os.path.join(FIG, "fig4_risk_matrix.png"), Inches(0.35), Inches(1.2), Inches(8.3), Inches(5.6))
bullets(s, [
    ("🔴 严重：R1 SDK 机型/遥控器限制；R5 UE 无原生支持", 0),
    ("🟠 高：R3 无 RTK 精度；R4 8GB 显存；R8 合规；R9 大场景 PLY；R2 iOS", 0),
    ("🟡 中：R6 排序伪影；R10 商业许可；R11 数据质量", 0),
    ("🟢 低：R7 路径/工具链；R12 时间同步", 0),
    ("缓解：机型锁定 Mini 4 Pro+RC-N2；UE 版本锁定+源码维护；LOD/流式；GCP 校验；保险/空域审批", 0),
], Inches(8.9), Inches(1.35), Inches(4.0), Inches(5.4), size=11.5)
footer(s, 11)

# ---------------- 12 路线图 ----------------
s = add_slide()
title_bar(s, "建议路线图与决策", "PoC 30 天 / 试点 90 天 / 生产 180 天")
data = [
    ["阶段", "周期", "目标", "验收标准"],
    ["P0 技术 PoC", "30 天", "单场景端到端跑通（1–2 公顷）", "UE 实时浏览无明显伪影；链路可复现"],
    ["P1 试点", "90 天", "3–5 场景、采集/训练 SOP", "单场景采集≤X 小时、训练≤Y 小时、帧率达标"],
    ["P2 生产化", "180 天", "多项目复用、LOD/流式、运维", "稳定交付、成本可估算、风险闭环"],
]
table(s, data, Inches(0.45), Inches(1.4), W - Inches(0.9), Inches(2.6), font=12,
      col_widths=[1.5, 1.0, 3.5, 3.4], first_col_bold=True)
bullets(s, [
    "立即行动：采购/租赁 Mini 4 Pro + RC-N2；实飞 1 个园区 200–400 张；用本报告流水线跑通",
    "处理端：自建开源链（COLMAP + 3DGS + UE 插件）保可控；同步评估 DJI Terra Flagship（本机 16GB RAM 不达标）",
    "渲染端：PoC 用开源插件；生产评估 xgrids LCC 或 Cesium for Unreal 3D Tiles 流式",
    "预期管理：无 RTK → 视觉级精度，不是测绘级；需落图/量测场景另配 RTK 或控制点",
], Inches(0.45), Inches(4.3), W - Inches(0.9), Inches(2.5), size=13)
footer(s, 12)

# ---------------- 13 结尾 ----------------
s = add_slide()
rect(s, 0, 0, W, H, RGBColor(0x0B, 0x2E, 0x59))
tb = s.shapes.add_textbox(Inches(1.0), Inches(2.2), W - Inches(2.0), Inches(1.2))
p = tb.text_frame.paragraphs[0]; p.text = "Q & A"
p.font.size = Pt(52); p.font.bold = True; p.font.color.rgb = WHITE
tb2 = s.shapes.add_textbox(Inches(1.0), Inches(3.6), W - Inches(2.0), Inches(2.4))
tf = tb2.text_frame; tf.word_wrap = True
for i, line in enumerate([
    "报告全文：report/DJI_Mini_UE5_3DGS_可行性验证报告.md",
    "复现工程：dji_ue5_3dgs/（docs/research / pipeline / capture / ue5 / data）",
    "关键证据：官方 SDK 兼容表与 Release Notes、5 张真实样片 EXIF 实测、本机编译/训练/渲染日志",
]):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    p.text = line; p.font.size = Pt(14); p.font.color.rgb = RGBColor(0xC9, 0xD8, 0xF0)
    p.space_after = Pt(10)

prs.save(OUT)
print("SAVED", OUT, "slides=", len(prs.slides))
