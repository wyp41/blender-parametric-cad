"""Blender regression checks for slicer units and animated Assembly rebuilding."""
import json
import math
from pathlib import Path
import struct
import sys
import tempfile

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import blender_parametric_cad
from blender_parametric_cad.blender import adapter, environments as env
from blender_parametric_cad.blender.motion import set_planar_motion
from blender_parametric_cad.core.assembly import Assembly, AssemblyInstance
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.sketch.numeric import set_rectangle
from blender_parametric_cad.sketch.sketch import SketchFeature
from blender_parametric_cad.sketch.entities import SketchCircle


def main():
    """Check actual exported coordinates and world transforms before/after reload."""
    blender_parametric_cad.register()
    part=Part(name='Export and motion regression')
    sketch=SketchFeature.on_plane('20x10mm','XY')
    set_rectangle(sketch,0,0,.02,.01)
    part.add_feature(sketch)
    pad=ExtrudeFeature(sketch_id=sketch.id,distance=.008)
    part.add_feature(pad)
    hole=SketchFeature.on_plane('Boolean bore','XY')
    hole.entities.append(SketchCircle(cx=.005,cy=.005,radius=.002))
    part.add_feature(hole)
    part.add_feature(ExtrudeFeature(sketch_id=hole.id,operation='REMOVE',depth_mode='THROUGH_ALL',dependencies=[hole.id,pad.id]))
    document=adapter.load_document()
    document.add_part(part)
    adapter.save_document(document)
    scene=env.part_studio_scene()
    assert adapter.rebuild_part(scene,part.id).success
    material=bpy.data.materials.new('Preserve material during export/rebuild')
    result_object=next(o for o in bpy.data.objects if o.get('cad_generated') and o.get('cad_part_id')==part.id)
    result_object.data.materials.clear();result_object.data.materials.append(material)
    scene.unit_settings.scale_length=.001
    path=Path(tempfile.gettempdir())/'cad_gear_unit_regression.stl'
    adapter.export_part(scene,part.id,str(path),'STL')
    assert result_object.data.materials[0]==material
    data=path.read_bytes()
    count=struct.unpack_from('<I',data,80)[0]
    points=[struct.unpack_from('<3f',data,84+50*i+12+12*j) for i in range(count) for j in range(3)]
    dimensions=[max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)]
    assert all(abs(a-b)<.001 for a,b in zip(dimensions,(20,10,8))),dimensions
    document=adapter.load_document()
    assembly=document.add_assembly(Assembly(name='Motion regression'))
    transform=Matrix.Translation((.1,.02,0)) @ Matrix.Rotation(.3,4,'Z')
    item=document.add_instance(assembly.id,AssemblyInstance(part_studio_id=part.id,transform=tuple(tuple(r) for r in transform)))
    view=env.assembly_scene()
    bpy.context.window.scene=view
    env.commit_assembly(document,assembly,view)
    view.parametric_cad_ui.active_assembly_id=assembly.id
    assert set_planar_motion(item.id) == env.instance_object(item.id)
    set_planar_motion(item.id,angle='2*pi*(frame-1)/240',x='.01*sin(2*pi*(frame-1)/240)')
    def check():
        for frame in (1,1.25,31,61,121):
            view.frame_set(int(frame),subframe=frame-int(frame))
            view.view_layers[0].update()
            obj=env.instance_object(item.id)
            theta=2*math.pi*(frame-1)/240
            axis=obj.matrix_world.to_3x3() @ Vector((1,0,0))
            assert (axis-Vector((math.cos(.3+theta),math.sin(.3+theta),0))).length<1e-5, (frame,list(axis),list(obj.delta_rotation_quaternion))
            assert abs(obj.matrix_world.translation.x-(.1+.01*math.sin(theta)))<1e-6
            before=obj.matrix_world.copy()
            env.sync_assembly(adapter.load_document().get_assembly(assembly.id),view)
            view.view_layers[0].update()
            assert all(abs(a-b)<1e-6 for ra,rb in zip(before,obj.matrix_world) for a,b in zip(ra,rb))
    check()
    assert adapter.rebuild_part(scene,part.id).success
    assert result_object.data.materials[0]==material
    check()
    blend=Path(tempfile.gettempdir())/'cad_gear_motion_regression.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    view=env.assembly_scene()
    check()
    output=Path(tempfile.gettempdir())/'cad_gear_workflow_validation.json'
    output.write_text(json.dumps({'stl_dimensions_mm':dimensions,'animation_world_transform':True,
                                 'assembly_sync':True,'source_rebuild':True,'save_reopen':True,
                                 'material_preserved':True,'static_motion_noop':True},indent=2))
    print('GEAR WORKFLOW REGRESSIONS PASSED',flush=True)


main()
