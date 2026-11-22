"""ALSO-BIKE Studio Standard — Blender 4.x Import, Cyclorama & Multi-View QA Render Script.

Model      : FOCUS AVENTURA² FS 6.9 (ebike-mtb-focus-aventura-fs-6-9)
GLB SHA256 : cfde87bbf408001ab726dd5041ee5e00067b696bf8f06a1ff2c2f84b3147f803
Geometry   : WB=1210.0mm | Reach=450.0mm | Stack=645.0mm | HTA=67.5deg | STA=75.5deg

Usage:
    blender -b --python ebike-mtb-focus-aventura-fs-6-9_blender_rebuild.py -- --glb ebike-mtb-focus-aventura-fs-6-9.glb --out ./renders_ebike-mtb-focus-aventura-fs-6-9
"""

import argparse, hashlib, json, sys
from pathlib import Path
import bpy
from mathutils import Vector

EXPECTED_SHA256 = "cfde87bbf408001ab726dd5041ee5e00067b696bf8f06a1ff2c2f84b3147f803"


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--glb", default="ebike-mtb-focus-aventura-fs-6-9.glb")
    p.add_argument("--out", default="./renders_ebike-mtb-focus-aventura-fs-6-9")
    p.add_argument("--samples", type=int, default=32)
    return p.parse_args(argv)


def setup_also_warm_cyclorama(scene):
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 32
    scene.eevee.use_raytracing = True
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"

    scene.world.use_nodes = True
    nt = scene.world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg_env = nt.nodes.new("ShaderNodeBackground")
    bg_env.inputs["Color"].default_value = (0.75, 0.72, 0.67, 1.0)
    bg_env.inputs["Strength"].default_value = 0.25
    bg_cam = nt.nodes.new("ShaderNodeBackground")
    bg_cam.inputs["Color"].default_value = (0.78, 0.76, 0.72, 1.0)
    bg_cam.inputs["Strength"].default_value = 1.0
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg_env.outputs[0], mix.inputs[1])
    nt.links.new(bg_cam.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])

    mat_floor = bpy.data.materials.new("ALSO_Warm_Neutral_Cyclorama")
    mat_floor.use_nodes = True
    bsdf = mat_floor.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.78, 0.76, 0.72, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.82
    bpy.ops.mesh.primitive_plane_add(size=120, location=(0.0, 0.0, 0.0))
    bpy.context.object.data.materials.append(mat_floor)

    for name, loc, energy, size, target in [
        ("ALSO_Key", (1.6, -3.2, 3.8), 580.0, 3.0, (0.0, 0.0, 0.60)),
        ("ALSO_Fill", (-1.4, 2.2, 2.5), 260.0, 3.0, (0.0, 0.0, 0.60)),
        ("ALSO_Rim", (0.2, 1.8, 3.5), 420.0, 2.0, (0.0, 0.0, 0.68)),
    ]:
        ldata = bpy.data.lights.new(name, "AREA")
        ldata.energy, ldata.shape, ldata.size, ldata.use_shadow = energy, "DISK", size, True
        if hasattr(ldata, "use_shadow_jitter"):
            ldata.use_shadow_jitter = True
        lobj = bpy.data.objects.new(name, ldata)
        scene.collection.objects.link(lobj)
        lobj.location = loc
        lobj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def main():
    args = parse_args()
    glb_path = Path(args.glb).resolve()
    actual_sha = hashlib.sha256(glb_path.read_bytes()).hexdigest()
    assert actual_sha == EXPECTED_SHA256, f"SHA256 mismatch: {actual_sha}"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    scene = bpy.context.scene
    setup_also_warm_cyclorama(scene)

    cam_data = bpy.data.cameras.new("ALSO_Ortho_Camera")
    cam_data.type = "ORTHO"
    cam_obj = bpy.data.objects.new("ALSO_Ortho_Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x, scene.render.resolution_y = 1200, 900
    scene.eevee.taa_render_samples = args.samples

    for name, eye, target, scale in [
        ("01_side_drive", (0.0, -4.0, 0.62), (0.0, 0.0, 0.56), 2.25),
        ("02_side_brake", (0.0, 4.0, 0.62), (0.0, 0.0, 0.56), 2.25),
        ("03_front", (4.0, 0.0, 0.68), (0.4, 0.0, 0.58), 1.45),
        ("04_rear", (-4.0, 0.0, 0.68), (-0.4, 0.0, 0.58), 1.45),
        ("05_front_45", (3.0, -3.0, 1.05), (0.0, 0.0, 0.55), 2.10),
        ("06_rear_45", (-3.0, 3.0, 1.05), (0.0, 0.0, 0.55), 2.10),
        ("07_cockpit", (0.15, -0.70, 1.65), (0.35, 0.0, 0.98), 0.95),
    ]:
        cam_obj.location = Vector(eye)
        cam_obj.rotation_euler = (Vector(target) - Vector(eye)).to_track_quat("-Z", "Y").to_euler()
        cam_data.ortho_scale = scale
        scene.render.filepath = str(out_dir / f"{name}.png")
        bpy.ops.render.render(write_still=True)

    bpy.ops.wm.save_as_mainfile(filepath=str(out_dir / "ebike-mtb-focus-aventura-fs-6-9_ALSO_studio.blend"))
    print(json.dumps({"status": "ok", "model": "ebike-mtb-focus-aventura-fs-6-9", "sha256": actual_sha}))


if __name__ == "__main__":
    main()
