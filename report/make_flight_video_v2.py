# -*- coding: utf-8 -*-
"""make_flight_video_v2.py -- 44s 演示片 v2：标题卡 + LLM 控制台 + 3D 飞行(HUD/小地图/闪光) + 3DGS 结果揭晓 + 结束卡，带中文旁白与音效。"""
import json, math, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs"
RAW = os.path.join(ROOT, "report", "flight_raw")
PLAN = os.path.join(ROOT, "report", "flight_plan.json")
AUDIO = os.path.join(ROOT, "report", "audio", "narration_mix.wav")
OUT = os.path.join(ROOT, "report", "DJI_Mini_UE5_3DGS_飞行演示_v2.mp4")
POSTER = os.path.join(ROOT, "report", "DJI_Mini_UE5_3DGS_飞行演示_v2_封面.png")
FONT = r"C:\Windows\Fonts\msyh.ttc"
FONTB = r"C:\Windows\Fonts\msyhbd.ttc"
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = "ffmpeg"

W, H, FPS = 1280, 720, 30
TITLE_S, CONSOLE_S, FLIGHT_S, RESULT_S, END_S = 3.0, 7.2, 18.0, 7.8, 5.5
N_TITLE, N_CONSOLE = int(TITLE_S * FPS), int(CONSOLE_S * FPS)
N_RESULT, N_END = int(RESULT_S * FPS), int(END_S * FPS)
ACCENT = (79, 209, 197); ACCENT2 = (245, 158, 66); RED = (239, 68, 68)
TEXT = (236, 243, 249); MUTED = (150, 168, 188)

def font(sz, bold=False):
    return ImageFont.truetype(FONTB if bold else FONT, sz)

with open(PLAN, encoding="utf-8") as fh:
    PLAN_D = json.load(fh)
N = PLAN_D["frames"]; POSES = PLAN_D["poses"]; FILES = PLAN_D["files"]
FW, FH = PLAN_D["width"], PLAN_D["height"]

import numpy as np
_g = np.zeros((H, W, 3), dtype="float32")
_a = np.array([9, 14, 26], dtype="float32"); _b = np.array([16, 25, 42], dtype="float32")
for y in range(H):
    _g[y, :, :] = _a * (1 - y / (H - 1)) + _b * (y / (H - 1))
BG = Image.fromarray(_g.astype("uint8"), "RGB")

def load_frame(i):
    im = Image.open(os.path.join(RAW, FILES[i])).convert("RGB")
    ch = int(FW * 9 / 16); top = (FH - ch) // 2
    return im.crop((0, top, FW, top + ch)).resize((W, H), Image.LANCZOS)

def rr(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)

def wrap(d, text, f, maxw):
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) <= maxw:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur: lines.append(cur)
    return lines

# ---------------------------------------------------------------- 标题卡
def title_slide():
    img = BG.copy(); d = ImageDraw.Draw(img)
    d.text((70, 62), "GAIA  ·  dji_ue5_3dgs", font=font(18, True), fill=(120, 145, 170))
    d.text((66, 150), "DJI Mini × UE5 3DGS", font=font(84, True), fill=TEXT)
    d.text((70, 268), "LLM 指令  →  无人机 3D 飞行采集  →  3DGS 重建", font=font(32), fill=ACCENT)
    d.rectangle([70, 330, 70 + 130, 335], fill=ACCENT2)
    # 徽标
    rr(d, [70, 372, 330, 414], 21, fill=(245, 158, 66, 40), outline=(245, 158, 66), width=1)
    d.text((96, 380), "仿真 + 虚拟环境验证", font=font(20, True), fill=(255, 210, 160))
    lines = [
        "自然语言下指令，大模型规划航线并调用工具",
        "无人机在 UE5 园区中自动飞行、逐点拍照",
        "照片带 GPS / 云台 / 真值位姿，直接进入 3DGS",
    ]
    for k, ln in enumerate(lines):
        d.text((72, 462 + k * 42), "—  " + ln, font=font(22), fill=(200, 216, 232))
    d.text((70, 640), "2026-11-08  ·  本机实测：RTX 5060 8GB / UE 5.8.4 / 4 核限载", font=font(17), fill=MUTED)
    d.text((W - 70, 640), "演示视频 v2", font=font(17, True), fill=(120, 145, 170), anchor="ra")
    return img

# ---------------------------------------------------------------- LLM 控制台
CMD = "把园区做一次 3DGS 网格航拍，航高 40 米，云台垂直向下，重叠 75%"
TOOLS = [
    ("plan_capture_mission", "pattern=grid  altitude=40m  overlap=75%"),
    ("takeoff", "altitude_m=5  confirm=true"),
    ("goto_waypoints", "plan_id=plan-65f197f4d1  confirm=true"),
    ("return_to_home", "auto"),
]
STATUS = ["正在解析意图…", "任务规划完成，等待确认…", "安全校验通过，无人机起飞…", "进入自动航点任务…", "飞行中，逐点拍照…"]

def console(t, chars, stage):
    img = BG.copy(); d = ImageDraw.Draw(img)
    d.text((70, 52), "LLM 发出指令", font=font(34, True), fill=TEXT)
    d.text((70, 96), "自然语言 → 工具调用 → 安全校验 → 无人机执行", font=font(19), fill=MUTED)
    d.rectangle([70, 132, 140, 135], fill=ACCENT)
    rr(d, [60, 166, W - 60, 590], 14, fill=(9, 14, 26), outline=(58, 76, 102), width=1)
    d.text((86, 182), "●   ●   ●", font=font(14), fill=(90, 100, 115))
    d.text((W - 250, 182), "LLM CONTROL CONSOLE", font=font(13, True), fill=(90, 110, 135))
    y = 226
    d.text((86, y), "用户", font=font(19, True), fill=ACCENT2)
    shown = CMD[:chars]
    for j, ln in enumerate(wrap(d, shown, font(20), W - 300)):
        d.text((156, y + j * 32), ln, font=font(20), fill=TEXT)
    if t < 2.0 and int(t * 4) % 2 == 0:
        xx = 156 + d.textlength(shown, font=font(20)) + 3
        d.rectangle([xx, y + 4, xx + 9, y + 28], fill=ACCENT)
    ty = 318
    d.text((86, ty - 6), "系统", font=font(19, True), fill=ACCENT)
    for i, (name, args) in enumerate(TOOLS):
        if i >= stage: break
        done = i < stage - 1
        mark = "[OK]" if done else "[..]"
        d.text((156, ty + i * 44), mark, font=font(17, True), fill=(ACCENT if done else ACCENT2))
        d.text((214, ty + i * 44), name + "(", font=font(19, True), fill=TEXT)
        d.text((214 + d.textlength(name + "(", font=font(19, True)), ty + i * 44), args + ")", font=font(17), fill=MUTED)
    d.text((86, 540), "> " + STATUS[min(stage, len(STATUS) - 1)], font=font(19, True), fill=(170, 200, 220))
    for k in range(5):
        d.ellipse([86 + k * 30, 640, 86 + k * 30 + 12, 652], fill=(ACCENT if k <= stage else (70, 84, 104)))
    return img

# ---------------------------------------------------------------- 飞行 HUD + 小地图
_xs = [p["loc_cm"][0] for p in POSES]; _ys = [p["loc_cm"][1] for p in POSES]
_xmin, _xmax = min(_xs) - 200, max(_xs) + 200
_ymin, _ymax = min(_ys) - 200, max(_ys) + 200
MAP = (W - 226, 64, W - 26, 264)   # x0,y0,x1,y1

def map_xy(x, y):
    mx0, my0, mx1, my1 = MAP
    w, h = mx1 - mx0 - 20, my1 - my0 - 20
    sx = w / (_xmax - _xmin); sy = h / (_ymax - _ymin)
    s = min(sx, sy)
    cx = (x - (_xmin + _xmax) / 2) * s + (mx0 + mx1) / 2
    cy = (y - (_ymin + _ymax) / 2) * s + (my0 + my1) / 2
    return cx, cy

def draw_map(d, i):
    mx0, my0, mx1, my1 = MAP
    rr(d, [mx0, my0, mx1, my1], 10, fill=(0, 0, 0, 130), outline=(90, 110, 140, 160))
    d.text((mx0 + 10, my0 + 6), "ROUTE", font=font(11, True), fill=(140, 165, 190, 255))
    pts = [map_xy(p["loc_cm"][0], p["loc_cm"][1]) for p in POSES]
    for k in range(len(pts) - 1):
        col = (79, 209, 197, 220) if k <= i else (110, 125, 148, 110)
        d.line([pts[k], pts[k + 1]], fill=col, width=2)
    # 已拍点
    for k in range(0, i + 1, max(1, i // 12)):
        x, y = pts[k]
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(245, 158, 66, 230))
    x, y = pts[i]
    d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(255, 255, 255, 255), outline=(0, 0, 0, 160))
    # 朝向
    yaw = math.radians(POSES[i]["yaw"])
    d.line([(x, y), (x + 14 * math.cos(yaw), y + 14 * math.sin(yaw))], fill=(255, 255, 255, 220), width=2)
    d.text((mx1 - 22, my0 + 6), "N", font=font(11, True), fill=(200, 215, 232, 230))

def draw_map_layer(i):
    mx0, my0, mx1, my1 = MAP
    mw, mh = mx1 - mx0, my1 - my0
    layer = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, mw - 1, mh - 1], radius=10, fill=(0, 0, 0, 135), outline=(90, 110, 140, 170))
    d.text((10, 6), "ROUTE", font=font(11, True), fill=(140, 165, 190, 255))
    def lxy(x, y):
        w, h = mw - 20, mh - 20
        s = min(w / (_xmax - _xmin), h / (_ymax - _ymin))
        return ((x - (_xmin + _xmax) / 2) * s + mw / 2,
                (y - (_ymin + _ymax) / 2) * s + mh / 2)
    pts = [lxy(p["loc_cm"][0], p["loc_cm"][1]) for p in POSES]
    for k in range(len(pts) - 1):
        col = (79, 209, 197, 230) if k <= i else (120, 135, 158, 120)
        d.line([pts[k], pts[k + 1]], fill=col, width=2)
    for k in range(0, i + 1, max(1, i // 14)):
        x, y = pts[k]
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(245, 158, 66, 240))
    x, y = pts[i]
    d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(255, 255, 255, 255), outline=(0, 0, 0, 180))
    yaw = math.radians(POSES[i]["yaw"])
    d.line([(x, y), (x + 13 * math.cos(yaw), y + 13 * math.sin(yaw))], fill=(255, 255, 255, 230), width=2)
    d.text((mw - 20, 6), "N", font=font(11, True), fill=(200, 215, 232, 235))
    return layer

def hud(i):
    img = load_frame(i).copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    d.rectangle([0, 0, W, 76], fill=(0, 0, 0, 100))
    d.rectangle([0, H - 32, W, H], fill=(0, 0, 0, 70))
    p = POSES[i]
    alt = p["loc_cm"][2] / 100.0; spd = p["speed_mps"]
    hdg = (p["yaw"] + 360.0) % 360.0
    j = min(i + 1, N - 1); vs = (POSES[j]["loc_cm"][2] - p["loc_cm"][2]) * FPS / 100.0
    batt = 100.0 - 11.0 * (i / float(N - 1))
    prog = i / float(N - 1); wp = min(30, int(prog * 30) + 1)
    # 顶部
    d.ellipse([26, 22, 40, 36], fill=RED + (255,))
    d.text((50, 20), "REC", font=font(17, True), fill=(255, 255, 255, 255))
    d.text((100, 20), "AUTO MISSION · 3DGS GRID", font=font(16, True), fill=(230, 238, 248, 255))
    d.text((26, 46), "GPS 24 SAT  ·  FIX 3D  ·  LLM: 园区网格航拍 40 m / 重叠 75%", font=font(13), fill=(185, 205, 225, 235))
    d.text((W // 2, 44), "UE5 仿真 · 非真机", font=font(13, True), fill=(240, 180, 110, 240), anchor="ma")
    rr(d, [W - 250, 14, W - 26, 46], 8, fill=(0, 0, 0, 120), outline=(90, 110, 140, 160))
    d.text((W - 238, 21), "BAT %d%%" % int(batt), font=font(14, True), fill=(220, 235, 245, 255))
    d.rectangle([W - 176, 24, W - 176 + int(140 * batt / 100), 36], fill=(ACCENT if batt > 40 else ACCENT2) + (255,))
    # 角标
    L = 24
    for (x, y, sx, sy) in [(20, 76, 1, 1), (W - 20, 76, -1, 1), (20, H - 20, 1, -1), (W - 20, H - 20, -1, -1)]:
        d.line([(x, y), (x + sx * L, y)], fill=(255, 255, 255, 80), width=2)
        d.line([(x, y), (x, y + sy * L)], fill=(255, 255, 255, 80), width=2)
    # 遥测
    box = [26, H - 160, 320, H - 26]
    rr(d, box, 10, fill=(0, 0, 0, 135), outline=(90, 110, 140, 150))
    d.text((42, box[1] + 10), "TELEMETRY", font=font(11, True), fill=(140, 165, 190, 255))
    for k, (k1, v1) in enumerate([("ALT", "%5.1f m" % alt), ("SPD", "%4.1f m/s" % spd),
                                  ("V/S", "%+4.1f m/s" % vs), ("HDG", "%03d°" % int(hdg))]):
        yy = box[1] + 32 + k * 26
        d.text((42, yy), k1, font=font(12, True), fill=(130, 155, 180, 255))
        d.text((104, yy - 3), v1, font=font(19, True), fill=(235, 245, 250, 255))
    d.text((42, box[3] - 20), "%.6f, %.6f" % (p["gps"]["lat"], p["gps"]["lon"]), font=font(10), fill=(150, 175, 195, 230))
    # 进度
    bx = W // 2 - 240
    rr(d, [bx, H - 90, bx + 480, H - 26], 9, fill=(0, 0, 0, 130), outline=(90, 110, 140, 150))
    d.text((bx + 14, H - 82), "MISSION PROGRESS", font=font(11, True), fill=(140, 165, 190, 255))
    d.text((bx + 466, H - 82), "%d%%" % int(prog * 100), font=font(13, True), fill=(235, 245, 250, 255), anchor="ra")
    d.rounded_rectangle([bx + 14, H - 58, bx + 466, H - 46], radius=5, fill=(40, 52, 70, 220))
    d.rounded_rectangle([bx + 14, H - 58, bx + 14 + int(452 * prog), H - 46], radius=5, fill=ACCENT + (255,))
    d.text((bx + 14, H - 40), "航点 %d/30  ·  照片 %d" % (wp, wp), font=font(11), fill=(180, 200, 220, 235))
    # 工具链
    tx = W - 300
    rr(d, [tx, H - 146, W - 26, H - 26], 9, fill=(0, 0, 0, 130), outline=(90, 110, 140, 150))
    d.text((tx + 12, H - 138), "LLM TOOL CHAIN", font=font(11, True), fill=(140, 165, 190, 255))
    tools = [("plan", True), ("takeoff", True), ("goto", i < N - 20), ("rth", i >= N - 20)]
    for k, (nm, st) in enumerate(tools):
        d.text((tx + 12, H - 116 + k * 22), ("OK  " if st else "--  ") + nm, font=font(12, True),
               fill=(ACCENT if st else (110, 125, 145)) + (255,))
    # 小地图（独立图层，裁剪在面板内）
    ov.alpha_composite(draw_map_layer(i), (MAP[0], MAP[1]))
    # 拍照闪光：连续轻闪 + 30/60/90% 三次强反馈 + 计数
    ph_now = int(prog * 30); ph_prev = int(((i - 1) / float(N - 1)) * 30) if i > 0 else 0
    if ph_now > ph_prev:
        d.rectangle([0, 0, W, H], fill=(255, 255, 255, 45))
    for pnum in (162, 323, 485):
        if abs(i - pnum) <= 2:
            d.rectangle([0, 0, W, H], fill=(255, 255, 255, 95))
            d.text((W // 2, H // 2 + 60), "PHOTO %d / 30" % ph_now, font=font(28, True),
                   fill=(255, 255, 255, 255), anchor="ma")
    # 中心十字
    cx, cy = W // 2, H // 2
    for a, b in [((cx - 15, cy), (cx - 5, cy)), ((cx + 5, cy), (cx + 15, cy)),
                 ((cx, cy - 15), (cx, cy - 5)), ((cx, cy + 5), (cx, cy + 15))]:
        d.line([a, b], fill=(255, 255, 255, 100), width=1)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

# ---------------------------------------------------------------- 结果揭晓
def results_base():
    img = BG.copy(); d = ImageDraw.Draw(img)
    d.text((60, 44), "照片  →  3DGS 重建  →  UE5 实时浏览", font=font(38, True), fill=TEXT)
    d.text((62, 96), "真实 LLM 任务：91 帧航拍 → 3DGS 训练 → UE5 加载 PLY", font=font(19), fill=MUTED)
    d.rectangle([62, 132, 172, 135], fill=ACCENT)
    def paste(path, box, label, color=TEXT):
        im = Image.open(path).convert("RGB")
        bw, bh = box[2] - box[0], box[3] - box[1]
        s = min(bw / im.width, bh / im.height)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
        x = box[0] + (bw - im.width) // 2; y = box[1] + (bh - im.height) // 2
        img.paste(im, (x, y))
        d.rectangle([x, y, x + im.width, y + im.height], outline=(90, 110, 140), width=2)
        d.text((x, y + im.height + 8), label, font=font(16, True), fill=color)
    try:
        paste(os.path.join(ROOT, "data", "trained", "capture", "run1", "renders", "gt_000.png"),
              (60, 180, 470, 500), "UE5 渲染（GT）", (200, 220, 235))
        paste(os.path.join(ROOT, "data", "trained", "capture", "run1", "renders", "val_000.png"),
              (600, 180, 1010, 500), "3DGS 重建（3000 iter · 欠训练）", (245, 200, 150))
    except Exception:
        pass
    d.text((500, 300), "→", font=font(64, True), fill=ACCENT)
    d.text((500, 380), "训练", font=font(18, True), fill=MUTED)
    # 右侧 UE 面板
    rr(d, [1030, 170, W - 26, 520], 12, fill=(0, 0, 0, 120), outline=(90, 110, 140), width=1)
    d.text((1046, 182), "UE5.8 · 真实 PLY", font=font(17, True), fill=TEXT)
    d.text((1046, 206), "109,376 splat", font=font(13), fill=MUTED)
    p = os.path.join(ROOT, "ue5", "results", "final_v2", "ue_pathb_4views_grid_v2.png")
    if os.path.exists(p):
        im = Image.open(p).convert("RGB")
        iw = W - 26 - 1046; ih = int(im.height * iw / im.width)
        im = im.resize((iw, min(ih, 200)), Image.LANCZOS)
        img.paste(im, (1046, 232))
        d.rectangle([1046, 232, 1046 + iw, 232 + min(ih, 200)], outline=(90, 110, 140), width=1)
    d.text((1046, 452), "插件移植编译通过 · 30.8 fps", font=font(13), fill=MUTED)
    # 底部指标
    stats = [("109,376", "splat 数"), ("3000", "迭代"), ("1.15 GB", "峰值显存"), ("13.28", "val PSNR")]
    x = 60
    for v, k in stats:
        d.text((x, 556), v, font=font(34, True), fill=ACCENT)
        d.text((x, 598), k, font=font(15), fill=MUTED)
        x += 235
    d.text((60, 648), "质量说明：3000 iter 欠训练，画质受算力/温度限制；链路与元数据契约已跑通", font=font(15), fill=(215, 185, 150))
    return img

def end_card():
    img = BG.copy(); d = ImageDraw.Draw(img)
    d.text((70, 90), "下一步：真机验证", font=font(64, True), fill=TEXT)
    d.rectangle([72, 210, 72 + 120, 216], fill=ACCENT)
    items = [
        "设备：DJI Mini 4 Pro + RC-N2 + Android 手机（MSDK v5）",
        "流程：空域报备 → 拆桨地面测试 → 悬停/起降 → 网格采集",
        "数据：真机照片 EXIF/XMP → COLMAP → 同一 3DGS 流水线",
        "已交付：可行性报告 / 13 页 PPT / 数据集 / 流水线 / 演示视频",
    ]
    for k, it in enumerate(items):
        d.text((74, 260 + k * 56), "—  " + it, font=font(24), fill=(205, 220, 235))
    d.text((70, 512), "链路已跑通；重建质量与真机安全待验证。", font=font(22, True), fill=(240, 180, 110))
    d.text((70, 560), "仿真与虚拟环境验证 · 2026-11-08", font=font(20, True), fill=ACCENT)
    d.text((70, 620), "DJI Mini × UE5 3DGS 技术可行性验证 · 演示 v2", font=font(16), fill=MUTED)
    return img

# ---------------------------------------------------------------- 组装
def main():
    if not os.path.isdir(RAW) or len(FILES) < N:
        print("frames missing"); return 2
    frames = []
    # 标题（淡入）
    tslide = title_slide()
    for k in range(N_TITLE):
        a = min(1.0, k / 12.0)
        frames.append(Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), tslide, a))
    # 控制台
    for k in range(N_CONSOLE):
        t = k / float(FPS)
        chars = int(min(1.0, t / 1.3) * len(CMD))
        stage = 0
        if t > 1.9: stage = 1
        if t > 2.4: stage = 2
        if t > 2.9: stage = 3
        if t > 3.5: stage = 4
        if t > 4.6: stage = 5
        frames.append(console(t, chars, stage))
    # 飞行（首尾淡入淡出）
    black = Image.new("RGB", (W, H), (0, 0, 0))
    first = hud(0)
    for k in range(10):
        frames.append(Image.blend(console(N_CONSOLE / FPS - 0.01, len(CMD), 5), first, (k + 1) / 10.0))
    for i in range(N):
        if i % 60 == 0:
            print("hud %d/%d" % (i, N), flush=True)
        frames.append(hud(i))
    last = hud(N - 1)
    # 结果
    rb = results_base()
    for k in range(16):
        frames.append(Image.blend(last, rb, (k + 1) / 16.0))
    for k in range(N_RESULT - 16):
        frames.append(rb)
    # 结尾
    ec = end_card()
    for k in range(16):
        frames.append(Image.blend(rb, ec, (k + 1) / 16.0))
    for k in range(N_END - 16):
        frames.append(ec)
    total = len(frames)
    print("frames:", total, "dur:", round(total / FPS, 2), "s", flush=True)
    silent = os.path.join(ROOT, "report", "_flight_v2_silent.mp4")
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-vcodec", "rawvideo",
           "-s", "%dx%d" % (W, H), "-pix_fmt", "rgb24", "-r", str(FPS), "-i", "-",
           "-an", "-vcodec", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium", silent]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close(); proc.wait()
    print("silent ok", os.path.getsize(silent))
    # 混音
    cmd2 = [FFMPEG, "-y", "-loglevel", "error", "-i", silent, "-i", AUDIO,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", OUT]
    subprocess.run(cmd2, check=True)
    print("saved", OUT, os.path.getsize(OUT))
    # 封面（飞行中带小地图）
    hud(170).save(POSTER, quality=95)
    print("poster", POSTER)
    try:
        os.remove(silent)
    except OSError:
        pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
