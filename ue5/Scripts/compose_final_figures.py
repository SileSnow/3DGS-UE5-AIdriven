import os, shutil
from PIL import Image, ImageDraw, ImageFont
base = 'C:/UEW/dji_ue5_3dgs/ue5/results'
final = os.path.join(base, 'final')
os.makedirs(final, exist_ok=True)

def load(p):
    return Image.open(p).convert('RGB')

# 1) copy Path B real-PLY views
src_views = [os.path.join(base, 'final_pathb', 'screenshots', 'view_%02d.png' % i) for i in range(4)]
for i, p in enumerate(src_views):
    shutil.copy(p, os.path.join(final, 'pathb_real_ply_view_%02d.png' % i))

# 2) copy sphere debug preview and best Niagara attempt
shutil.copy(os.path.join(base, 'pathb_ctrl', 'viewport_measure_start.png'), os.path.join(final, 'pathb_sphere_50k_debug.png'))
shutil.copy(os.path.join(base, 'nia_sm01', 'screenshots', 'orbit_000.png'), os.path.join(final, 'niagara_attempt_best.png'))
shutil.copy(os.path.join(base, 'nia_sm001', 'screenshots', 'orbit_000.png'), os.path.join(final, 'niagara_attempt_small_scale.png'))
shutil.copy(os.path.join(base, 'reference', 'real_capture_ref_yaw0.png'), os.path.join(final, 'reference_real_capture_cpu_yaw0.png'))

# 3) comparison: UE viewport (left) vs CPU reference (right)
ue = load(src_views[0])
ref = load(os.path.join(base, 'reference', 'real_capture_ref_yaw0.png'))
try:
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 28)
except Exception:
    font = ImageFont.load_default()
canvas = Image.new('RGB', (ue.width + ref.width, ue.height + 44), (16, 16, 16))
canvas.paste(ue, (0, 44))
canvas.paste(ref, (ue.width, 44))
d = ImageDraw.Draw(canvas)
d.text((16, 8), 'UE 5.8.4 - Path B preview (debug points, 109k splats)', fill=(255, 200, 90), font=font)
d.text((ue.width + 16, 8), 'CPU reference projection (same camera, numpy)', fill=(120, 220, 255), font=font)
canvas.save(os.path.join(final, 'comparison_ue_vs_reference.png'))

# 4) 2x2 grid of the four orbit views
views = [load(p) for p in src_views]
w, h = views[0].size
grid = Image.new('RGB', (w * 2, h * 2), (10, 10, 10))
for i, v in enumerate(views):
    grid.paste(v, ((i % 2) * w, (i // 2) * h))
grid.save(os.path.join(final, 'pathb_real_ply_4views_grid.png'))

print('[compose] written to', final)
for f in sorted(os.listdir(final)):
    p = os.path.join(final, f)
    print('  ', f, os.path.getsize(p), 'bytes')
