"""headless_build.py -- build the procedural campus scene with no RHI / no GPU work.

Run through the pythonscript commandlet (headless, -nullrhi):

    UnrealEditor-Cmd.exe UE5Synth.uproject -run=pythonscript ^
        -script="C:/UEW/dji_ue5_3dgs/capture/scripts/headless_build.py" ^
        -nullrhi -unattended -nosplash -stdout -log

This exercises the whole scene-generation code path (textures, materials, actor spawning,
lighting, level save) on the CPU only, so geometry/materials bugs are found without
spending an exclusive RHI/GPU window.  Args can be overridden with the PY_SYNTH_ARGS
environment variable (default: --mode build --rebuild).
"""

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "capture_synth.py")
args = ["--mode", "build", "--rebuild"]
extra = os.environ.get("PY_SYNTH_ARGS", "").strip()
if extra:
    args = extra.split()
sys.argv = [SCRIPT] + args
print("[HEADLESS] running %s with args %s" % (SCRIPT, args), flush=True)
runpy.run_path(SCRIPT, run_name="__main__")
