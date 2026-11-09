"""diag3.py -- print post-process / light property names used to fix exposure."""
import unreal

def p(*a):
    line = "[DIAG3] " + " ".join(str(x) for x in a)
    print(line)
    try:
        unreal.log(line)
    except Exception:
        pass

pp = unreal.PostProcessSettings()
p("camera/fstop/bias props", [n for n in dir(pp) if ("camera" in n.lower() or "fstop" in n.lower() or "bias" in n.lower())])
p("exposure props", [n for n in dir(pp) if "exposure" in n.lower()])
p("tonemap props", [n for n in dir(pp) if "tonemap" in n.lower() or "film" in n.lower()])
p("ELightUnits entries", [n for n in dir(unreal.LightUnits) if not n.startswith("_")])
dlc = unreal.DirectionalLightComponent
p("dlc intensity props", {n: hasattr(dlc, n) for n in ("intensity", "intensity_units", "light_color", "atmosphere_sun_light", "mobility")})
slc = unreal.SkyLightComponent
p("sky props", {n: hasattr(slc, n) for n in ("intensity", "real_time_capture", "light_color", "mobility")})
p("has EyeAdaptation showflag?", hasattr(unreal, "EngineShowFlags"))
p("done")
