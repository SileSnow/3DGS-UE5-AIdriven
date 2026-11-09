# -*- coding: utf-8 -*-
"""make_flight_video.py -- 把 UE 渲染的连续飞行帧合成"LLM 指令 -> 无人机 3D 飞行"演示视频。

输入: report/flight_raw/f0001..f0540.png + report/flight_plan.json
输出: report/DJI_Mini_UE5_3DGS_飞行演示.mp4 (1280x720, 30fps)
      report/DJI_Mini_UE5_3DGS_飞行演示_封面.png
结构: 0-5.5s LLM 控制台(打字机 + 工具调用) -> 5.5-23.5s 3D 飞行(HUD)
      -> 23.5-29s 任务完成(照片墙+结论)
"""
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs"
RAW = os.path.join(ROOT, "report", "flight_raw")
PLAN = os.path.join(ROOT, "report", "flight_plan.json")
OUT = os.path.join(ROOT, "report", "DJI_Mini_UE5_3DGS_飞行演示.mp4")
POSTER = os.path.join(ROOT, "report", "DJI_Mini_UE5_3DGS_飞行演示_封面.png")
FONT = r"C:\Windows\Fonts\msyh.ttc"
FONTB = r"C:\Windows\Fonts\msyhbd.ttc"
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = "ffmpeg"

W, H = 1280, 720
FPS = 30
INTRO_S = 5.5
OUTRO_S = 5.5
ACCENT = (79, 209, 197)
ACCENT2 = (245, 158, 66)
RED = (239, 68, 68)
TEXT = (235, 242, 249)
MUTED = (150, 168, 188)

def font(sz, bold=False):
    return ImageFont.truetype(FONTB if bold else FONT, sz)

def fmt_latlon(gps):
    return "%.6f, %.6f" % (gps["lat"], gps["lon"])

def gradient_bg():
    import numpy as np
    g = np.zeros((H, W, 3), dtype="float32")
    a = np.array([8, 13, 24], dtype="float32")
    b = np.array([14, 22, 38], dtype="float32")
    for y in range(H):
        g[y, :, :] = a * (1 - y / (H - 1)) + b * (y / (H - 1))
    return Image.fromarray(g.astype("uint8"), "RGB")

BG = gradient_bg()

def rounded(d, box, radius, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

# ---------------------------------------------------------------- 素材
with open(PLAN, encoding="utf-8") as fh:
    PLAN_D = json.load(fh)
N = PLAN_D["frames"]
POSES = PLAN_D["poses"]
FILES = PLAN_D["files"]
FRAME_W, FRAME_H = PLAN_D["width"], PLAN_D["height"]

def load_frame(i):
    p = os.path.join(RAW, FILES[i])
    im = Image.open(p).convert("RGB")
    # 4:3 -> 16:9 中裁 + 缩放到 1280x720
    ch = int(FRAME_W * 9 / 16)
    top = (FRAME_H - ch) // 2
    im = im.crop((0, top, FRAME_W, top + ch)).resize((W, H), Image.LANCZOS)
    return im

# ---------------------------------------------------------------- 开场：LLM 控制台
CMD = "把园区做一次 3DGS 网格航拍，航高 40 米，云台垂直向下，重叠 75%"
TOOLS = [
    ("plan_capture_mission", "pattern=grid  altitude=40m  overlap=75%", True),
    ("takeoff", "altitude_m=5  confirm=true", True),
    ("goto_waypoints", "plan_id=plan-65f197f4d1  confirm=true", True),
    ("return_to_home", "auto", True),
]

def draw_console(t, cmd_chars, tool_stage, show_cursor=False):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    # 标题
    d.text((70, 54), "LLM  →  DRONE", font=font(34, True), fill=TEXT)
    d.text((70, 96), "自然语言指令 → 工具调用 → 安全校验 → 无人机执行", font=font(20), fill=MUTED)
    d.rectangle([70, 132, 70 + 70, 135], fill=ACCENT)
    # 终端面板
    rounded(d, [62, 168, W - 62, 600], 14, fill=(10, 16, 28), outline=(60, 78, 104), width=1)
    d.text((88, 186), "●  ●  ●", font=font(16), fill=(90, 100, 115))
    d.text((W - 250, 186), "LLM CONTROL CONSOLE", font=font(14, True), fill=(90, 110, 135))
    # 用户指令（打字机）
    y = 232
    d.text((88, y), "用户", font=font(20, True), fill=ACCENT2)
    shown = CMD[:cmd_chars]
    for j, line in enumerate(wrap_lines(d, shown, font(21), W - 300)):
        d.text((158, y + j * 34), line, font=font(21), fill=TEXT)
    if show_cursor and int(t * 4) % 2 == 0:
        d.rectangle([158 + d.textlength(shown, font=font(21)) + 3, y + 4,
                     158 + d.textlength(shown, font=font(21)) + 13, y + 30], fill=ACCENT)
    # 工具调用
    ty = 330
    d.text((88, ty - 6), "系统", font=font(20, True), fill=ACCENT)
    for i, (name, args, ok) in enumerate(TOOLS):
        if i >= tool_stage:
            break
        done = i < tool_stage - 1
        mark = "[OK]" if done else "[..]"
        color = ACCENT if done else ACCENT2
        d.text((158, ty + i * 46), mark, font=font(22, True), fill=color)
        d.text((214, ty + i * 46), name + "(", font=font(20, True), fill=TEXT)
        d.text((214 + d.textlength(name + "(", font=font(20, True)), ty + i * 46),
               args + ")", font=font(19), fill=MUTED)
    # 底部状态
    status = ["正在解析意图…", "任务规划完成，等待确认…", "安全校验通过，无人机起飞…", "进入自动航点任务…"]
    idx = min(tool_stage, len(status) - 1)
    d.text((88, 552), "> " + status[idx], font=font(20, True), fill=(170, 200, 220))
    # 底部进度点
    for k in range(4):
        c = ACCENT if k <= tool_stage else (70, 84, 104)
        d.ellipse([88 + k * 34, 640, 88 + k * 34 + 14, 654], fill=c)
    return img

def wrap_lines(d, text, f, maxw):
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

# ---------------------------------------------------------------- 飞行 HUD
def hud(frame, i):
    img = frame.copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rectangle([0, 0, W, 76], fill=(0, 0, 0, 96))
    d.rectangle([0, H - 32, W, H], fill=(0, 0, 0, 70))
    p = POSES[i]
    alt = p["loc_cm"][2] / 100.0
    spd = p["speed_mps"]
    hdg = (p["yaw"] + 360.0) % 360.0
    gps = p["gps"]
    # 竖直速度
    j = min(i + 1, N - 1)
    vs = (POSES[j]["loc_cm"][2] - p["loc_cm"][2]) * FPS / 100.0
    batt = 100.0 - 11.0 * (i / float(N - 1))
    wp = min(30, int(i / float(N - 1) * 30) + 1)

    # 顶部左：REC + 模式
    d.ellipse([26, 22, 40, 36], fill=RED + (255,))
    d.text((50, 20), "REC", font=font(18, True), fill=(255, 255, 255, 255))
    d.text((100, 20), "AUTO MISSION · 3DGS GRID", font=font(17, True), fill=(230, 238, 248, 255))
    # 顶部中：LLM 指令
    d.text((26, 46), "GPS 24 SAT  ·  FIX 3D  ·  LLM: 园区 3DGS 航拍 40 m / 重叠 75%", font=font(14), fill=(185, 205, 225, 235))
    # 顶部右：电量/卫星
    rounded(d, [W - 250, 14, W - 26, 46], 8, fill=(0, 0, 0, 120), outline=(90, 110, 140, 160))
    d.text((W - 238, 21), "BAT %d%%" % int(batt), font=font(15, True), fill=(220, 235, 245, 255))
    d.rectangle([W - 176, 24, W - 176 + int(140 * batt / 100), 36], fill=(ACCENT if batt > 40 else ACCENT2) + (255,))
    pass
    # 四角括号
    L = 26
    for (x, y, sx, sy) in [(20, 74, 1, 1), (W - 20, 74, -1, 1), (20, H - 20, 1, -1), (W - 20, H - 20, -1, -1)]:
        d.line([(x, y), (x + sx * L, y)], fill=(255, 255, 255, 90), width=2)
        d.line([(x, y), (x, y + sy * L)], fill=(255, 255, 255, 90), width=2)
    # 左下遥测
    box = [26, H - 168, 322, H - 26]
    rounded(d, box, 12, fill=(0, 0, 0, 130), outline=(90, 110, 140, 150))
    d.text((44, box[1] + 12), "TELEMETRY", font=font(12, True), fill=(140, 165, 190, 255))
    items = [("ALT", "%5.1f m" % alt), ("SPD", "%4.1f m/s" % spd), ("V/S", "%+4.1f m/s" % vs), ("HDG", "%03d°" % int(hdg))]
    for k, (k1, v1) in enumerate(items):
        yy = box[1] + 34 + k * 28
        d.text((44, yy), k1, font=font(13, True), fill=(130, 155, 180, 255))
        d.text((110, yy - 3), v1, font=font(20, True), fill=(235, 245, 250, 255))
    # 左下 GPS
    d.text((44, box[3] - 20), fmt_latlon(gps), font=font(11), fill=(150, 175, 195, 230))
    # 底部中：任务进度
    prog = i / float(N - 1)
    rounded(d, [W // 2 - 260, H - 92, W // 2 + 260, H - 26], 10, fill=(0, 0, 0, 120), outline=(90, 110, 140, 150))
    d.text((W // 2 - 244, H - 84), "MISSION PROGRESS", font=font(12, True), fill=(140, 165, 190, 255))
    d.text((W // 2 + 244, H - 84), "%d%%" % int(prog * 100), font=font(14, True), fill=(235, 245, 250, 255), anchor="ra")
    d.rounded_rectangle([W // 2 - 244, H - 58, W // 2 + 244, H - 44], radius=6, fill=(40, 52, 70, 220))
    d.rounded_rectangle([W // 2 - 244, H - 58, W // 2 - 244 + int(488 * prog), H - 44], radius=6, fill=ACCENT + (255,))
    d.text((W // 2 - 244, H - 40), "航点 %d/30 · 拍照 %d" % (wp, wp), font=font(12), fill=(180, 200, 220, 235))
    # 右下：工具链
    tools = [("plan", True), ("takeoff", True), ("goto", i < N - 30), ("rth", False)]
    bx = W - 300
    rounded(d, [bx, H - 148, W - 26, H - 26], 10, fill=(0, 0, 0, 120), outline=(90, 110, 140, 150))
    d.text((bx + 14, H - 140), "LLM TOOL CHAIN", font=font(12, True), fill=(140, 165, 190, 255))
    for k, (nm, st) in enumerate(tools):
        if k == 2: st = i < N - 30
        if k == 3: st = i >= N - 30 and False
        col = ACCENT if st else (110, 125, 145)
        mark = "OK" if st else "--"
        d.text((bx + 14, H - 118 + k * 22), mark + " " + nm, font=font(13, True), fill=col + (255,))
    # 中心十字
    cx, cy = W // 2, H // 2
    d.line([(cx - 16, cy), (cx - 5, cy)], fill=(255, 255, 255, 110), width=1)
    d.line([(cx + 5, cy), (cx + 16, cy)], fill=(255, 255, 255, 110), width=1)
    d.line([(cx, cy - 16), (cx, cy - 5)], fill=(255, 255, 255, 110), width=1)
    d.line([(cx, cy + 5), (cx, cy + 16)], fill=(255, 255, 255, 110), width=1)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

# ---------------------------------------------------------------- 结尾：任务完成
def outro(base, t):
    img = base.copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rectangle([0, 0, W, H], fill=(5, 9, 16, 190))
    d.text((70, 70), "任务完成", font=font(56, True), fill=(240, 248, 252, 255))
    d.rectangle([72, 150, 72 + 120, 155], fill=ACCENT + (255,))
    lines = [
        "LLM 规划 → 安全校验 → 无人机自动执行 → 返航降落",
        "30 个航点 · 30 张照片 · 航线 402 m · 仿真 308 s",
        "照片含 GPS / 云台 / 真值位姿 → 可直接进入 3DGS 重建",
    ]
    for k, ln in enumerate(lines):
        d.text((72, 190 + k * 42), ln, font=font(24), fill=(215, 228, 240, 255))
    # 照片墙
    thumbs = ["0001.png", "0020.png", "0045.png", "0065.png"]
    tw, th = 236, 177
    for k, name in enumerate(thumbs):
        p = os.path.join(ROOT, "data", "synthetic", "mission_llm", "images", name)
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS)
        x = 72 + k * (tw + 18)
        y = 360
        img.paste(im, (x, y))
        d.rectangle([x, y, x + tw, y + th], outline=(90, 110, 140, 255), width=2)
        d.text((x + 6, y + th + 6), name.replace(".png", ""), font=font(13), fill=(170, 190, 210, 255))
    d.text((72, H - 96), "下一步：3DGS 重建 → UE5 实时浏览", font=font(26, True), fill=ACCENT + (255,))
    d.text((72, H - 56), "DJI Mini × UE5 3DGS 可行性验证 · 演示", font=font(16), fill=(150, 170, 190, 255))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

def main():
    if not os.path.isdir(RAW) or len(FILES) < 10:
        print("RAW frames missing"); return 2
    frames = []
    # 1) 开场
    n_intro = int(INTRO_S * FPS)
    total_chars = len(CMD)
    for k in range(n_intro):
        t = k / float(FPS)
        # 打字进度：前 2.2s 打完
        chars = int(min(1.0, t / 2.2) * total_chars)
        stage = 0
        if t > 2.6: stage = 1
        if t > 3.2: stage = 2
        if t > 3.9: stage = 3
        if t > 4.6: stage = 4
        im = draw_console(t, chars, stage, show_cursor=(t <= 2.4))
        frames.append(im)
    first = load_frame(0)
    # 转场 0.4s：黑 -> 飞行首帧
    trans = int(0.4 * FPS)
    black = Image.new("RGB", (W, H), (2, 4, 8))
    for k in range(trans):
        a = (k + 1) / trans
        frames.append(Image.blend(black, hud(first, 0), a))
    # 2) 飞行
    for i in range(N):
        if i % 30 == 0:
            print("hud %d/%d" % (i, N), flush=True)
        frames.append(hud(load_frame(i), i))
    # 3) 结尾
    last = load_frame(N - 1)
    n_out = int(OUTRO_S * FPS)
    for k in range(n_out):
        a = min(1.0, k / (0.6 * FPS))
        frames.append(Image.blend(last, outro(last, k / FPS), a))
    # 4) 编码
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-vcodec", "rawvideo",
           "-s", "%dx%d" % (W, H), "-pix_fmt", "rgb24", "-r", str(FPS), "-i", "-",
           "-an", "-vcodec", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
           "-preset", "medium", "-movflags", "+faststart", OUT]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close(); proc.wait()
    print("saved", OUT, "frames", len(frames), "dur", round(len(frames) / FPS, 1), "s")
    print("size", os.path.getsize(OUT))
    # 封面
    cover = hud(load_frame(180), 180)
    cover.save(POSTER, quality=95)
    print("poster", POSTER)
    return 0

if __name__ == "__main__":
    sys.exit(main())
