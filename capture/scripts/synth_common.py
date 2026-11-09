"""
synth_common.py -- shared helpers for the UE5.8 procedural DJI-Mini aerial capture tool.

Runs INSIDE UnrealEditor (bundled Python 3.11) via -ExecutePythonScript.
No third-party Python packages are used (only stdlib + the unreal module).

Coordinate conventions (see shared/CONVENTIONS.md):
  * UE world: left handed, X forward, Y right, Z up, units = cm.
  * Camera axes: +X forward, +Y right, +Z up (SceneCapture2D actor axes).
  * Simulated GPS mapping: UE +X -> East, UE +Y -> South (so North = -Y), UE +Z -> Up.
  * c2w: 4x4 row-major, columns = camera axes (forward/right/up) expressed in UE world,
    translation = camera position in UE world cm.
"""

import json
import math
import os
import random
import time

import unreal

# ----------------------------------------------------------------------------- paths
THIS_FILE = os.path.abspath(__file__)
SCRIPTS_DIR = os.path.dirname(THIS_FILE)            # <repo>/capture/scripts
CAPTURE_ROOT = os.path.dirname(SCRIPTS_DIR)         # <repo>/capture
PROJECT_ROOT = os.path.dirname(CAPTURE_ROOT)        # <repo>
UE_PROJECT_DIR = os.path.join(CAPTURE_ROOT, "UE5Synth")
DATA_ROOT = os.path.join(PROJECT_ROOT, "data", "synthetic")
TRAIN_ROOT = os.path.join(DATA_ROOT, "capture")
VAL_ROOT = os.path.join(DATA_ROOT, "val")
TRAIN_IMAGES_DIR = os.path.join(TRAIN_ROOT, "images")
VAL_IMAGES_DIR = os.path.join(VAL_ROOT, "images")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs", "capture")
TEXTURE_SRC_DIR = os.path.join(CAPTURE_ROOT, "assets", "textures")

ASSET_DIR = "/Game/Synth"
MATERIAL_DIR = ASSET_DIR + "/Materials"
TEXTURE_DIR = ASSET_DIR + "/Textures"
MAP_ASSET = ASSET_DIR + "/Campus"
LABEL_PREFIX = "SYNTH_"

# --------------------------------------------------------------- DJI Mini 4 Pro camera
# Official specs (dji.com): 1/1.3 inch CMOS, FOV 82.1 deg (diagonal), 24mm equivalent,
# f/1.7, stills 4:3 8064x6048.  Active sensor area for a 1/1.3 inch 4:3 sensor is
# ~9.6 x 7.2 mm (diag 12.0 mm), which is consistent with 8064 px * 1.2 um = 9.68 mm.
SENSOR_W_MM = 9.6
SENSOR_H_MM = 7.2
SENSOR_DIAG_MM = math.hypot(SENSOR_W_MM, SENSOR_H_MM)
FOV_DIAG_DEG = 82.1
FOCAL_MM = (SENSOR_DIAG_MM * 0.5) / math.tan(math.radians(FOV_DIAG_DEG * 0.5))
WIDTH = 1600
HEIGHT = 1200
FOV_H_DEG = math.degrees(2.0 * math.atan(SENSOR_W_MM * 0.5 / FOCAL_MM))
FOV_V_DEG = math.degrees(2.0 * math.atan(SENSOR_H_MM * 0.5 / FOCAL_MM))
FX = FOCAL_MM / SENSOR_W_MM * WIDTH
FY = FOCAL_MM / SENSOR_H_MM * HEIGHT
CX = WIDTH * 0.5
CY = HEIGHT * 0.5
EQUIV_FOCAL_MM = 24.0
ORIGIN_WGS84 = {"lat": 39.9042, "lon": 116.4074, "alt": 43.0}
M_PER_DEG_LAT = 111320.0

# ------------------------------------------------------------------ scene / flight plan
AREA_HALF_CM = 4500.0          # 90 m x 90 m campus area centred on the world origin
GROUND_CM = 40000.0            # 400 m ground plane
PLOT_TOP_CM = 16.0             # raised block/plot top height
ROAD_W_CM = 900.0              # 9 m wide roads
ROAD_X = (-2800.0, 0.0, 2800.0)
ROAD_Y = (-2800.0, 0.0, 2800.0)
GRID_LINES = 7                 # flight lines per pass (across-track)
GRID_SHOTS = 5                 # shots per flight line (along-track)
PASSES = (
    # (heading yaw deg, gimbal pitch deg, altitude cm)
    (0.0, -45.0, 4000.0),
    (72.0, -48.0, 3800.0),
    (144.0, -50.0, 4200.0),
    (216.0, -52.0, 3600.0),
    (288.0, -55.0, 4400.0),
)
VAL_COUNT = 15
SCENE_SEED = 20261108

PALETTE = {
    "facade": (
        (0.86, 0.84, 0.79), (0.93, 0.92, 0.89), (0.72, 0.58, 0.48),
        (0.80, 0.70, 0.55), (0.60, 0.66, 0.70), (0.68, 0.69, 0.68),
        (0.62, 0.72, 0.68), (0.78, 0.64, 0.55),
    ),
    "car": (
        (0.80, 0.80, 0.82), (0.10, 0.11, 0.13), (0.55, 0.10, 0.10),
        (0.10, 0.25, 0.55), (0.75, 0.70, 0.30), (0.30, 0.45, 0.30),
        (0.60, 0.60, 0.62),
    ),
    "leaf": (
        (0.16, 0.42, 0.15), (0.20, 0.48, 0.17), (0.25, 0.52, 0.20),
        (0.13, 0.35, 0.12), (0.30, 0.50, 0.16),
    ),
}
MARKER_COLOR = (1.0, 0.0, 1.0)
MARKER_POSITIONS = (
    (-1600.0, -1600.0, 0.0),
    (1200.0, -800.0, 0.0),
    (2000.0, 1200.0, 0.0),
    (-1200.0, 2000.0, 0.0),
    (700.0, 700.0, 0.0),
)

# Calibration targets used by capture_synth.py --mode calib and by
# scripts/validate_reprojection.py.  They sit on the three open road intersections so
# that they are never occluded from a near-nadir calibration camera.
CALIB_MARKER_SIZE_CM = 140.0
CALIB_MARKER_BASE_Z_CM = 6.5
CALIB_MARKERS = (
    (0.0, 0.0),
    (-2800.0, 2800.0),
    (2800.0, -2800.0),
)
CALIB_CAMERA_OFFSETS_CM = (
    (520.0, -330.0),
    (-430.0, 460.0),
    (650.0, 620.0),
)

_CACHE = {"materials": {}, "mids": {}, "meshes": {}, "textures": {}, "lighting": {}}


# ----------------------------------------------------------------------------- logging
def log(msg):
    unreal.log("[SYNTH] " + str(msg))


def log_warn(msg):
    unreal.log_warning("[SYNTH] " + str(msg))


def log_err(msg):
    unreal.log_error("[SYNTH] " + str(msg))


def ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path)


def _try(fn, *args, **kwargs):
    """Call fn, swallow and log any exception. Returns (ok, result)."""
    try:
        return True, fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - log and continue
        log_warn("call %s failed: %s" % (getattr(fn, "__name__", fn), exc))
        return False, None


def enum_entry(enum_cls, *names):
    """Resolve a python enum entry by trying several spellings."""
    for name in names:
        try:
            return getattr(enum_cls, name)
        except Exception:
            continue
    return None


def module_class(*names):
    """Resolve a python-exposed class by trying several names.

    UE 5.8 is built with ScriptName meta-data on several Blueprint function libraries:
    UKismetMaterialLibrary -> unreal.MaterialLibrary, UKismetRenderingLibrary ->
    unreal.RenderingLibrary, UKismetSystemLibrary -> unreal.SystemLibrary, ...
    """
    for name in names:
        obj = getattr(unreal, name, None)
        if obj is not None:
            return obj
    log_warn("none of these unreal attributes exist: %s" % (", ".join(names),))
    return None


# ----------------------------------------------------------------------- editor access
def get_editor_world():
    try:
        subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        world = subsystem.get_editor_world()
        if world:
            return world
    except Exception as exc:
        log_warn("UnrealEditorSubsystem.get_editor_world failed: %s" % exc)
    try:
        return unreal.EditorLevelLibrary.get_editor_world()
    except Exception:
        return None


def actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def level_subsystem():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


# ----------------------------------------------------------------------------- assets
def asset_exists(path):
    return unreal.EditorAssetLibrary.does_asset_exist(path)


def load_asset(path):
    asset = unreal.EditorAssetLibrary.load_asset(path)
    if asset is None:
        log_warn("could not load asset: %s" % path)
    return asset


def make_asset_dir(path):
    if not unreal.EditorAssetLibrary.does_directory_exist(path):
        unreal.EditorAssetLibrary.make_directory(path)


def save_asset(asset):
    if asset is None:
        return
    with_path = asset.get_path_name()
    package_path = with_path.split(".")[0]
    unreal.EditorAssetLibrary.save_asset(package_path, False)


def get_engine_mesh(name):
    key = "mesh:" + name
    if key not in _CACHE["meshes"]:
        _CACHE["meshes"][key] = load_asset("/Engine/BasicShapes/%s.%s" % (name, name))
    return _CACHE["meshes"][key]


# ------------------------------------------------------------------------- materials
def _new_material(asset_name, builder):
    path = MATERIAL_DIR + "/" + asset_name
    if asset_exists(path):
        return load_asset(path)
    make_asset_dir(MATERIAL_DIR)
    factory = unreal.MaterialFactoryNew()
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = asset_tools.create_asset(asset_name, MATERIAL_DIR, unreal.Material, factory)
    if material is None:
        raise RuntimeError("failed to create material " + asset_name)
    mel = unreal.MaterialEditingLibrary
    builder(material, mel)
    mel.layout_material_expressions(material)
    mel.recompile_material(material)
    save_asset(material)
    log("created material %s" % path)
    return material


def force_compile_material(material):
    """Block until the material's shaders are compiled.

    UMaterialEditingLibrary::GetStatistics() internally calls FMaterialResource::FinishCompilation(),
    which is the only python-exposed way to synchronously wait for shader compilation.  Without
    this the first rendered frames would fall back to the default material (grey, untextured)
    because -ExecutePythonScript renders in the same editor tick that creates the materials.
    """
    if material is None:
        return False
    try:
        stats = unreal.MaterialEditingLibrary.get_statistics(material)
        pixel = getattr(stats, "num_pixel_shader_instructions", "?")
        vertex = getattr(stats, "num_vertex_shader_instructions", "?")
        log("material %s compiled synchronously (pixel_instr=%s vertex_instr=%s)" % (
            material.get_name(), pixel, vertex))
        return True
    except Exception as exc:
        log_warn("force compile of %s failed: %s" % (material.get_name(), exc))
        return False


def _build_flat_material(material, mel):
    base = mel.create_material_expression(material, unreal.MaterialExpressionVectorParameter, -420, -60)
    base.set_editor_property("parameter_name", "BaseColor")
    base.set_editor_property("default_value", unreal.LinearColor(0.6, 0.6, 0.6, 1.0))
    mel.connect_material_property(base, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = mel.create_material_expression(material, unreal.MaterialExpressionScalarParameter, -420, 120)
    rough.set_editor_property("parameter_name", "Roughness")
    rough.set_editor_property("default_value", 0.8)
    mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)


def _build_tiled_material(material, mel):
    tex = mel.create_material_expression(material, unreal.MaterialExpressionTextureSampleParameter2D, -420, -180)
    tex.set_editor_property("parameter_name", "BaseTex")
    tex.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    uv = mel.create_material_expression(material, unreal.MaterialExpressionTextureCoordinate, -900, -40)
    scale = mel.create_material_expression(material, unreal.MaterialExpressionScalarParameter, -900, 120)
    scale.set_editor_property("parameter_name", "UVScale")
    scale.set_editor_property("default_value", 1.0)
    uv_mul = mel.create_material_expression(material, unreal.MaterialExpressionMultiply, -650, -40)
    mel.connect_material_expressions(uv, "", uv_mul, "A")
    mel.connect_material_expressions(scale, "", uv_mul, "B")
    mel.connect_material_expressions(uv_mul, "", tex, "UVs")
    tint = mel.create_material_expression(material, unreal.MaterialExpressionVectorParameter, -650, 220)
    tint.set_editor_property("parameter_name", "Tint")
    tint.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
    color_mul = mel.create_material_expression(material, unreal.MaterialExpressionMultiply, -300, -40)
    mel.connect_material_expressions(tex, "RGB", color_mul, "A")
    mel.connect_material_expressions(tint, "", color_mul, "B")
    mel.connect_material_property(color_mul, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = mel.create_material_expression(material, unreal.MaterialExpressionScalarParameter, -420, 320)
    rough.set_editor_property("parameter_name", "Roughness")
    rough.set_editor_property("default_value", 0.85)
    mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)


def ensure_materials():
    if "flat" not in _CACHE["materials"]:
        _CACHE["materials"]["flat"] = _new_material("M_SynthFlat", _build_flat_material)
    if "tiled" not in _CACHE["materials"]:
        _CACHE["materials"]["tiled"] = _new_material("M_SynthTiled", _build_tiled_material)
    if not _CACHE.get("materials_compiled"):
        for material in (_CACHE["materials"]["flat"], _CACHE["materials"]["tiled"]):
            force_compile_material(material)
        _CACHE["materials_compiled"] = True
    return _CACHE["materials"]


def flat_mid(world, color, roughness=0.8):
    mats = ensure_materials()
    key = ("flat",) + tuple(round(float(c), 4) for c in color) + (round(float(roughness), 3),)
    if key not in _CACHE["mids"]:
        material_library = module_class("MaterialLibrary", "KismetMaterialLibrary")
        if material_library is None:
            return mats["flat"]
        mid = material_library.create_dynamic_material_instance(world, mats["flat"])
        mid.set_vector_parameter_value("BaseColor", unreal.LinearColor(color[0], color[1], color[2], 1.0))
        mid.set_scalar_parameter_value("Roughness", roughness)
        _CACHE["mids"][key] = mid
    return _CACHE["mids"][key]


def tiled_mid(world, texture_key, tint=(1.0, 1.0, 1.0), uv_scale=1.0, roughness=0.85):
    tex = get_texture(texture_key)
    if tex is None:
        return flat_mid(world, tint if tint else (0.7, 0.7, 0.7), roughness)
    mats = ensure_materials()
    key = ("tiled", texture_key) + tuple(round(float(c), 4) for c in tint) + (
        round(float(uv_scale), 3), round(float(roughness), 3))
    if key not in _CACHE["mids"]:
        material_library = module_class("MaterialLibrary", "KismetMaterialLibrary")
        if material_library is None:
            return mats["tiled"]
        mid = material_library.create_dynamic_material_instance(world, mats["tiled"])
        mid.set_texture_parameter_value("BaseTex", tex)
        mid.set_vector_parameter_value("Tint", unreal.LinearColor(tint[0], tint[1], tint[2], 1.0))
        mid.set_scalar_parameter_value("UVScale", uv_scale)
        mid.set_scalar_parameter_value("Roughness", roughness)
        _CACHE["mids"][key] = mid
    return _CACHE["mids"][key]


def import_textures():
    """Import the PNGs generated by gen_textures.py; returns True/False."""
    names = ("T_Grass", "T_Asphalt", "T_Concrete", "T_Paving", "T_FacadeA", "T_FacadeB", "T_Glass", "T_Roof")
    if not os.path.isdir(TEXTURE_SRC_DIR):
        log_warn("texture source dir missing: %s" % TEXTURE_SRC_DIR)
        return False
    make_asset_dir(TEXTURE_DIR)
    tasks = []
    for name in names:
        png = os.path.join(TEXTURE_SRC_DIR, name + ".png")
        if not os.path.isfile(png):
            log_warn("missing texture png: %s" % png)
            continue
        if asset_exists(TEXTURE_DIR + "/" + name):
            load_asset(TEXTURE_DIR + "/" + name)
            continue
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", png)
        task.set_editor_property("destination_path", TEXTURE_DIR)
        task.set_editor_property("destination_name", name)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        tasks.append(task)
    if tasks:
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        asset_tools.import_asset_tasks(tasks)
        log("imported %d textures" % len(tasks))
    for name in names:
        load_asset(TEXTURE_DIR + "/" + name)
    ok = all(get_texture(n) is not None for n in names)
    log("textures ready=%s" % ok)
    return ok


def get_texture(name):
    if name not in _CACHE["textures"]:
        _CACHE["textures"][name] = load_asset(TEXTURE_DIR + "/" + name)
    return _CACHE["textures"][name]


# ------------------------------------------------------------------------- actor spawn
def spawn_actor(world, actor_class, location, rotation=None, label=None):
    rot = rotation or unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0)
    actor = actor_subsystem().spawn_actor_from_class(actor_class, location, rot)
    if actor is None:
        log_warn("spawn failed for %s" % actor_class)
        return None
    if label:
        try:
            actor.set_actor_label(label)
        except Exception:
            pass
    return actor


def spawn_mesh(world, mesh, location, rotation=None, scale=(1.0, 1.0, 1.0), material=None, label=None):
    actor = spawn_actor(world, unreal.StaticMeshActor, location, rotation, label)
    if actor is None:
        return None
    component = actor.get_editor_property("static_mesh_component")
    if component is None:
        try:
            component = actor.get_components_by_class(unreal.StaticMeshComponent)[0]
        except Exception:
            component = None
    if component is None:
        log_warn("no static mesh component on spawned actor")
        return actor
    if mesh is not None:
        component.set_static_mesh(mesh)
    actor.set_actor_scale3d(unreal.Vector(float(scale[0]), float(scale[1]), float(scale[2])))
    if material is not None:
        component.set_material(0, material)
    return actor


def spawn_box(world, center, size_cm, material=None, yaw=0.0, label=None, mesh="Cube"):
    scale = (size_cm[0] / 100.0, size_cm[1] / 100.0, size_cm[2] / 100.0)
    rot = unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw)
    return spawn_mesh(world, get_engine_mesh(mesh), unreal.Vector(center[0], center[1], center[2]),
                      rot, scale, material, label)


def spawn_cylinder(world, center, size_cm, material=None, yaw=0.0, label=None):
    scale = (size_cm[0] / 100.0, size_cm[1] / 100.0, size_cm[2] / 100.0)
    rot = unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw)
    return spawn_mesh(world, get_engine_mesh("Cylinder"), unreal.Vector(center[0], center[1], center[2]),
                      rot, scale, material, label)


def spawn_sphere(world, center, size_cm, material=None, label=None):
    scale = (size_cm[0] / 100.0, size_cm[1] / 100.0, size_cm[2] / 100.0)
    return spawn_mesh(world, get_engine_mesh("Sphere"), unreal.Vector(center[0], center[1], center[2]),
                      None, scale, material, label)


# --------------------------------------------------------------------------- scene build
def _segments(centers, half_width, half_area):
    bounds = [-half_area]
    for c in centers:
        bounds.extend([c - half_width, c + half_width])
    bounds.append(half_area)
    segs = []
    i = 0
    while i + 1 < len(bounds):
        a, b = bounds[i], bounds[i + 1]
        if b - a > 100.0:
            segs.append((a, b))
        i += 2
    return segs


def _add_building(world, rng, cx, cy, w, d, h, label, facade_tex, tint):
    base_z = PLOT_TOP_CM
    uv = max(w, d, h) / 800.0
    mat = tiled_mid(world, facade_tex, tint, uv, 0.82)
    spawn_box(world, (cx, cy, base_z + h * 0.5), (w, d, h), mat, label=label + "_Body")
    roof_mat = tiled_mid(world, "T_Roof", (0.62, 0.62, 0.60), max(w, d) / 600.0, 0.9)
    spawn_box(world, (cx, cy, base_z + h + 12.0), (w * 1.02, d * 1.02, 24.0), roof_mat,
              label=label + "_Roof")
    for i in range(rng.randint(1, 3)):
        rw = rng.uniform(150.0, 350.0)
        rd = rng.uniform(150.0, 350.0)
        rh = rng.uniform(80.0, 220.0)
        ox = rng.uniform(-w * 0.3, w * 0.3)
        oy = rng.uniform(-d * 0.3, d * 0.3)
        spawn_box(world, (cx + ox, cy + oy, base_z + h + 24.0 + rh * 0.5), (rw, rd, rh),
                  flat_mid(world, (0.55, 0.56, 0.57), 0.7), label=label + "_RoofUnit")
    side = rng.randint(0, 3)
    porch_mat = flat_mid(world, (0.42, 0.42, 0.44), 0.55)
    if side == 0:
        spawn_box(world, (cx + w * 0.5 + 60.0, cy, base_z + 160.0), (120.0, min(d * 0.5, 500.0), 320.0),
                  porch_mat, label=label + "_Porch")
    elif side == 1:
        spawn_box(world, (cx - w * 0.5 - 60.0, cy, base_z + 160.0), (120.0, min(d * 0.5, 500.0), 320.0),
                  porch_mat, label=label + "_Porch")
    elif side == 2:
        spawn_box(world, (cx, cy + d * 0.5 + 60.0, base_z + 160.0), (min(w * 0.5, 500.0), 120.0, 320.0),
                  porch_mat, label=label + "_Porch")
    else:
        spawn_box(world, (cx, cy - d * 0.5 - 60.0, base_z + 160.0), (min(w * 0.5, 500.0), 120.0, 320.0),
                  porch_mat, label=label + "_Porch")


def _add_tree(world, rng, x, y, z_base):
    trunk_h = rng.uniform(240.0, 420.0)
    canopy_r = rng.uniform(170.0, 300.0)
    canopy_h = rng.uniform(420.0, 700.0)
    trunk_mat = flat_mid(world, (0.27, 0.18, 0.11), 0.95)
    leaf_mat = flat_mid(world, rng.choice(PALETTE["leaf"]), 0.9)
    spawn_cylinder(world, (x, y, z_base + trunk_h * 0.5), (70.0, 70.0, trunk_h), trunk_mat,
                   label="SYNTH_Tree_Trunk")
    spawn_sphere(world, (x, y, z_base + trunk_h + canopy_h * 0.35),
                 (canopy_r * 2.0, canopy_r * 2.0, canopy_h), leaf_mat, label="SYNTH_Tree_Canopy")


def _add_car(world, rng, x, y, yaw, z_base):
    body = rng.choice(PALETTE["car"])
    spawn_box(world, (x, y, z_base + 72.0), (440.0, 180.0, 130.0),
              flat_mid(world, body, 0.35), yaw=yaw, label="SYNTH_Car")
    spawn_box(world, (x, y, z_base + 158.0), (250.0, 160.0, 62.0),
              flat_mid(world, (0.10, 0.12, 0.14), 0.2), yaw=yaw, label="SYNTH_CarCabin")


def _add_lamp(world, x, y, z_base, yaw=0.0):
    spawn_cylinder(world, (x, y, z_base + 300.0), (28.0, 28.0, 600.0),
                   flat_mid(world, (0.30, 0.31, 0.32), 0.6), label="SYNTH_LampPole")
    spawn_box(world, (x, y, z_base + 610.0), (160.0, 44.0, 22.0),
              flat_mid(world, (0.9, 0.88, 0.78), 0.4), yaw=yaw, label="SYNTH_LampHead")


def build_scene(world, sun_intensity=10.0):
    t0 = time.time()
    log("build_scene: start (seed=%d)" % SCENE_SEED)
    ensure_materials()
    import_textures()
    rng = random.Random(SCENE_SEED)

    # ---------------------------------------------------------------- ground / roads
    grass = tiled_mid(world, "T_Grass", (0.92, 1.0, 0.88), 16.0, 0.95)
    spawn_box(world, (0.0, 0.0, -20.0), (GROUND_CM, GROUND_CM, 40.0), grass, label="SYNTH_Ground")
    asphalt = tiled_mid(world, "T_Asphalt", (1.0, 1.0, 1.0), 10.0, 0.75)
    for x0 in ROAD_X:
        spawn_box(world, (x0, 0.0, 2.0), (ROAD_W_CM, GROUND_CM * 0.3, 4.0), asphalt,
                  label="SYNTH_RoadNS")
    for y0 in ROAD_Y:
        spawn_box(world, (0.0, y0, 2.0), (GROUND_CM * 0.3, ROAD_W_CM, 4.0), asphalt,
                  label="SYNTH_RoadEW")
    dash_mat = flat_mid(world, (0.85, 0.85, 0.82), 0.6)
    for x0 in ROAD_X:
        for i in range(-8, 9):
            spawn_box(world, (x0, i * 1100.0, 5.0), (60.0, 320.0, 3.0), dash_mat,
                      label="SYNTH_RoadDashNS")
    for y0 in ROAD_Y:
        for i in range(-8, 9):
            spawn_box(world, (i * 1100.0, y0, 5.0), (320.0, 60.0, 3.0), dash_mat,
                      label="SYNTH_RoadDashEW")

    # ---------------------------------------------------------------------- blocks
    x_segs = _segments(ROAD_X, ROAD_W_CM * 0.5, AREA_HALF_CM)
    y_segs = _segments(ROAD_Y, ROAD_W_CM * 0.5, AREA_HALF_CM)
    log("blocks: %d x %d" % (len(x_segs), len(y_segs)))
    facade_texs = ("T_FacadeA", "T_FacadeB", "T_FacadeA", "T_FacadeB", "T_Glass", "T_Concrete")
    paving = tiled_mid(world, "T_Paving", (0.92, 0.92, 0.90), 3.0, 0.9)
    plaza_rng = random.Random(SCENE_SEED + 77)
    for bi in range(len(x_segs)):
        for bj in range(len(y_segs)):
            x0, x1 = x_segs[bi]
            y0, y1 = y_segs[bj]
            w, d = x1 - x0, y1 - y0
            cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
            spawn_box(world, (cx, cy, PLOT_TOP_CM * 0.5), (w, d, PLOT_TOP_CM), paving,
                      label="SYNTH_Plot")
            if (bi, bj) == (1, 1):
                _build_park(world, rng, x0, x1, y0, y1)
            elif (bi, bj) == (2, 2):
                _build_plaza(world, plaza_rng, x0, x1, y0, y1)
            else:
                inner = w > 1500.0 and d > 1500.0
                nx = 2 if w > 1500.0 else 1
                ny = 2 if d > 1500.0 else 1
                gap = 90.0 if inner else 80.0
                for ix in range(nx):
                    for iy in range(ny):
                        pw = (w - gap * (nx + 1)) / nx
                        pd = (d - gap * (ny + 1)) / ny
                        if pw < 420.0 or pd < 420.0:
                            continue
                        px = x0 + gap + pw * 0.5 + ix * (pw + gap)
                        py = y0 + gap + pd * 0.5 + iy * (pd + gap)
                        bw = pw * rng.uniform(0.82, 0.96)
                        bd = pd * rng.uniform(0.82, 0.96)
                        bh = rng.uniform(1500.0, 3200.0) if inner else rng.uniform(900.0, 2400.0)
                        tex = rng.choice(facade_texs)
                        tint = rng.choice(PALETTE["facade"])
                        _add_building(world, rng, px, py, bw, bd, bh,
                                      "SYNTH_Bldg_%d_%d_%d_%d" % (bi, bj, ix, iy), tex, tint)
                        if rng.random() < 0.5:
                            spawn_box(world, (px, py + pd * 0.42, PLOT_TOP_CM + 35.0),
                                      (bw * rng.uniform(0.3, 0.7), 90.0, 70.0),
                                      flat_mid(world, (0.18, 0.40, 0.16), 0.9),
                                      label="SYNTH_Hedge")

    # ------------------------------------------------- perimeter filler buildings (rings)
    ring_rng = random.Random(SCENE_SEED + 991)
    for ring in range(3):
        radius = AREA_HALF_CM + 1400.0 + ring * 1700.0
        count = 14 + ring * 4
        for k in range(count):
            ang = (k + 0.4 * ring) / float(count) * 2.0 * math.pi
            x = math.cos(ang) * radius
            y = math.sin(ang) * radius
            bw = ring_rng.uniform(650.0, 1400.0)
            bd = ring_rng.uniform(650.0, 1400.0)
            bh = ring_rng.uniform(500.0, 1600.0)
            tex = ring_rng.choice(("T_FacadeB", "T_Concrete", "T_FacadeA"))
            tint = ring_rng.choice(PALETTE["facade"])
            _add_building(world, ring_rng, x, y, bw, bd, bh,
                          "SYNTH_Ring_%d_%d" % (ring, k), tex, tint)

    # ------------------------------------------------------------------- street trees
    for x0 in ROAD_X:
        for yy in range(-4200, 4300, 1500):
            if abs(yy) < 700.0:
                continue
            _add_tree(world, rng, x0 + ROAD_W_CM * 0.5 + 120.0, float(yy), 0.0)
    for y0 in ROAD_Y:
        for xx in range(-4200, 4300, 1500):
            if abs(xx) < 700.0:
                continue
            _add_tree(world, rng, float(xx), y0 + ROAD_W_CM * 0.5 + 120.0, 0.0)

    # ------------------------------------------------------------------------- cars
    for x0 in ROAD_X:
        for i in range(5):
            y = rng.uniform(-4000.0, 4000.0)
            if abs(y) < 900.0:
                continue
            lane = rng.choice((-1.0, 1.0)) * ROAD_W_CM * 0.22
            _add_car(world, rng, x0 + lane, y, 0.0, 4.0)
    for y0 in ROAD_Y:
        for i in range(5):
            x = rng.uniform(-4000.0, 4000.0)
            if abs(x) < 900.0:
                continue
            lane = rng.choice((-1.0, 1.0)) * ROAD_W_CM * 0.22
            _add_car(world, rng, x, y0 + lane, 90.0, 4.0)

    # -------------------------------------------------------------------- street lamps
    for x0 in ROAD_X:
        for yy in range(-3800, 4000, 1900):
            _add_lamp(world, x0 - ROAD_W_CM * 0.5 - 90.0, float(yy), 0.0)
    for y0 in ROAD_Y:
        for xx in range(-3800, 4000, 1900):
            _add_lamp(world, float(xx), y0 - ROAD_W_CM * 0.5 - 90.0, 0.0, yaw=90.0)

    # ------------------------------------------------------------- calibration markers
    for idx, (mx, my, mz) in enumerate(MARKER_POSITIONS):
        spawn_box(world, (mx, my, mz + 60.0), (120.0, 120.0, 120.0),
                  flat_mid(world, MARKER_COLOR, 0.35), label="SYNTH_Marker_%d" % idx)
    for idx, (mx, my) in enumerate(CALIB_MARKERS):
        spawn_box(world, (mx, my, CALIB_MARKER_BASE_Z_CM + CALIB_MARKER_SIZE_CM * 0.5),
                  (CALIB_MARKER_SIZE_CM, CALIB_MARKER_SIZE_CM, CALIB_MARKER_SIZE_CM),
                  flat_mid(world, MARKER_COLOR, 0.35), label="SYNTH_CalibMarker_%d" % idx)

    _add_lighting(world, sun_intensity)
    log("build_scene: done in %.1fs" % (time.time() - t0))
    return True


def _build_park(world, rng, x0, x1, y0, y1):
    cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    pond = flat_mid(world, (0.05, 0.18, 0.28), 0.08)
    spawn_cylinder(world, (cx, cy, PLOT_TOP_CM + 12.0), (1200.0, 1200.0, 24.0), pond,
                   label="SYNTH_Pond")
    for i in range(22):
        _add_tree(world, rng, rng.uniform(x0 + 400.0, x1 - 400.0), rng.uniform(y0 + 400.0, y1 - 400.0),
                  PLOT_TOP_CM)
    path_mat = tiled_mid(world, "T_Paving", (0.88, 0.86, 0.82), 2.0, 0.9)
    spawn_box(world, (cx, cy, PLOT_TOP_CM + 4.0), (x1 - x0 - 200.0, 260.0, 8.0), path_mat,
              label="SYNTH_ParkPath")
    spawn_box(world, (cx, cy, PLOT_TOP_CM + 4.0), (260.0, y1 - y0 - 200.0, 8.0), path_mat,
              label="SYNTH_ParkPath")


def _build_plaza(world, rng, x0, x1, y0, y1):
    cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    plaza_mat = tiled_mid(world, "T_Concrete", (0.95, 0.93, 0.90), 2.5, 0.8)
    spawn_cylinder(world, (cx, cy, PLOT_TOP_CM + 10.0), (2600.0, 2600.0, 20.0), plaza_mat,
                   label="SYNTH_Plaza")
    water = flat_mid(world, (0.06, 0.20, 0.30), 0.05)
    spawn_cylinder(world, (cx, cy, PLOT_TOP_CM + 40.0), (900.0, 900.0, 60.0), water,
                   label="SYNTH_FountainBasin")
    stone = flat_mid(world, (0.78, 0.76, 0.72), 0.6)
    spawn_cylinder(world, (cx, cy, PLOT_TOP_CM + 130.0), (320.0, 320.0, 200.0), stone,
                   label="SYNTH_FountainPillar")
    spawn_sphere(world, (cx, cy, PLOT_TOP_CM + 300.0), (300.0, 300.0, 300.0),
                 flat_mid(world, (0.85, 0.55, 0.12), 0.4), label="SYNTH_FountainOrb")
    art_colors = ((0.85, 0.15, 0.12), (0.10, 0.35, 0.80), (0.92, 0.72, 0.10),
                  (0.20, 0.65, 0.30), (0.80, 0.30, 0.70))
    for i in range(5):
        ang = i * 2.0 * math.pi / 5.0
        px = cx + math.cos(ang) * 2100.0
        py = cy + math.sin(ang) * 2100.0
        spawn_box(world, (px, py, PLOT_TOP_CM + 100.0), (190.0, 190.0, 200.0),
                  flat_mid(world, art_colors[i], 0.45), yaw=float(i * 17),
                  label="SYNTH_PlazaArt")
    bench_mat = flat_mid(world, (0.35, 0.24, 0.15), 0.8)
    for i in range(8):
        ang = i * math.pi / 4.0
        px = cx + math.cos(ang) * 1500.0
        py = cy + math.sin(ang) * 1500.0
        spawn_box(world, (px, py, PLOT_TOP_CM + 40.0), (260.0, 80.0, 80.0), bench_mat,
                  yaw=float(math.degrees(ang)), label="SYNTH_Bench")
    for i in range(10):
        _add_tree(world, rng, rng.uniform(x0 + 500.0, x1 - 500.0), rng.uniform(y0 + 500.0, y1 - 500.0),
                  PLOT_TOP_CM)


def _add_lighting(world, sun_intensity=10.0):
    """Sky atmosphere first, then sun, sky light (real-time capture), fog and fill lights.

    The sky atmosphere has to exist before the sky light captures the scene, otherwise the
    captured sky light is black and shadowed areas render pitch black.
    """
    # 1) sky atmosphere (needs to exist before the directional light for the sun disk)
    spawn_actor(world, unreal.SkyAtmosphere, unreal.Vector(0.0, 0.0, 0.0),
                unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0), label="SYNTH_SkyAtmosphere")
    # 2) sun
    sun_rotator = unreal.Rotator(roll=0.0, pitch=-42.0, yaw=35.0)
    sun = spawn_actor(world, unreal.DirectionalLight, unreal.Vector(0.0, 0.0, 6000.0), sun_rotator,
                      label="SYNTH_Sun")
    if sun:
        comps = sun.get_components_by_class(unreal.DirectionalLightComponent)
        if comps:
            comp = comps[0]
            _try(comp.set_editor_property, "mobility", enum_entry(unreal.ComponentMobility, "MOVABLE", "Movable"))
            _try(comp.set_editor_property, "intensity", float(sun_intensity))
            _try(comp.set_editor_property, "atmosphere_sun_light", True)
            _try(comp.set_editor_property, "light_color", unreal.Color(r=255, g=247, b=235, a=255))
            _try(comp.set_editor_property, "cast_shadows", True)
            _CACHE["lighting"]["sun"] = comp
    # 3) shadowless fill lights (cheap stand-in for sky ambient, keeps shadows from going black)
    fill_specs = (
        (-28.0, 200.0, 0.13, (190, 208, 255)),
        (-28.0, 320.0, 0.13, (190, 208, 255)),
        (-70.0, 110.0, 0.10, (235, 235, 225)),
    )
    for index, (pitch, yaw, factor, color) in enumerate(fill_specs):
        fill = spawn_actor(world, unreal.DirectionalLight, unreal.Vector(0.0, 0.0, 5500.0),
                           unreal.Rotator(roll=0.0, pitch=pitch, yaw=yaw),
                           label="SYNTH_FillLight_%d" % index)
        if not fill:
            continue
        comps = fill.get_components_by_class(unreal.DirectionalLightComponent)
        if not comps:
            continue
        comp = comps[0]
        _try(comp.set_editor_property, "mobility", enum_entry(unreal.ComponentMobility, "MOVABLE", "Movable"))
        _try(comp.set_editor_property, "intensity", float(sun_intensity) * factor)
        _try(comp.set_editor_property, "cast_shadows", False)
        _try(comp.set_editor_property, "atmosphere_sun_light", False)
        _try(comp.set_editor_property, "light_color", unreal.Color(r=color[0], g=color[1], b=color[2], a=255))
    # 4) sky light with real-time capture
    sky = spawn_actor(world, unreal.SkyLight, unreal.Vector(0.0, 0.0, 4000.0),
                      unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0), label="SYNTH_SkyLight")
    if sky:
        comps = sky.get_components_by_class(unreal.SkyLightComponent)
        if comps:
            comp = comps[0]
            _try(comp.set_editor_property, "mobility", enum_entry(unreal.ComponentMobility, "MOVABLE", "Movable"))
            _try(comp.set_editor_property, "real_time_capture", True)
            _try(comp.set_editor_property, "intensity", 1.0)
            _try(comp.recapture_sky)
            for prop in ("mobility", "real_time_capture", "intensity", "source_type"):
                try:
                    log("sky light %s = %s" % (prop, comp.get_editor_property(prop)))
                except Exception as exc:
                    log_warn("sky light prop %s read failed: %s" % (prop, exc))
            _CACHE["lighting"]["sky"] = comp
    # 5) height fog for depth cue
    fog = spawn_actor(world, unreal.ExponentialHeightFog, unreal.Vector(0.0, 0.0, 0.0),
                      unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0), label="SYNTH_Fog")
    if fog:
        comps = fog.get_components_by_class(unreal.ExponentialHeightFogComponent)
        if comps:
            _try(comps[0].set_editor_property, "fog_density", 0.0035)
            _CACHE["lighting"]["fog"] = comps[0]
    log("lighting added (sun=%.1f lux, 3 shadowless fill lights)" % sun_intensity)


def clear_generated(world):
    removed = 0
    for actor in actor_subsystem().get_all_level_actors():
        try:
            label = actor.get_actor_label()
        except Exception:
            continue
        if label and label.startswith(LABEL_PREFIX):
            actor_subsystem().destroy_actor(actor)
            removed += 1
    log("cleared %d generated actors" % removed)


def count_generated(world=None):
    count = 0
    for actor in actor_subsystem().get_all_level_actors():
        try:
            if actor.get_actor_label().startswith(LABEL_PREFIX):
                count += 1
        except Exception:
            continue
    return count


# ------------------------------------------------------------------------- level flow
def ensure_level(rebuild=False):
    """Return the current editor world.

    The campus scene is regenerated on every run (it only takes ~1 s for ~500 actors) so
    the tool does not depend on a saved level asset; this keeps the pipeline deterministic
    and avoids stale transient MaterialInstanceDynamic references when a level is reloaded.
    Works both with the full editor and with the headless pythonscript commandlet.
    """
    world = get_editor_world()
    if world is None:
        raise RuntimeError("no editor world available")
    log("editor world: %s" % world.get_name())
    return world


def ensure_scene(rebuild=False, sun_intensity=10.0):
    world = ensure_level(rebuild=rebuild)
    existing = count_generated(world)
    log("generated actors in world: %d" % existing)
    if rebuild or existing < 50:
        if existing:
            clear_generated(world)
        build_scene(world, sun_intensity=sun_intensity)
    else:
        log("reusing %d generated actors already in the world" % existing)
    return world


# -------------------------------------------------------------------- flight planning
def ground_footprint_cm(pitch_deg, alt_cm):
    """Approximate ground footprint (across, along) of one camera in cm."""
    h = float(alt_cm)
    pitch = abs(float(pitch_deg))
    half_v = FOV_V_DEG * 0.5
    if pitch <= half_v:
        return 0.0, 0.0
    near = h / math.tan(math.radians(pitch + half_v))
    far = h / math.tan(math.radians(pitch - half_v))
    along = abs(far - near)
    width = 2.0 * (h / math.tan(math.radians(pitch))) * math.tan(math.radians(FOV_H_DEG * 0.5))
    return width, along


def overlap_stats():
    along_spacing = 2.0 * AREA_HALF_CM / float(GRID_SHOTS - 1)
    across_spacing = 2.0 * AREA_HALF_CM / float(GRID_LINES - 1)
    stats = []
    for yaw, pitch, alt in PASSES:
        width, along = ground_footprint_cm(pitch, alt)
        stats.append({
            "yaw_deg": yaw,
            "gimbal_pitch_deg": pitch,
            "altitude_cm": alt,
            "footprint_across_cm": round(width, 1),
            "footprint_along_cm": round(along, 1),
            "across_spacing_cm": round(across_spacing, 1),
            "along_spacing_cm": round(along_spacing, 1),
            "side_overlap": round(1.0 - across_spacing / width, 4) if width else None,
            "heading_overlap": round(1.0 - along_spacing / along, 4) if along else None,
        })
    return stats


def generate_train_poses():
    poses = []
    idx = 1
    along_spacing = 2.0 * AREA_HALF_CM / float(GRID_SHOTS - 1)
    across_spacing = 2.0 * AREA_HALF_CM / float(GRID_LINES - 1)
    for pass_index, (yaw, pitch, alt) in enumerate(PASSES):
        yaw_r = math.radians(yaw)
        ux, uy = math.cos(yaw_r), math.sin(yaw_r)
        vx, vy = -math.sin(yaw_r), math.cos(yaw_r)
        for li in range(GRID_LINES):
            across = (li - (GRID_LINES - 1) * 0.5) * across_spacing
            for si in range(GRID_SHOTS):
                along = (si - (GRID_SHOTS - 1) * 0.5) * along_spacing
                x = ux * along + vx * across
                y = uy * along + vy * across
                poses.append({
                    "loc": (x, y, alt),
                    "yaw": yaw,
                    "pitch": pitch,
                    "roll": 0.0,
                    "index": idx,
                    "timestamp": float((idx - 1) * 2.0),
                    "pass": pass_index,
                    "prefix": "",
                })
                idx += 1
    return poses


def generate_val_poses(count=VAL_COUNT):
    rng = random.Random(SCENE_SEED + 4242)
    train = generate_train_poses()
    poses = []
    idx = 1
    attempts = 0
    while len(poses) < count and attempts < count * 200:
        attempts += 1
        x = rng.uniform(-AREA_HALF_CM, AREA_HALF_CM)
        y = rng.uniform(-AREA_HALF_CM, AREA_HALF_CM)
        alt = rng.uniform(3200.0, 4800.0)
        pitch = rng.choice((-45.0, -48.0, -51.0, -54.0, -57.0, -60.0))
        yaw = rng.uniform(0.0, 360.0)
        ok = True
        for train_pose in train:
            tx, ty, tz = train_pose["loc"]
            if (x - tx) ** 2 + (y - ty) ** 2 < 500.0 ** 2 and abs(alt - tz) < 400.0:
                ok = False
                break
        if not ok:
            continue
        poses.append({
            "loc": (x, y, alt),
            "yaw": yaw,
            "pitch": pitch,
            "roll": 0.0,
            "index": idx,
            "timestamp": float((idx - 1) * 2.0),
            "pass": -1,
            "prefix": "val_",
        })
        idx += 1
    return poses


def generate_calib_poses(alt_cm=2500.0):
    """Near-nadir frames over the calibration targets (used to verify reprojection)."""
    poses = []
    for i, (mx, my) in enumerate(CALIB_MARKERS):
        offx, offy = CALIB_CAMERA_OFFSETS_CM[i % len(CALIB_CAMERA_OFFSETS_CM)]
        poses.append({
            "loc": (mx + offx, my + offy, alt_cm),
            "yaw": 0.0,
            "pitch": -90.0,
            "roll": 0.0,
            "index": i + 1,
            "timestamp": float(i),
            "pass": -1,
            "prefix": "calib_",
            "target_ue_cm": [mx, my, CALIB_MARKER_BASE_Z_CM + CALIB_MARKER_SIZE_CM * 0.5],
            "target_size_cm": CALIB_MARKER_SIZE_CM,
        })
    return poses


# ------------------------------------------------------- pose -> c2w / GPS / gimbal
def rotator_axes(yaw_deg, pitch_deg, roll_deg=0.0):
    """Return UE camera axes (forward, right, up) for a rotator.

    Derived from the UE FRotator quaternion with roll = 0 (the gimbal roll used by this
    tool is always 0):
        forward = ( cos(p)cos(y),  cos(p)sin(y),  sin(p))
        right   = (-sin(y),        cos(y),        0     )
        up      = (-sin(p)cos(y), -sin(p)sin(y),  cos(p))
    These three vectors are orthonormal, which is required for the exported c2w.
    """
    y = math.radians(yaw_deg)
    p = math.radians(pitch_deg)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    forward = (cp * cy, cp * sy, sp)
    right = (-sy, cy, 0.0)
    up = (-sp * cy, -sp * sy, cp)
    return forward, right, up


def c2w_from_pose(loc_cm, yaw_deg, pitch_deg, roll_deg=0.0):
    forward, right, up = rotator_axes(yaw_deg, pitch_deg, roll_deg)
    tx, ty, tz = (float(loc_cm[0]), float(loc_cm[1]), float(loc_cm[2]))
    return [
        float(forward[0]), float(right[0]), float(up[0]), tx,
        float(forward[1]), float(right[1]), float(up[1]), ty,
        float(forward[2]), float(right[2]), float(up[2]), tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def ue_to_wgs84(loc_cm):
    east_m = float(loc_cm[0]) / 100.0
    north_m = -float(loc_cm[1]) / 100.0
    up_m = float(loc_cm[2]) / 100.0
    lat = ORIGIN_WGS84["lat"] + north_m / M_PER_DEG_LAT
    lon = ORIGIN_WGS84["lon"] + east_m / (M_PER_DEG_LAT * math.cos(math.radians(ORIGIN_WGS84["lat"])))
    return {
        "lat": round(lat, 9),
        "lon": round(lon, 9),
        "alt": round(ORIGIN_WGS84["alt"] + up_m, 4),
    }


# ------------------------------------------------------------------- capture / render
def create_render_target(world):
    fmt = enum_entry(unreal.TextureRenderTargetFormat, "RTF_RGBA8", "RGBA8")
    rendering_library = module_class("RenderingLibrary", "KismetRenderingLibrary")
    if rendering_library is not None:
        try:
            rt = rendering_library.create_render_target2d(
                world, WIDTH, HEIGHT, fmt, unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
            if rt is not None:
                log("render target created through %s" % rendering_library)
                return rt
        except Exception as exc:
            log_warn("create_render_target2d failed: %s" % exc)
    rt = unreal.new_object(unreal.TextureRenderTarget2D, world)
    rt.set_editor_property("clear_color", unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
    rt.init_custom_format(WIDTH, HEIGHT, enum_entry(unreal.PixelFormat, "PF_B8G8R8A8", "B8G8R8A8"), False)
    return rt


def apply_capture_post_process(comp, exposure=0.6):
    pp = comp.get_editor_property("post_process_settings")

    def sp(name, value):
        try:
            pp.set_editor_property(name, value)
        except Exception as exc:
            log_warn("post process '%s' failed: %s" % (name, exc))

    sp("override_auto_exposure_method", True)
    sp("auto_exposure_method", enum_entry(unreal.AutoExposureMethod, "AEM_HISTOGRAM", "HISTOGRAM"))
    sp("override_auto_exposure_min_brightness", True)
    sp("auto_exposure_min_brightness", float(exposure))
    sp("override_auto_exposure_max_brightness", True)
    sp("auto_exposure_max_brightness", float(exposure))
    sp("override_auto_exposure_bias", True)
    sp("auto_exposure_bias", 0.0)
    sp("override_motion_blur_amount", True)
    sp("motion_blur_amount", 0.0)
    sp("override_bloom_intensity", True)
    sp("bloom_intensity", 0.0)
    sp("override_vignette_intensity", True)
    sp("vignette_intensity", 0.0)
    sp("override_film_grain_intensity", True)
    sp("film_grain_intensity", 0.0)
    sp("override_scene_fringe_intensity", True)
    sp("scene_fringe_intensity", 0.0)
    comp.set_editor_property("post_process_settings", pp)
    _try(comp.set_editor_property, "post_process_blend_weight", 1.0)


def create_capture_rig(world, exposure=0.6):
    actor = spawn_actor(world, unreal.SceneCapture2D, unreal.Vector(0.0, 0.0, 4000.0),
                        unreal.Rotator(roll=0.0, pitch=-45.0, yaw=0.0), label="SYNTH_CaptureDevice")
    component = None
    for prop_name in ("capture_component2d", "capture_component_2d", "capture_component"):
        try:
            component = actor.get_editor_property(prop_name)
        except Exception:
            component = None
        if component is not None:
            log("capture component property: %s" % prop_name)
            break
    if component is None:
        component = actor.get_components_by_class(unreal.SceneCaptureComponent2D)[0]
    _try(component.set_editor_property, "projection_type", enum_entry(unreal.CameraProjectionMode, "PERSPECTIVE"))
    _try(component.set_editor_property, "fov_angle", FOV_H_DEG)
    _try(component.set_editor_property, "capture_source", enum_entry(unreal.SceneCaptureSource, "SCS_FINAL_COLOR_LDR"))
    _try(component.set_editor_property, "capture_every_frame", False)
    _try(component.set_editor_property, "capture_on_movement", False)
    _try(component.set_editor_property, "always_persist_rendering_state", False)
    _try(component.set_editor_property, "use_custom_projection_matrix", False)
    render_target = create_render_target(world)
    component.set_editor_property("texture_target", render_target)
    apply_capture_post_process(component, exposure)
    log("capture rig ready: %dx%d fov=%.3f fx=%.3f" % (WIDTH, HEIGHT, FOV_H_DEG, FX))
    return actor, component, render_target


def render_pose(world, actor, component, render_target, pose, images_dir):
    location = unreal.Vector(float(pose["loc"][0]), float(pose["loc"][1]), float(pose["loc"][2]))
    rotation = unreal.Rotator(roll=float(pose.get("roll", 0.0)), pitch=float(pose["pitch"]),
                              yaw=float(pose["yaw"]))
    actor.set_actor_location(location, False, True)
    actor.set_actor_rotation(rotation, True)
    file_name = "%s%04d.png" % (pose.get("prefix", ""), int(pose["index"]))
    full_path = os.path.join(images_dir, file_name)
    if os.path.isfile(full_path):
        os.remove(full_path)
    t0 = time.perf_counter()
    component.capture_scene()
    rendering_library = module_class("RenderingLibrary", "KismetRenderingLibrary")
    rendering_library.export_render_target(world, render_target, images_dir, file_name)
    elapsed = time.perf_counter() - t0
    ok = os.path.isfile(full_path) and os.path.getsize(full_path) > 1024
    return ok, elapsed, file_name, full_path


def render_frames(world, poses, images_dir, exposure=0.6, label="train", metadata_prefix="images/"):
    ensure_dir(images_dir)
    actor, component, render_target = create_capture_rig(world, exposure)
    frames = []
    times = []
    total_t0 = time.perf_counter()
    for i, pose in enumerate(poses):
        ok, elapsed, file_name, full_path = render_pose(world, actor, component, render_target,
                                                        pose, images_dir)
        times.append(elapsed)
        if not ok:
            log_warn("frame %s failed (no file)" % file_name)
        frame = {
            "file": metadata_prefix + file_name,
            "c2w": c2w_from_pose(pose["loc"], pose["yaw"], pose["pitch"], pose.get("roll", 0.0)),
            "gps": ue_to_wgs84(pose["loc"]),
            "gimbal_deg": {
                "yaw": round(float(pose["yaw"]), 4),
                "pitch": round(float(pose["pitch"]), 4),
                "roll": round(float(pose.get("roll", 0.0)), 4),
            },
            "timestamp": float(pose["timestamp"]),
        }
        if pose.get("target_ue_cm") is not None:
            frame["target_ue_cm"] = [float(v) for v in pose["target_ue_cm"]]
            frame["target_size_cm"] = float(pose.get("target_size_cm", 0.0))
        frames.append(frame)
        if (i + 1) % 10 == 0 or (i + 1) == len(poses):
            avg = sum(times) / len(times)
            log("rendered %d/%d %s frames (avg %.3fs/frame, last %.3fs) -> %s" % (
                i + 1, len(poses), label, avg, elapsed, file_name))
    total = time.perf_counter() - total_t0
    log("render_frames[%s]: %d frames in %.2fs (avg %.3fs)" % (
        label, len(poses), total, (sum(times) / len(times)) if times else 0.0))
    try:
        actor_subsystem().destroy_actor(actor)
    except Exception:
        pass
    return frames, {"frames": len(poses), "total_seconds": round(total, 3),
                    "avg_frame_seconds": round(sum(times) / len(times), 4) if times else None}


def engine_version():
    try:
        return unreal.SystemLibrary.get_engine_version()
    except Exception:
        return "unknown"


def base_metadata(frame_count):
    return {
        "dataset": "synthetic_dji_mini4pro_campus_v1",
        "camera_model": "DJI Mini 4 Pro (simulated)",
        "width": WIDTH,
        "height": HEIGHT,
        "fx": round(FX, 4),
        "fy": round(FY, 4),
        "cx": round(CX, 4),
        "cy": round(CY, 4),
        "coord_system": "UE_LHS_Zup_cm",
        "origin_wgs84": dict(ORIGIN_WGS84),
        "sensor_mm": {"width": SENSOR_W_MM, "height": SENSOR_H_MM, "diagonal": round(SENSOR_DIAG_MM, 4)},
        "focal_mm": round(FOCAL_MM, 4),
        "equivalent_focal_mm": EQUIV_FOCAL_MM,
        "fov_deg": {"diagonal": FOV_DIAG_DEG, "horizontal": round(FOV_H_DEG, 4),
                    "vertical": round(FOV_V_DEG, 4)},
        "units": "cm / degrees",
        "generator": {
            "tool": "capture/scripts/capture_synth.py",
            "ue_version": engine_version(),
            "scene": "procedural campus (Blueprint-only UE5.8 project, no third-party assets)",
            "scene_seed": SCENE_SEED,
            "frame_count": frame_count,
        },
        "flight": {
            "area_half_cm": AREA_HALF_CM,
            "grid_lines": GRID_LINES,
            "grid_shots": GRID_SHOTS,
            "passes": overlap_stats(),
        },
        "notes": (
            "Simulated DJI Mini 4 Pro RGB capture rendered with SceneCapture2D in UE5.8. "
            "fx=fy derived from official 82.1 deg diagonal FOV on a 1/1.3 inch 4:3 sensor "
            "(9.6x7.2 mm active area, f=%.3f mm actual). fx/fy at 1600x1200 = %.2f/%.2f px. "
            "c2w is 4x4 row-major, columns = [forward, right, up] camera axes in UE world (cm); "
            "camera axes follow UE convention (+X forward, +Y right, +Z up). "
            "GPS is simulated from local UE coords with UE +X = East, UE +Y = South, UE +Z = Up."
            % (FOCAL_MM, FX, FY)
        ),
    }


def write_json(path, payload):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    log("wrote %s" % path)
