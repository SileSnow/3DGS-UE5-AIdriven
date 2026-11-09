# -*- coding: utf-8 -*-
"""make_audio.py -- 旁白 + 程序化音效混音（22050 Hz mono WAV）。"""
import glob, os, wave
import numpy as np

AUD = r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\report\audio"
OUT = os.path.join(AUD, "narration_mix.wav")
SR = 22050
DUR = 41.5

# 旁白时间码（与视频分镜一致）
OFFSETS = [3.1, 7.7, 12.4, 17.7, 22.2, 28.2, 34.0, 38.9]

def read_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getframerate() == SR, w.getframerate()
        n = w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            data = data.reshape(-1, 2).mean(axis=1)
    return data

mix = np.zeros(int(SR * DUR), dtype=np.float32)

# 1) 旁白
for i, off in enumerate(OFFSETS, 1):
    p = os.path.join(AUD, "line_%02d.wav" % i)
    if not os.path.exists(p):
        print("missing", p); continue
    seg = read_wav(p)
    s = int(off * SR)
    e = min(s + len(seg), len(mix))
    mix[s:e] += seg[:e - s] * 1.0

# 2) 低频 pad（开场到结束）
t = np.arange(len(mix)) / SR
lfo = 0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * t)
pad = (0.5 * np.sin(2 * np.pi * 55.0 * t) + 0.35 * np.sin(2 * np.pi * 82.5 * t + 0.3)
       + 0.25 * np.sin(2 * np.pi * 110.0 * t + 1.1) + 0.12 * np.sin(2 * np.pi * 164.8 * t + 2.0))
fade_in = np.clip(t / 2.0, 0, 1)
fade_out = np.clip((DUR - t) / 2.5, 0, 1)
mix += (pad * (0.05 + 0.03 * lfo)) * fade_in * fade_out

def add(sig, at, gain=1.0):
    s = int(at * SR)
    e = min(s + len(sig), len(mix))
    if e > s:
        mix[s:e] += sig[:e - s] * gain

# 3) whoosh（转场）
def whoosh(dur=1.1, seed=1):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    x = rng.standard_normal(n)
    k = np.hanning(n)
    x = x * k
    # 简单低通
    w = 60
    x = np.convolve(x, np.ones(w) / w, mode="same")
    return x * 1.6

add(whoosh(1.2, 2), 9.7, 0.10)    # 进入飞行
add(whoosh(1.0, 3), 27.6, 0.10)   # 进入结果
add(whoosh(0.9, 4), 35.6, 0.07)   # 进入结尾

# 4) 工具调用提示音（控制台）
def beep(freq=880.0, dur=0.07):
    n = int(dur * SR)
    x = np.sin(2 * np.pi * freq * np.arange(n) / SR)
    x *= np.hanning(n)
    return x
for k, at in enumerate([5.6, 6.2, 6.9, 7.6]):
    add(beep(760 + 90 * k), at, 0.055)

# 5) 快门声（飞行拍摄，15 次）
def shutter(seed=9):
    rng = np.random.default_rng(seed)
    n = int(0.035 * SR)
    x = rng.standard_normal(n)
    x = np.diff(np.concatenate([[0.0], x]))
    x *= np.hanning(n) ** 2
    return x * 0.5
for k in range(15):
    add(shutter(20 + k), 10.7 + k * 1.15, 0.07)

# 6) 结果揭晓提示音
add(np.concatenate([beep(660, 0.12), np.zeros(int(0.05 * SR)), beep(990, 0.18)]), 28.4, 0.05)

# 归一化 & 导出
peak = float(np.max(np.abs(mix))) or 1.0
mix = mix / peak * 0.92
mix *= np.clip(np.arange(len(mix)) / (0.4 * SR), 0, 1)
pcm = (mix * 32767.0).astype(np.int16)
with wave.open(OUT, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("saved", OUT, "dur", round(len(mix) / SR, 2), "s, peak", round(peak, 3))
