import re
from pypdf import PdfReader
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "terra_release_notes_5.0.2.pdf")
r = PdfReader(p)
txt = '\n'.join((pg.extract_text() or '') for pg in r.pages)
print('PAGES', len(r.pages), 'CHARS', len(txt))
for kw in ['Gaussian', 'Splat', '3DGS', 'PLY', '高斯', '点云', 'Osgb', 'OSGB', 'LOD']:
    idx = [m.start() for m in re.finditer(kw, txt, re.IGNORECASE)]
    print('KW', kw, 'count', len(idx))
    for i in idx[:2]:
        print('  ...', txt[max(0, i - 300):i + 500].replace(chr(10), ' '))
print('=== FIRST 1500 CHARS ===')
print(txt[:1500].replace(chr(10),' '))