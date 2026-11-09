import os, shutil
from PIL import Image, ImageDraw, ImageFont
base = 'C:/UEW/dji_ue5_3dgs/ue5/results'
v2 = os.path.join(base, 'final_v2')
refdir = os.path.join(v2, 'reference')
os.makedirs(refdir, exist_ok=True)
ply = 'C:/UEW/dji_ue5_3dgs/data/trained/capture/run1/gaussians_best.ply'
# reference camera params identical to the UE presets
presets = [
    dict(yaw=0,   scale=0.9,  elev=0.15),
    dict(yaw=120, scale=1.0,  elev=0.35),
    dict(yaw=240, scale=0.75, elev=1.6),
    dict(yaw=45,  scale=1.0,  elev=0.35),
]
import subprocess, sys
for i, p in enumerate(presets):
    out = os.path.join(refdir, 'ref_view_%02d.png' % i)
    cmd = [sys.executable, 'C:/UEW/dji_ue5_3dgs/ue5/Scripts/render_ply_reference.py',
           '--ply', ply, '--out', out, '--yaw-deg', str(p['yaw']),
           '--camera-distance', '16000', '--dist-scale', str(p['scale']),
           '--elevation', str(p['elev'])]
    subprocess.run(cmd, check=True)

def load(p):
    return Image.open(p).convert('RGB')

try:
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 26)
except Exception:
    font = ImageFont.load_default()

ue0 = load(os.path.join(v2, 'screenshots', 'view_00.png'))
ref0 = load(os.path.join(refdir, 'ref_view_00.png'))
canvas = Image.new('RGB', (ue0.width + ref0.width, ue0.height + 44), (16, 16, 16))
canvas.paste(ue0, (0, 44))
canvas.paste(ref0, (ue0.width, 44))
d = ImageDraw.Draw(canvas)
d.text((16, 8), 'UE 5.8.4 Path B preview (109,376 splats, near view)', fill=(255, 200, 90), font=font)
d.text((ue0.width + 16, 8), 'CPU reference projection (same camera)', fill=(120, 220, 255), font=font)
cmp_path = os.path.join(v2, 'comparison_ue_vs_reference_v2.png')
canvas.save(cmp_path)

views = [load(os.path.join(v2, 'screenshots', 'view_%02d.png' % i)) for i in range(4)]
w, h = views[0].size
grid = Image.new('RGB', (w * 2, h * 2), (10, 10, 10))
for i, v in enumerate(views):
    grid.paste(v, ((i % 2) * w, (i // 2) * h))
grid.save(os.path.join(v2, 'ue_pathb_4views_grid_v2.png'))

# copy the core figures into the main final/ folder as well
final = os.path.join(base, 'final')
for i in range(4):
    shutil.copy(os.path.join(v2, 'screenshots', 'view_%02d.png' % i), os.path.join(final, 'v2_view_%02d.png' % i))
shutil.copy(cmp_path, os.path.join(final, 'comparison_ue_vs_reference_v2.png'))
shutil.copy(os.path.join(v2, 'ue_pathb_4views_grid_v2.png'), os.path.join(final, 'ue_pathb_4views_grid_v2.png'))
print('[compose] done')
for f in sorted(os.listdir(v2)):
    p = os.path.join(v2, f)
    if os.path.isfile(p):
        print('  ', f, os.path.getsize(p))
for f in ['ref_view_00.png','ref_view_01.png','ref_view_02.png','ref_view_03.png']:
    print('  reference/' + f, os.path.getsize(os.path.join(refdir, f)))
