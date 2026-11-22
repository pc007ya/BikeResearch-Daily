"""ALSO-BIKE Studio Standard — Blender 4.x Import, Cyclorama & Multi-View QA Render Script.

Model      : G32 SuperFast (bikerumor-g32-superfast)
GLB SHA256 : 3b511b7468c3c40d2b4e6dc730c2b69bb9cceb1aacf369d05f83b7d04a5219bc
Geometry   : WB=1045.0mm | Reach=395.0mm | Stack=575.0mm | HTA=71.0deg | STA=73.5deg

Usage (headless or Blender GUI):
    blender -b --python bikerumor-g32-superfast_blender_rebuild.py -- --glb bikerumor-g32-superfast.glb --out ./renders_bikerumor-g32-superfast
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

EXPECTED_SHA256 = "3b511b7468c3c40d2b4e6dc730c2b69bb9cceb1aacf369d05f83b7d04a5219bc"


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", default="bikerumor-g32-superfast.glb")
    parser.add_argument("--out", default="./renders_bikerumor-g32-superfast")
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=900)
    return parser.parse_args(argv)


def setup_also_warm_cyclorama(scene):
    """Replicate ALSO_BIKE warm neutral cyclorama (0.78, 0.76, 0.72) + AgX + 3-point studio disk lights."""
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 32
    scene.eevee.use_raytracing = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    # World shader with camera ray split (ALSO standard)
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

    # Warm neutral cyclorama floor
    mat_floor = bpy.data.materials.new("ALSO_Warm_Neutral_Cyclorama")
    mat_floor.use_nodes = True
    bsdf = mat_floor.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.78, 0.76, 0.72, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.82
    bpy.ops.mesh.primitive_plane_add(size=120, location=(0.0, 0.0, 0.0))
    bpy.context.object.data.materials.append(mat_floor)

    # 3-Point physical jittered-shadow studio disk lights (Key, Fill, Rim)
    light_specs = [
        ("ALSO_Key", (1.6, -3.2, 3.8), 580.0, 3.0, (0.0, 0.0, 0.60)),
        ("ALSO_Fill", (-1.4, 2.2, 2.5), 260.0, 3.0, (0.0, 0.0, 0.60)),
        ("ALSO_Rim", (0.2, 1.8, 3.5), 420.0, 2.0, (0.0, 0.0, 0.68)),
    ]
    for name, loc, energy, size, target in light_specs:
        ldata = bpy.data.lights.new(name, "AREA")
        ldata.energy = energy
        ldata.shape = "DISK"
        ldata.size = size
        ldata.use_shadow = True
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
    assert actual_sha == EXPECTED_SHA256, f"SHA256 mismatch: {actual_sha} != {EXPECTED_SHA256}"

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))

    scene = bpy.context.scene
    setup_also_warm_cyclorama(scene)

    cam_data = bpy.data.cameras.new("ALSO_Ortho_Camera")
    cam_data.type = "ORTHO"
    cam_data.clip_start = 0.001
    cam_obj = bpy.data.objects.new("ALSO_Ortho_Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    # ALSO-style 7-view orthographic inspection rig (Z-up in Blender)
    views = [
        ("01_side_drive", (0.0, -4.0, 0.62), (0.0, 0.0, 0.56), 2.25),
        ("02_side_brake", (0.0, 4.0, 0.62), (0.0, 0.0, 0.56), 2.25),
        ("03_front", (4.0, 0.0, 0.68), (0.4, 0.0, 0.58), 1.45),
        ("04_rear", (-4.0, 0.0, 0.68), (-0.4, 0.0, 0.58), 1.45),
        ("05_front_45", (3.0, -3.0, 1.05), (0.0, 0.0, 0.55), 2.10),
        ("06_rear_45", (-3.0, 3.0, 1.05), (0.0, 0.0, 0.55), 2.10),
        ("07_cockpit", (0.15, -0.70, 1.65), (0.35, 0.0, 0.98), 0.95),
    ]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.eevee.taa_render_samples = args.samples

    for name, eye, target, scale in views:
        cam_obj.location = Vector(eye)
        cam_obj.rotation_euler = (Vector(target) - Vector(eye)).to_track_quat("-Z", "Y").to_euler()
        cam_data.ortho_scale = scale
        scene.render.filepath = str(out_dir / f"{name}.png")
        bpy.ops.render.render(write_still=True)

    # Save integrated .blend file alongside renders
    bpy.ops.wm.save_as_mainfile(filepath=str(out_dir / "bikerumor-g32-superfast_ALSO_studio.blend"))
    print(json.dumps({"status": "ok", "model": "bikerumor-g32-superfast", "sha256": actual_sha, "views": len(views)}))


if __name__ == "__main__":
    main()
