"""
gen_textures.py -- procedural PNG textures for the UE5 synthetic campus scene.

Runs with the SYSTEM Python (Pillow + numpy installed), NOT inside Unreal.
Writes 512x512 seamlessly tileable PNGs into:
    <repo>/capture/assets/textures/

Files:
    T_Grass.png, T_Asphalt.png, T_Concrete.png, T_Paving.png,
    T_FacadeA.png, T_FacadeB.png, T_Glass.png, T_Roof.png
"""
import os
import numpy as np
from PIL import Image, ImageDraw

S = 512
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "textures")
rng = np.random.default_rng(20261108)


def periodic_noise(wavelength_px=64.0, octaves=4):
    """Seamlessly tileable gaussian noise in roughly [-1, 1] (period S)."""
    total = np.zeros((S, S), np.float32)
    amp = 1.0
    fy = np.fft.fftfreq(S)[:, None]
    fx = np.fft.fftfreq(S)[None, :]
    for _ in range(octaves):
        sigma = 1.0 / wavelength_px
        filt = np.exp(-0.5 * (np.sqrt(fx * fx + fy * fy) / sigma) ** 2)
        spec = filt * (rng.normal(size=(S, S)) + 1j * rng.normal(size=(S, S)))
        n = np.real(np.fft.ifft2(spec))
        n /= (n.std() + 1e-9)
        total += amp * n
        amp *= 0.5
        wavelength_px *= 0.5
    total /= (total.std() + 1e-9)
    return np.clip(total, -2.5, 2.5)


def rgb_image(arr, name):
    img = Image.fromarray(np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8))
    path = os.path.join(OUT_DIR, name + ".png")
    img.save(path, optimize=True)
    print("wrote", path)


def base_layer(color):
    a = np.zeros((S, S, 3), np.float32)
    a[:, :, 0] = color[0]
    a[:, :, 1] = color[1]
    a[:, :, 2] = color[2]
    return a


def make_grass():
    a = base_layer((0.335, 0.475, 0.205))
    n1 = periodic_noise(96.0, 4)
    n2 = periodic_noise(8.0, 3)
    for c in range(3):
        a[:, :, c] += n1 * 0.055 + n2 * 0.035
    # darker / lighter patches
    patch = periodic_noise(160.0, 2)
    a += (patch > 1.1)[:, :, None] * np.array([-0.035, -0.03, -0.02], np.float32)
    a += (patch < -1.3)[:, :, None] * np.array([0.04, 0.035, 0.02], np.float32)
    rgb_image(a, "T_Grass")


def make_asphalt():
    a = base_layer((0.205, 0.208, 0.215))
    n1 = periodic_noise(32.0, 4)
    n2 = periodic_noise(4.0, 2)
    for c in range(3):
        a[:, :, c] += n1 * 0.045 + n2 * 0.022
    # faint lighter patches (repair patches)
    patch = periodic_noise(128.0, 2)
    a += (patch > 1.4)[:, :, None] * np.array([0.03, 0.03, 0.03], np.float32)
    rgb_image(a, "T_Asphalt")


def _lines(img, color, lines, width=2):
    d = ImageDraw.Draw(img)
    for (x0, y0, x1, y1) in lines:
        d.line([x0, y0, x1, y1], fill=color, width=width)


def make_concrete():
    a = base_layer((0.615, 0.600, 0.570))
    n1 = periodic_noise(64.0, 4)
    n2 = periodic_noise(6.0, 2)
    for c in range(3):
        a[:, :, c] += n1 * 0.05 + n2 * 0.02
    img = Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))
    _lines(img, (150, 147, 140), [(0, y, S, y) for y in (128, 256, 384)], 2)
    _lines(img, (190, 187, 180), [(0, y + 3, S, y + 3) for y in (128, 256, 384)], 1)
    img.save(os.path.join(OUT_DIR, "T_Concrete.png"), optimize=True)
    print("wrote T_Concrete.png")


def make_paving():
    a = base_layer((0.685, 0.675, 0.650))
    n1 = periodic_noise(48.0, 4)
    n2 = periodic_noise(6.0, 2)
    for c in range(3):
        a[:, :, c] += n1 * 0.045 + n2 * 0.018
    img = Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for y in range(0, S, 128):
        d.line([0, y, S, y], fill=(135, 133, 128), width=2)
    for x in range(0, S, 128):
        d.line([x, 0, x, S], fill=(140, 138, 133), width=2)
    img.save(os.path.join(OUT_DIR, "T_Paving.png"), optimize=True)
    print("wrote T_Paving.png")


def make_facade_a():
    """Concrete facade with a 4x4 grid of windows (tile = 8m x 8m)."""
    a = base_layer((0.660, 0.645, 0.620))
    n1 = periodic_noise(72.0, 4)
    for c in range(3):
        a[:, :, c] += n1 * 0.045
    img = Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    cell = S // 4
    for iy in range(4):
        for ix in range(4):
            x0 = ix * cell + 18
            y0 = iy * cell + 20
            x1 = x0 + cell - 36
            y1 = y0 + cell - 40
            # frame
            d.rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], fill=(172, 170, 165))
            # glass: per-window brightness variation + vertical gradient
            bright = 0.14 + 0.10 * rng.random()
            win = np.zeros((y1 - y0, x1 - x0, 3), np.float32)
            for yy in range(y1 - y0):
                t = yy / max(1, (y1 - y0 - 1))
                shade = bright * (0.65 + 0.55 * t)
                win[yy, :, 0] = shade * 0.75
                win[yy, :, 1] = shade * 0.95
                win[yy, :, 2] = shade * 1.18
            img.paste(Image.fromarray(np.clip(win * 255, 0, 255).astype(np.uint8)), (x0, y0))
            # mullion
            mx = (x0 + x1) // 2
            d.line([mx, y0, mx, y1], fill=(88, 92, 96), width=2)
            my = (y0 + y1) // 2
            d.line([x0, my, x1, my], fill=(88, 92, 96), width=2)
    # floor slabs
    for y in range(0, S, 128):
        d.line([0, y, S, y], fill=(150, 148, 143), width=3)
    img.save(os.path.join(OUT_DIR, "T_FacadeA.png"), optimize=True)
    print("wrote T_FacadeA.png")


def make_facade_b():
    """Ribbon-window office facade (tile = 8m x 8m)."""
    a = base_layer((0.680, 0.670, 0.650))
    n1 = periodic_noise(72.0, 3)
    for c in range(3):
        a[:, :, c] += n1 * 0.035
    img = Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for band in range(4):
        y0 = band * 128 + 30
        y1 = y0 + 66
        glass = np.zeros((y1 - y0, S, 3), np.float32)
        for yy in range(y1 - y0):
            t = yy / max(1, (y1 - y0 - 1))
            shade = 0.15 + 0.09 * (1.0 - abs(t - 0.45) * 2.0)
            glass[yy, :, 0] = shade * 0.72
            glass[yy, :, 1] = shade * 0.90
            glass[yy, :, 2] = shade * 1.15
        img.paste(Image.fromarray(np.clip(glass * 255, 0, 255).astype(np.uint8)), (0, y0))
        # mullions
        for x in range(0, S, 64):
            d.line([x, y0, x, y1], fill=(70, 74, 78), width=3)
        d.line([0, y0, S, y0], fill=(60, 64, 68), width=2)
        # spandrel highlight
        d.line([0, y1 + 2, S, y1 + 2], fill=(196, 194, 188), width=4)
    img.save(os.path.join(OUT_DIR, "T_FacadeB.png"), optimize=True)
    print("wrote T_FacadeB.png")


def make_glass():
    """Curtain-wall glass (tile = 8m x 8m)."""
    a = base_layer((0.115, 0.165, 0.205))
    n1 = periodic_noise(48.0, 3)
    for c in range(3):
        a[:, :, c] += n1 * 0.02
    img = Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for x in range(0, S, 64):
        d.line([x, 0, x, S], fill=(78, 86, 92), width=3)
    for y in range(0, S, 128):
        d.line([0, y, S, y], fill=(70, 78, 84), width=4)
    # sky reflection streaks
    for i in range(6):
        y = int(rng.integers(0, S))
        d.line([0, y, S, y + int(rng.integers(-30, 30))], fill=(150, 175, 195), width=2)
    img.save(os.path.join(OUT_DIR, "T_Glass.png"), optimize=True)
    print("wrote T_Glass.png")


def make_roof():
    a = base_layer((0.440, 0.435, 0.420))
    n1 = periodic_noise(16.0, 4)
    n2 = periodic_noise(3.0, 2)
    for c in range(3):
        a[:, :, c] += n1 * 0.07 + n2 * 0.03
    rgb_image(a, "T_Roof")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    make_grass()
    make_asphalt()
    make_concrete()
    make_paving()
    make_facade_a()
    make_facade_b()
    make_glass()
    make_roof()
    print("done ->", OUT_DIR)


if __name__ == "__main__":
    main()
