"""diag_editor.py -- validate editor-world APIs needed by synth_common (runs headless)."""

import unreal


def p(*args):
    line = "[DIAG2] " + " ".join(str(a) for a in args)
    print(line)
    try:
        unreal.log(line)
    except Exception:
        pass


ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
p("UnrealEditorSubsystem", ues)
world = ues.get_editor_world() if ues else None
p("editor world", world, world.get_name() if world else None)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
p("EditorActorSubsystem", eas)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
p("LevelEditorSubsystem", les)

mesh = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube.Cube")
p("cube mesh", mesh)
if eas and world and mesh:
    actor = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0),
                                      unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0))
    p("spawned actor", actor)
    if actor:
        comp = actor.get_editor_property("static_mesh_component")
        p("static_mesh_component", comp)
        if comp:
            comp.set_static_mesh(mesh)
            p("set_static_mesh ok")
        actor.set_actor_scale3d(unreal.Vector(2.0, 2.0, 2.0))
        actor.set_actor_label("DIAG_Actor")
        p("actor label", actor.get_actor_label())
        p("all level actors", len(eas.get_all_level_actors()))
        eas.destroy_actor(actor)

try:
    rt = unreal.RenderingLibrary.create_render_target2d(
        world, 320, 240, unreal.TextureRenderTargetFormat.RTF_RGBA8,
        unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
    p("render target", rt, "size", rt.get_editor_property("size_x") if rt else None)
except Exception as exc:  # noqa: BLE001
    p("RT create failed", exc)

mat = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial")
p("basic shape material", mat)
try:
    mid = unreal.MaterialLibrary.create_dynamic_material_instance(world, mat)
    p("MID", mid)
    if mid:
        mid.set_scalar_parameter_value("Roughness", 0.5)
        mid.set_vector_parameter_value("BaseColor", unreal.LinearColor(1.0, 0.0, 1.0, 1.0))
        p("MID params set ok")
except Exception as exc:  # noqa: BLE001
    p("MID failed", exc)

try:
    p("current level", les.get_current_level() if les else None)
except Exception as exc:  # noqa: BLE001
    p("get_current_level failed", exc)

p("done")
