# -*- coding: utf-8 -*-
"""生成 DJI Mini × UE5 3DGS 可行性验证汇报视频（1080p/30fps/约90s，无音频）。"""
import os, sys, subprocess, json, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

ROOT = r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs"
OUT_MP4 = os.path.join(ROOT, "report", "DJI_Mini_UE5_3DGS_演示视频.mp4")
OUT_POSTER = os.path.join(ROOT, "report", "DJI_Mini_UE5_3DGS_演示视频_封面.png")
W, H = 1920, 1080
FPS = 30
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FFMPEG = None
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    pass

ACCENT = (79, 209, 197)       # teal
ACCENT2 = (245, 158, 66)      # orange
TEXT = (236, 242, 248)
MUTED = (150, 165, 185)
DARK1 = np.array([10, 16, 32], dtype=np.float32)
DARK2 = np.array([18, 28, 52], dtype=np.float32)

def font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)

def base_canvas():
    # 背景渐变 + 网格 + 顶部/底部装饰
    grad = np.zeros((H, W, 3), dtype=np.float32)
    for y in range(H):
        t = y / (H - 1)
        grad[y, :, :] = DARK1 * (1 - t) + DARK2 * t
    # 右上角光晕
    yy, xx = np.mgrid[0:H, 0:W]
    cx, cy = W * 0.82, -H * 0.1
    r = np.sqrt(((xx - cx) / W) ** 2 + ((yy - cy) / H) ** 2)
    glow = np.clip(1.0 - r * 2.6, 0, 1)[..., None] ** 2
    grad += glow * np.array([30, 60, 80], dtype=np.float32)
    img = Image.fromarray(np.clip(grad, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img, "RGBA")
    # 网格
    for x in range(0, W, 120):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 8), width=1)
    for y in range(0, H, 120):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 8), width=1)
    # 顶部/底部条
    d.rectangle([0, 0, W, 6], fill=ACCENT + (255,))
    d.rectangle([0, H - 4, W, H], fill=(40, 52, 70, 255))
    return img

BG = base_canvas()

def footer(d, text="DJI Mini × UE5 3DGS 技术可行性验证 ｜ 本机实测 ｜ 2026-11-08"):
    f = font(22)
    d.text((72, H - 52), text, font=f, fill=MUTED)
    d.text((W - 72, H - 52), "GAIA / dji_ue5_3dgs", font=f, fill=MUTED, anchor="ra")

def header(d, title, sub=None, idx=None):
    d.text((72, 48), title, font=font(52, True), fill=TEXT)
    if sub:
        d.text((76, 118), sub, font=font(26), fill=MUTED)
    d.rectangle([72, 160, 72 + 96, 164], fill=ACCENT + (255,))
    if idx:
        d.text((W - 72, 52), idx, font=font(24, True), fill=(120, 140, 165), anchor="ra")

def wrap(d, text, f, maxw):
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) <= maxw:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines

def place_image(canvas, path, box, border=True, shadow=True, radius=14):
    if not os.path.exists(path):
        return False
    im = Image.open(path).convert("RGB")
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    scale = min(bw / im.width, bh / im.height)
    nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    px, py = x0 + (bw - nw) // 2, y0 + (bh - nh) // 2
    if shadow:
        sh = Image.new("RGBA", (nw + 40, nh + 40), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sd.rounded_rectangle([20, 20, nw + 20, nh + 20], radius=radius, fill=(0, 0, 0, 110))
        sh = sh.filter(ImageFilter.GaussianBlur(12))
        canvas.paste(sh, (px - 20, py - 20), sh)
    canvas.paste(im, (px, py))
    if border:
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle([px, py, px + nw, py + nh], radius=radius, outline=(90, 110, 140), width=2)
    return True

def bullet_block(d, items, x, y, w, size=30, gap=58, color=TEXT, mark_color=ACCENT):
    f = font(size)
    for i, item in enumerate(items):
        yy = y + i * gap
        d.rounded_rectangle([x, yy + 8, x + 12, yy + 20], radius=6, fill=mark_color + (255,))
        lines = wrap(d, item, f, w - 36)
        for j, ln in enumerate(lines):
            d.text((x + 30, yy + j * (size + 10)), ln, font=f, fill=color)

def slide_cover():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    d.text((120, 220), "DJI Mini × UE5 3DGS", font=font(110, True), fill=TEXT)
    d.text((124, 360), "技术可行性验证 · 汇报演示", font=font(52), fill=ACCENT)
    d.rectangle([124, 452, 124 + 180, 458], fill=ACCENT2 + (255,))
    d.text((124, 500), "SDK 自动采集  ·  3DGS 重建  ·  UE 5.8 渲染集成", font=font(34), fill=(190, 205, 225))
    d.text((124, 566), "本机实测：AMD R9 8945HX / RTX 5060 8GB / UE 5.8.4 / 4 核限载（≤80°C）", font=font(26), fill=MUTED)
    d.text((124, 640), "报告 41,186 字  ·  5 张图表  ·  13 页 PPTX  ·  全部结果可复现", font=font(26), fill=MUTED)
    d.text((124, 820), "Evidence-backed feasibility  ·  2026-11-08", font=font(24, True), fill=(120, 150, 175))
    footer(d, "带一手引用与实测证据 ｜ 开源链路 vs DJI 官方链 ｜ 结论与路线图")
    return img

def slide_conclusions():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    header(d, "结论速览：五个维度的可行性", "基于官方文档 + 真实样片元数据 + 本机端到端实测", "01")
    rows = [
        ("SDK 自动采集", "有条件可行", "Mini 3 / 3 Pro / 4 Pro 支持 MSDK v5（仅 Android；Mini 4 Pro 需 RC-N2）", ACCENT2),
        ("官方 Terra 3DGS", "可行但本机不可跑", "Terra v5+ 支持可见光 3DGS；要求 32GB 内存（本机 16GB 仅文档级验证）", ACCENT2),
        ("开源 3DGS 链路", "可行（欠训练）", "纯 PyTorch 端到端跑通：109,376 splat，峰值显存 1.15GB", ACCENT),
        ("UE5.8 渲染集成", "可行但需适配", "Italink 插件移植 5.8.4 编译成功；真实 PLY 可显示，Niagara 尺度待修", ACCENT),
        ("端到端工程化", "PoC 级可行", "采集 → 3DGS → PLY → UE 全链路复现，含 30/90/180 天路线", ACCENT),
    ]
    y = 210
    for name, verdict, detail, color in rows:
        d.rounded_rectangle([72, y, 1848, y + 128], radius=16, fill=(255, 255, 255, 12), outline=(80, 100, 130, 90), width=1)
        d.text((104, y + 26), name, font=font(36, True), fill=(255, 255, 255))
        d.text((460, y + 22), verdict, font=font(30, True), fill=color)
        d.text((104, y + 78), detail, font=font(25), fill=MUTED)
        y += 148
    footer(d)
    return img

def slide_pipeline():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    header(d, "技术链路：从航拍采集到 UE5 渲染", "采集 → 位姿/元数据 → 3DGS 训练 → PLY 导出 → UE5 集成", "02")
    place_image(img, os.path.join(ROOT, "report", "figures", "fig1_pipeline.png"), (90, 200, 1830, 920))
    d.text((110, 934), "关键自检：UE <-> COLMAP 坐标换算重投影误差 ≤ 1.26e-12 px ｜ c2w 闭环误差 4.5e-13", font=font(25), fill=MUTED)
    footer(d)
    return img

def slide_coords():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    header(d, "坐标与数据一致性：被实测钉死的环节", "UE 左手中标（X 前 / Y 右 / Z 上，cm）  <->  COLMAP 右手中标", "03")
    place_image(img, os.path.join(ROOT, "report", "figures", "fig3_coordinates.png"), (90, 200, 1250, 900))
    bullets = [
        "重投影自检：max 1.26e-12 px",
        "c2w 闭环：4.5e-13",
        "合成数据 175 训练 + 15 验证",
        "内参 fx=fy=1148.34（Mini 4 Pro）",
        "位姿先验：GPS + 云台角",
    ]
    bullet_block(d, bullets, 1300, 240, 540, size=28, gap=76)
    footer(d)
    return img

def slide_dataset():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    header(d, "合成航拍数据集：UE5.8 程序化园区", "175 训练 + 15 验证 @1600×1200，805 actors，Mini 4 Pro 相机参数", "04")
    imgs = ["0001.png", "0002.png", "0003.png", "0004.png"]
    xs = [90, 1005]
    ys = [210, 590]
    for i, name in enumerate(imgs):
        x = xs[i % 2]; y = ys[i // 2]
        place_image(img, os.path.join(ROOT, "data", "synthetic", "capture", "images", name), (x, y, x + 890, y + 350), radius=12)
    d.text((90, 972), "数据契约：metadata.json（c2w / 内参 / GPS / 云台）与 3DGS 训练脚本完全对齐", font=font(25), fill=MUTED)
    footer(d)
    return img

def slide_train():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    header(d, "3DGS 训练：链路自洽，质量受算力限制", "自研 pure-PyTorch 可微光栅化器（gsplat CUDA JIT 在本环境失败后切换）", "05")
    gt = os.path.join(ROOT, "data", "trained", "capture", "run1", "renders", "gt_000.png")
    rd = os.path.join(ROOT, "data", "trained", "capture", "run1", "renders", "val_000.png")
    place_image(img, gt, (80, 210, 930, 690)); place_image(img, rd, (990, 210, 1840, 690))
    d.text((80, 716), "Ground Truth（UE 渲染）", font=font(26, True), fill=MUTED)
    d.text((990, 716), "3DGS 渲染（3000 iter，欠训练）", font=font(26, True), fill=MUTED)
    stats = [
        ("109,376", "splat 数"), ("3000", "迭代"), ("1.15 GB", "峰值显存"), ("13.28", "val PSNR"),
    ]
    x = 80
    for v, k in stats:
        d.text((x, 790), v, font=font(46, True), fill=ACCENT)
        d.text((x, 852), k, font=font(24), fill=MUTED)
        x += 430
    d.text((80, 916), "链路正确性证据：5 帧子集 PSNR 22.27（每视图 ~120 次更新）→ 全量欠训练（每视图 ~25 次）", font=font(24), fill=(200, 175, 140))
    footer(d)
    return img

def slide_ue():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    header(d, "UE5.8 集成：真实训练 PLY 在引擎中显示", "Italink 插件移植到 UE 5.8.4（编译 147.7s）；自研 C++ PLY 解析器（按属性名索引）", "06")
    place_image(img, os.path.join(ROOT, "ue5", "results", "final_v2", "ue_pathb_4views_grid_v2.png"), (60, 200, 1860, 900), radius=10)
    d.text((80, 930), "Path B：真实 PLY（109,376 splat）点云预览，鲁棒取景（去离群点后相机距离 160m）", font=font(24), fill=MUTED)
    footer(d)
    return img

def slide_perf():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    header(d, "渲染验证与性能（4 核限载，1280×720）", "UE Path B 点云预览 vs CPU 参考投影（同一机位、同一 PLY）", "07")
    place_image(img, os.path.join(ROOT, "ue5", "results", "final_v2", "comparison_ue_vs_reference_v2.png"), (60, 200, 1860, 690), radius=10)
    stats = [
        ("30.8", "fps（109k 点云）"), ("28.2 ms", "PLY 解析"), ("23.5 ms", "SetPoints"),
        ("72,053", "屏内 splat"), ("95.4/104.7", "Niagara 吞吐 50k/200k"),
    ]
    x = 70
    for v, k in stats:
        d.text((x, 740), v, font=font(42, True), fill=ACCENT)
        d.text((x, 800), k, font=font(22), fill=MUTED)
        x += 360
    d.text((70, 880), "注：Niagara splat 渲染已打通但存在尺度失配（×100），Path B 为当前可交付的可靠路径", font=font(23), fill=(215, 175, 140))
    footer(d)
    return img

def slide_roadmap():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    header(d, "结论与路线图", "PoC 级可行；生产需真机验证 + 更强 GPU + 插件适配", "08")
    place_image(img, os.path.join(ROOT, "report", "figures", "fig5_sdk_tiers.png"), (70, 200, 1180, 900), radius=10)
    phases = [
        ("30 天", "PoC：Mini 4 Pro 实拍 1 公顷 → 3DGS → UE5 demo"),
        ("90 天", "试点：3–5 场景、SOP、质量与效率基线"),
        ("180 天", "工程化:插件选型/授权、自动化、质量评估"),
    ]
    y = 250
    for ph, txt in phases:
        d.rounded_rectangle([1230, y, 1850, y + 150], radius=14, fill=(255, 255, 255, 12), outline=(80, 100, 130, 90))
        d.text((1258, y + 22), ph, font=font(34, True), fill=ACCENT2)
        for j, ln in enumerate(wrap(d, txt, font(24), 540)):
            d.text((1258, y + 74 + j * 34), ln, font=font(24), fill=TEXT)
        y += 180
    footer(d)
    return img

def slide_llm():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    header(d, "额外验证：LLM 工具调用调度无人机", "自然语言 → 工具调用 → 安全层 → 仿真/虚拟无人机 → 航拍图 → 3DGS", "09")
    path = os.path.join(ROOT, "llm_drone", "ue5_mission", "results", "contact_sheet_p1.png")
    if not place_image(img, path, (70, 200, 1150, 900), radius=10):
        place_image(img, os.path.join(ROOT, "ue5", "results", "final_v2", "pathb_real_ply_4view_grid.png"), (70, 200, 1150, 900))
    bullets = [
        "真实 LLM 完成多步任务：6 次工具调用、20 张照片",
        "安全层硬约束：200m/禁飞区请求被拒绝且不可绕过",
        "确定性 workflow 兜底：30 张照片一次跑通",
        "闭环：LLM 规划 → UE5 虚拟拍摄 91 帧 → 3DGS",
    ]
    bullet_block(d, bullets, 1200, 260, 620, size=26, gap=96, mark_color=ACCENT2)
    footer(d)
    return img

def slide_end():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    d.text((120, 210), "谢谢", font=font(110, True), fill=TEXT)
    d.text((124, 350), "交付物与复现入口", font=font(46), fill=ACCENT)
    d.rectangle([124, 422, 124 + 140, 428], fill=ACCENT2 + (255,))
    items = [
        "可行性报告（41,186 字，含 5 图）  report/DJI_Mini_UE5_3DGS_可行性验证报告.md",
        "决策层简报（13 页 PPTX）        report/DJI_Mini_UE5_3DGS_可行性验证_简报.pptx",
        "3DGS 流水线（pure-PyTorch）      pipeline/  ·  训练产物 data/trained/capture/run1/",
        "UE5.8 工程与渲染证据             ue5/  ·  results/final_v2/（4 视角 + 性能）",
        "合成航拍数据集（175+15 帧）      data/synthetic/",
        "LLM 调度无人机 Phase-1          llm_drone/docs/FINAL_PHASE1_SUMMARY.md",
    ]
    f = font(25)
    for i, it in enumerate(items):
        d.text((128, 470 + i * 62), it, font=f, fill=TEXT if i % 2 == 0 else (205, 218, 235))
    d.text((124, 860), "全部数据与结论可在本机复现（shared/verify_all.ps1 → PASS=16/0/0）", font=font(26), fill=MUTED)
    footer(d)
    return img

SLIDES = [
    ("cover", slide_cover, 6.0),
    ("conclusions", slide_conclusions, 10.0),
    ("pipeline", slide_pipeline, 8.0),
    ("coords", slide_coords, 8.0),
    ("dataset", slide_dataset, 7.0),
    ("train", slide_train, 10.0),
    ("ue", slide_ue, 8.0),
    ("perf", slide_perf, 8.0),
    ("roadmap", slide_roadmap, 9.0),
    ("llm", slide_llm, 8.0),
    ("end", slide_end, 6.0),
]

def main():
    os.makedirs(os.path.dirname(OUT_MP4), exist_ok=True)
    print("rendering slides...", flush=True)
    rendered = []
    for name, fn, dur in SLIDES:
        im = fn()
        rendered.append((name, im, dur))
        print("  slide", name, "ok", flush=True)
    poster = rendered[0][1]
    poster.save(OUT_POSTER, quality=95)
    print("poster saved", OUT_POSTER, flush=True)

    if not FFMPEG:
        print("no ffmpeg, abort"); return 2
    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-vcodec", "rawvideo", "-s", "%dx%d" % (W, H),
           "-pix_fmt", "rgb24", "-r", str(FPS), "-i", "-",
           "-an", "-vcodec", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "20", "-preset", "medium", "-movflags", "+faststart", OUT_MP4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    trans = int(0.5 * FPS)   # 15 帧转场
    total = 0
    prev = None
    def emit(frame):
        nonlocal total
        proc.stdin.write(frame.tobytes())
        total += 1
    for idx, (name, im, dur) in enumerate(rendered):
        hold = int(dur * FPS)
        if idx == 0:
            for _ in range(hold):
                emit(im)
            prev = im
        else:
            for k in range(trans):
                a = (k + 1) / trans
                emit(Image.blend(prev, im, a))
            for _ in range(hold - trans):
                emit(im)
            prev = im
        print("  encoded", name, flush=True)
    proc.stdin.close(); proc.wait()
    print("done: %s frames=%d dur=%.1fs" % (OUT_MP4, total, total / FPS), flush=True)
    print("size", os.path.getsize(OUT_MP4), flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
