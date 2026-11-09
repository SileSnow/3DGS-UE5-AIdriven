# -*- coding: utf-8 -*-
import wave, os, glob, json
d = r"C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\report\audio"
rows = []
total = 0.0
for p in sorted(glob.glob(os.path.join(d, "line_*.wav"))):
    with wave.open(p, "rb") as w:
        n = w.getnframes(); sr = w.getframerate()
        dur = n / float(sr)
    rows.append((os.path.basename(p), round(dur, 2), sr))
    total += dur
print(json.dumps({"lines": rows, "total_s": round(total, 2)}, ensure_ascii=False))
