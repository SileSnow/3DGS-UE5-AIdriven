"""diag_materials.py -- headless check of generated materials / textures / material assignment."""
import unreal


def p(*a):
    line = "[DIAGM] " + " ".join(str(x) for x in a)
    print(line)
    try:
        unreal.log(line)
    except Exception:
        pass


mel = unreal.MaterialEditingLibrary
for name in ("M_SynthFlat", "M_SynthTiled"):
    path = "/Game/Synth/Materials/" + name
    mat = unreal.EditorAssetLibrary.load_asset(path)
    p(name, "loaded:", mat)
    if not mat:
        continue
    errors = mel.recompile_material(mat)
    p(name, "recompile errors:", list(errors) if errors else [])
    exprs = mel.get_material_expressions(mat)
    p(name, "num expressions:", len(exprs))
    for e in exprs:
        p("   expr:", e.get_class().get_name(), e.get_name())
    for prop in ("MP_BASE_COLOR", "MP_ROUGHNESS"):
        try:
            enum_val = getattr(unreal.MaterialProperty, prop)
            node = mel.get_material_property_input_node(mat, enum_val)
            out = mel.get_material_property_input_node_output_name(mat, enum_val)
            p(name, prop, "input:", node.get_class().get_name() if node else None, "output:", out)
        except Exception as exc:
            p(name, prop, "query failed:", exc)

for t in ("T_Grass", "T_FacadeA", "T_FacadeB", "T_Paving"):
    tex = unreal.EditorAssetLibrary.load_asset("/Game/Synth/Textures/" + t)
    size = None
    if tex:
        try:
            size = tex.get_editor_property("imported_size")
        except Exception as exc:
            size = "err:%s" % exc
    p("texture:", t, tex, size)

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
mesh = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube.Cube")
actor = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0),
                                   unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0))
comp = actor.get_editor_property("static_mesh_component")
comp.set_static_mesh(mesh)
mat = unreal.EditorAssetLibrary.load_asset("/Game/Synth/Materials/M_SynthFlat")
mid = unreal.MaterialLibrary.create_dynamic_material_instance(world, mat)
p("created MID:", mid)
if mid:
    mid.set_vector_parameter_value("BaseColor", unreal.LinearColor(0.1, 0.8, 0.1, 1.0))
    mid.set_scalar_parameter_value("Roughness", 0.5)
ok = comp.set_material(0, mid)
p("set_material(0, mid) ->", ok)
p("component material 0 ->", comp.get_material(0))
p("num material slots ->", comp.get_num_materials())
eas.destroy_actor(actor)
p("done")
