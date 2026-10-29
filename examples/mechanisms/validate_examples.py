"""Validate actual Assembly world transforms, gear clearances, and print meshes."""
import json
import math
from pathlib import Path
import struct
from itertools import combinations

import bpy
import bmesh
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from blender_parametric_cad.blender import adapter, environments as env

OUT=Path(__file__).resolve().parent


def validate(export=True):
    """Run sampling checks on the built document, then export each unique Part."""
    catalog=json.loads((OUT/'catalog.json').read_text())
    document=adapter.load_document()
    assert all(document.get_part(i) for i in catalog['original_part_ids'])
    meshes={}
    part_checks=[]
    for key,identifier in catalog['parts'].items():
        obj=next(o for o in bpy.data.objects if o.get('cad_generated') and o.get('cad_part_id')==identifier)
        mesh=obj.data
        bm=bmesh.new();bm.from_mesh(mesh)
        assert all(e.is_manifold for e in bm.edges),key
        assert bm.calc_volume(signed=True)>0,key
        mesh.calc_loop_triangles()
        meshes[key]=(mesh,[tuple(t.vertices) for t in mesh.loop_triangles])
        part_checks.append({'part':key,'manifold':True,'volume_mm3':bm.calc_volume()*1e9})
        bm.free()
    report={'parts':part_checks,'cases':[],'original_part_ids_preserved':True,
            'motion_type':'prescribed native drivers; no joint/contact solver',
            'load_or_print_testing':False}
    for case in catalog['cases']:
        scene=bpy.data.scenes[case['scene']]
        for window in bpy.context.window_manager.windows:window.scene=scene
        objects={key:env.instance_object(value['id']) for key,value in case['instances'].items()}
        pairs=[]
        number=case['number']
        if number==1:pairs=[('input','output')]
        elif number==2:pairs=[('input','idler'),('idler','output')]
        elif number in (3,4):pairs=[('input','compound'),('compound','output')]
        elif number==5:pairs=[('input','rack')]
        elif number==6:pairs=[('input','ring')]
        elif 7<=number<=10:
            pairs=[(a,f'planet{k}') for a in ('sun','ring') for k in range(3)]
        closure_max=0.0
        collisions=[]
        fixture_pairs=[pair for pair in combinations(objects,2)
                       if pair not in pairs and tuple(reversed(pair)) not in pairs
                       and not (number==13 and set(pair)=={'cam','follower'})
                       and not any(set(pair)==set(contact) for contact in case.get('surface_contacts',[]))]
        fixture_collisions=[]
        for sample in range(73):
            frame=1+sample*240/72
            scene.frame_set(int(frame),subframe=frame-int(frame))
            scene.view_layers[0].update()
            theta=2*math.pi*(frame-1)/240
            for obj in objects.values():
                if obj.animation_data:
                    assert all(c.driver.is_valid for c in obj.animation_data.drivers),(number,obj.name,'invalid driver')
            speeds={1:{'input':1,'output':-.5},2:{'input':1,'idler':-1,'output':.5},
                    3:{'input':1,'compound':-.5,'output':.25},
                    4:{'input':1,'compound':-.5,'output':.25},6:{'input':1,'ring':.25}}
            for key,speed in speeds.get(number,{}).items():
                angle=case['instances'][key]['phase']+speed*theta
                axis=objects[key].matrix_world.to_3x3() @ Vector((1,0,0))
                assert (axis-Vector((math.cos(angle),math.sin(angle),0))).length<1e-5,(number,key,'gear ratio')
            if number==5:
                assert abs(objects['rack'].matrix_world.translation.x-.04*math.sin(theta))<1e-6
                axis=objects['input'].matrix_world.to_3x3() @ Vector((1,0,0))
                assert (axis-Vector((math.cos(2*math.sin(theta)),math.sin(2*math.sin(theta)),0))).length<1e-5
            if 7<=number<=10:
                wc=case['speeds']['carrier'];wp=case['speeds']['planet']
                for k in range(3):
                    obj=objects[f'planet{k}'];phi=k*2*math.pi/3
                    expected=Vector((.06*math.cos(phi+wc*theta),.06*math.sin(phi+wc*theta),.005))
                    assert (obj.matrix_world.translation-expected).length<1e-5,(number,k,'orbit')
                    axis=obj.matrix_world.to_3x3() @ Vector((1,0,0))
                    expected_axis=Vector((math.cos(3*phi+wp*theta),math.sin(3*phi+wp*theta),0))
                    assert (axis-expected_axis).length<1e-5,(number,k,'spin')
            elif number==11:
                a=objects['crank'].matrix_world @ Vector((.02,0,0))
                b=objects['rod'].matrix_world.translation
                end=objects['rod'].matrix_world @ Vector((.06,0,0))
                slider=objects['slider'].matrix_world.translation
                closure_max=max(closure_max,(a.xy-b.xy).length,(end.xy-slider.xy).length)
            elif number==12:
                a=objects['crank'].matrix_world @ Vector((.02,0,0))
                b=objects['coupler'].matrix_world.translation
                end=objects['coupler'].matrix_world @ Vector((.06,0,0))
                rocker=objects['rocker'].matrix_world @ Vector((.04,0,0))
                closure_max=max(closure_max,(a.xy-b.xy).length,(end.xy-rocker.xy).length)
            elif number==13:
                expected=.03+.01*math.sin(theta)
                closure_max=max(closure_max,abs(objects['follower'].matrix_world.translation.y-expected))
            elif number==14:
                closure_max=max(closure_max,abs(objects['pin'].matrix_world.translation.x-objects['yoke'].matrix_world.translation.x))
            trees={}
            for key in objects:
                obj=objects[key]
                mesh,triangles=meshes[case['instances'][key]['part']]
                # Stagger caps only, leaving a large common Z span. This avoids
                # coincident faces while still detecting XY tooth penetration.
                shift=Matrix.Translation((0,0,(.0001 if key!='base' else 0)+(.0002 if key in ('output','rack','ring','compound','idler') else 0)))
                vertices=[shift @ obj.matrix_world @ v.co for v in mesh.vertices]
                trees[key]=BVHTree.FromPolygons(vertices,triangles,all_triangles=True)
            for a,b in pairs:
                if trees[a].overlap(trees[b]):collisions.append({'frame':frame,'parts':[a,b]})
            for a,b in fixture_pairs:
                if trees[a].overlap(trees[b]):fixture_collisions.append({'frame':frame,'parts':[a,b]})
        assert closure_max<1e-5,(number,'closure',closure_max*1000)
        result={'number':number,'title':case['title'],'samples':73,
                'world_motion_checked':True,
                'gear_pairs_checked':len(pairs),'collisions':collisions,
                'fixture_pairs_checked':len(fixture_pairs),'fixture_collisions':fixture_collisions,
                'max_planar_closure_error_mm':closure_max*1000}
        report['cases'].append(result)
        (OUT/'validation.json').write_text(json.dumps(report,indent=2))
        print('CASE',number,'gear collisions',len(collisions),'fixture collisions',len(fixture_collisions),'closure mm',closure_max*1000,flush=True)
        scene.frame_set(1)
    assert not any(c['collisions'] for c in report['cases']),'Gear interference; see validation.json.'
    assert not any(c['fixture_collisions'] for c in report['cases']),'Fixture interference; see validation.json.'
    errors=adapter.validate_cad_document(env.part_studio_scene())
    assert not errors,errors
    report['cad_validation_errors']=errors
    if export:report=export_parts(report)
    (OUT/'validation.json').write_text(json.dumps(report,indent=2))
    return report


def export_parts(report=None):
    """Export unique Parts without rerunning the already-passed motion checks."""
    if report is None:report=json.loads((OUT/'validation.json').read_text())
    catalog=json.loads((OUT/'catalog.json').read_text())
    directory=OUT/'stl';directory.mkdir(exist_ok=True)
    for key,identifier in catalog['parts'].items():
        obj=next(o for o in bpy.data.objects if o.get('cad_generated') and o.get('cad_part_id')==identifier)
        expected=[1000*(max(v.co[i] for v in obj.data.vertices)-min(v.co[i] for v in obj.data.vertices)) for i in range(3)]
        path=directory/(key+'.stl')
        adapter.export_part(env.part_studio_scene(),identifier,str(path),'STL')
        data=path.read_bytes();count=struct.unpack_from('<I',data,80)[0]
        points=[struct.unpack_from('<3f',data,84+50*i+12+12*j) for i in range(count) for j in range(3)]
        bounds=[max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)]
        assert all(abs(a-b)<.001 for a,b in zip(bounds,expected)),(key,bounds,expected)
        next(p for p in report['parts'] if p['part']==key)['stl_dimensions_mm']=bounds
        print('STL',key,bounds,flush=True)
    (OUT/'validation.json').write_text(json.dumps(report,indent=2))
    return report


def verify_reload():
    """Compare actual instance transforms across a saved-file reload."""
    catalog=json.loads((OUT/'catalog.json').read_text())
    def sample():
        matrices=[]
        for case in catalog['cases']:
            scene=bpy.data.scenes[case['scene']]
            for window in bpy.context.window_manager.windows:window.scene=scene
            for frame in (1.25,31,121):
                scene.frame_set(int(frame),subframe=frame-int(frame))
                scene.view_layers[0].update()
                for item in case['instances'].values():
                    matrices.extend(v for row in env.instance_object(item['id']).matrix_world for v in row)
            scene.frame_set(1)
        return matrices
    before=sample()
    for window in bpy.context.window_manager.windows:window.scene=bpy.data.scenes[catalog['cases'][2]['scene']]
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'mechanism_course_gallery.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'mechanism_course_gallery.blend'))
    after=sample()
    error=max(abs(a-b) for a,b in zip(before,after))
    assert len(before)==len(after) and error<1e-6,error
    report=json.loads((OUT/'validation.json').read_text())
    report['gallery_save_reopen']={'passed':True,'max_transform_component_difference':error,
                                  'sample_frames':[1.25,31,121]}
    (OUT/'validation.json').write_text(json.dumps(report,indent=2))
    for window in bpy.context.window_manager.windows:window.scene=bpy.data.scenes[catalog['cases'][2]['scene']]
    print('GALLERY SAVE REOPEN PASSED',error,flush=True)


if __name__=='__main__':validate()
