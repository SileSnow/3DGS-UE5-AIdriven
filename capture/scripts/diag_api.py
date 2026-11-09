"""diag_api.py -- quick UE5.8 Python API introspection (runs in the pythonscript commandlet).

    UnrealEditor-Cmd.exe UE5Synth.uproject -run=pythonscript -script=diag_api.py -nullrhi -unattended

Prints which of the APIs used by synth_common.py exist in this UE 5.8 build, so that API
name mismatches (e.g. UCLASS ScriptName overrides) are found without spending a render window.
"""

import sys

import unreal


def p(*args):
    line = "[DIAG] " + " ".join(str(a) for a in args)
    print(line)
    try:
        unreal.log(line)
    except Exception:
        pass


p("python", sys.version.split()[0])
p("has MaterialLibrary", hasattr(unreal, "MaterialLibrary"),
  "has KismetMaterialLibrary", hasattr(unreal, "KismetMaterialLibrary"))
ml = getattr(unreal, "MaterialLibrary", None)
if ml is not None:
    p("MaterialLibrary methods", [n for n in dir(ml) if not n.startswith("_")])
p("has RenderingLibrary", hasattr(unreal, "RenderingLibrary"))
rl = getattr(unreal, "RenderingLibrary", None)
if rl is not None:
    p("RenderingLibrary methods", [n for n in dir(rl) if not n.startswith("_")])

for name in ("SceneCapture2D", "SceneCaptureComponent2D", "TextureRenderTarget2D", "StaticMeshActor",
             "DirectionalLight", "SkyLight", "SkyAtmosphere", "ExponentialHeightFog",
             "LevelEditorSubsystem", "EditorActorSubsystem", "UnrealEditorSubsystem",
             "EditorAssetLibrary", "AssetImportTask", "MaterialFactoryNew", "MaterialEditingLibrary",
             "MaterialInstanceConstantFactoryNew", "SceneCaptureComponent",
             "AutoExposureMethod", "ComponentMobility", "CameraProjectionMode", "SceneCaptureSource",
             "TextureRenderTargetFormat", "MaterialProperty", "MaterialSamplerType", "PixelFormat",
             "SystemLibrary", "new_object"):
    p("attr", name, hasattr(unreal, name))

for enum_name in ("AutoExposureMethod", "SceneCaptureSource", "ComponentMobility",
                  "CameraProjectionMode", "TextureRenderTargetFormat"):
    enum_cls = getattr(unreal, enum_name, None)
    if enum_cls is not None:
        p("enum", enum_name, [n for n in dir(enum_cls) if not n.startswith("_")])
p("PixelFormat.PF_B8G8R8A8", hasattr(unreal.PixelFormat, "PF_B8G8R8A8"))
p("MaterialProperty.MP_BASE_COLOR", hasattr(unreal.MaterialProperty, "MP_BASE_COLOR"))

sc2d = getattr(unreal, "SceneCapture2D", None)
if sc2d is not None:
    p("SceneCapture2D props", [n for n in dir(sc2d) if not n.startswith("_")][:30])
sc2c = getattr(unreal, "SceneCaptureComponent2D", None)
if sc2c is not None:
    wanted = ("fov_angle", "texture_target", "capture_source", "capture_every_frame",
              "capture_on_movement", "post_process_settings", "post_process_blend_weight",
              "always_persist_rendering_state", "projection_type", "use_custom_projection_matrix")
    p("SceneCaptureComponent2D wanted props", {n: hasattr(sc2c, n) for n in wanted})

try:
    pp = unreal.PostProcessSettings()
    p("PostProcessSettings exposure props",
      [n for n in dir(pp) if "auto_exposure" in n.lower()][:30])
    p("PostProcessSettings misc props",
      [n for n in dir(pp) if n in ("motion_blur_amount", "bloom_intensity", "vignette_intensity",
                                   "film_grain_intensity", "scene_fringe_intensity")])
except Exception as exc:  # noqa: BLE001
    p("PostProcessSettings construct failed", exc)

p("done")
