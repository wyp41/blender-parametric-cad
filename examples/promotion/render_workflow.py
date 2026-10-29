"""Render actual gear Sketch/Extrude/Through All history for the explainer."""
import importlib.util
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

OUT=Path(__file__).resolve().parent
repo=OUT.parents[1]
spec=importlib.util.spec_from_file_location('blender_parametric_cad',repo/'__init__.py',submodule_search_locations=[str(repo)])
addon=importlib.util.module_from_spec(spec);sys.modules['blender_parametric_cad']=addon
spec.loader.exec_module(addon);addon.register()
from blender_parametric_cad.blender import adapter, environments as env
from blender_parametric_cad.sketch.profile import ProfileDetector

bpy.ops.wm.open_mainfile(filepath=str(OUT.parent/'mechanisms/base_spur_gears.blend'))
document=adapter.load_document()
part=document.get_part('cff13979-fa1e-488f-ab8b-384a0a5de45a')
print('GEAR HISTORY',[(f.feature_type,f.name) for f in part.features],flush=True)
scene=bpy.data.scenes.new('Workflow render')
bpy.context.window.scene=scene
world=bpy.data.worlds.new('Workflow background');world.color=(.025,.035,.055);scene.world=world
scene.render.engine='BLENDER_WORKBENCH'
scene.render.resolution_x=960;scene.render.resolution_y=720;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL'
scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True;scene.display.shading.cavity_type='BOTH'
scene.display.shading.background_type='WORLD'
camera=bpy.data.objects.new('Workflow camera',bpy.data.cameras.new('Workflow camera'))
scene.collection.objects.link(camera);scene.camera=camera
camera.location=(.035,-.065,.065)
camera.rotation_euler=(Vector((0,0,.004))-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO';camera.data.ortho_scale=.067;camera.data.clip_start=.001
material=bpy.data.materials.new('Workflow blue');material.diffuse_color=(.025,.38,.8,1)
directory=OUT/'workflow';directory.mkdir(exist_ok=True)
curve=bpy.data.curves.new('Actual gear sketch outline','CURVE');curve.dimensions='3D';curve.bevel_depth=.00012;curve.bevel_resolution=1
profile=ProfileDetector().detect(part.features[0])
assert profile.success,profile.message
points=[(x,y,0) for x,y in profile.profile.iter_loops()[0].points]
spline=curve.splines.new('POLY');spline.points.add(len(points)-1)
for point,coordinate in zip(spline.points,points):point.co=(*coordinate,1)
spline.use_cyclic_u=True
outline=bpy.data.objects.new('Actual Sketch lines',curve);scene.collection.objects.link(outline);curve.materials.append(material)
scene.render.filepath=str(directory/'01_sketch.png');bpy.ops.render.render(write_still=True,scene=scene.name)
outline.hide_render=True
model=bpy.data.objects.new('Feature result preview',bpy.data.meshes.new('Preview'))
scene.collection.objects.link(model)
records=[]
for filename,limit,width in [('02_extrude.png',2,.008),('03_bore.png',None,.008),('04_width12.png',None,.012)]:
    part.rollback_index=limit
    part.features[1].distance=width
    adapter.save_document(document)
    result=adapter.rebuild_part(env.part_studio_scene(),part.id)
    assert result.success,(filename,[e.message for e in result.errors])
    source=next(o for o in bpy.data.objects if o.get('cad_generated') and o.get('cad_part_id')==part.id)
    model.data=source.data
    model.data.materials.clear();model.data.materials.append(material)
    scene.render.filepath=str(directory/filename);bpy.ops.render.render(write_still=True,scene=scene.name)
    mesh=model.data
    dimensions=[1000*(max(v.co[i] for v in mesh.vertices)-min(v.co[i] for v in mesh.vertices)) for i in range(3)]
    assert abs(dimensions[2]-width*1000)<.001,(filename,dimensions)
    records.append({'image':filename,'rollback_index':limit,'extrude_mm':width*1000,'dimensions_mm':dimensions})
    print('WORKFLOW',filename,dimensions,flush=True)
(directory/'validation.json').write_text(json.dumps({'source_part':part.id,'actual_history_rebuilt':True,'stages':records},indent=2))
print('WORKFLOW RENDERS COMPLETE',flush=True)
