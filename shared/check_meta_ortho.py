import json, numpy as np, os
base = r'C:\Users\Lenovo\Desktop\GAIA项目\dji_ue5_3dgs\\data\\synthetic\\capture'
meta = json.load(open(os.path.join(base, 'metadata.json'), encoding='utf-8'))
print('frames', len(meta['frames']))
bad = 0; maxerr = 0.0
for f in meta['frames']:
    M = np.array(f['c2w'], dtype=float).reshape(4,4)
    R = M[:3,:3]
    err = float(np.abs(R @ R.T - np.eye(3)).max())
    maxerr = max(maxerr, err)
    if err > 1e-6: bad += 1
print('non_orthonormal_frames', bad, 'max_RRt_err', maxerr)
print('mtime_meta', os.path.getmtime(os.path.join(base,'metadata.json')))
print('bak_exists', os.path.exists(os.path.join(base,'metadata.bak.json')))