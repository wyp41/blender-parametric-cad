"""Extend the original 20/40-tooth document into a mechanical course gallery.

Run in the existing Blender CAD session. Source Parts and the original Assembly
are preserved. Dimensions in this script are mm unless converted at API calls.
"""
import json
import math
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Quaternion, Vector

from blender_parametric_cad.blender import adapter, environments as env
from blender_parametric_cad.blender.motion import set_planar_motion
from blender_parametric_cad.core.assembly import Assembly, AssemblyInstance
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import AxisReference
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.features.revolve import RevolveFeature
from blender_parametric_cad.sketch.entities import SketchArc, SketchCircle, SketchLine
from blender_parametric_cad.sketch.gears import add_outline, internal_outline, rack_outline, spur_outline
from blender_parametric_cad.sketch.sketch import SketchFeature

OUT = Path(__file__).resolve().parent
THETA = '(2*pi*(frame-1)/240)'
BASE_IDS = ('cff13979-fa1e-488f-ab8b-384a0a5de45a', 'dffe88ad-52d5-4575-8610-daaebd36f4b8')
COLORS = {'input': (.025, .38, .8, 1), 'output': (.98, .33, .05, 1),
          'middle': (.07, .65, .42, 1), 'base': (.15, .2, .26, 1),
          'ring': (.6, .22, .55, 1), 'link': (.95, .64, .08, 1)}
parts = {}
cases = []


def source(part):
    """Resolve a disposable result by its persistent Part UUID."""
    return next(o for o in bpy.data.objects if o.get('cad_generated') and o.get('cad_part_id') == part.id)


def profile(part, name, geometry, z=0):
    """Append a sketch on an offset XY plane, using mm outlines or circle tuples."""
    sketch = SketchFeature.on_plane(name, 'XY', offset=z/1000)
    if isinstance(geometry, tuple):
        x, y, radius = geometry
        sketch.entities.append(SketchCircle(cx=x/1000, cy=y/1000, radius=radius/1000))
    else:
        add_outline(sketch, [(x/1000, y/1000) for x, y in geometry])
    part.add_feature(sketch)
    return sketch


def pad(part, sketch, height, operation='NEW', name='Extrude'):
    """Append one additive or subtractive Extrude with the previous body dependency."""
    body = next((f for f in reversed(part.features[:-1]) if f.feature_type in ('EXTRUDE', 'REVOLVE')), None)
    dependencies = [sketch.id] + ([body.id] if operation != 'NEW' and body else [])
    feature = ExtrudeFeature(name=name, sketch_id=sketch.id, distance=height/1000,
                             operation=operation, depth_mode='THROUGH_ALL' if operation == 'REMOVE' else 'BLIND',
                             dependencies=dependencies)
    part.add_feature(feature)
    return feature


def rectangle(x, y, width, height):
    """Return a CCW rectangle in mm."""
    return [(x, y), (x+width, y), (x+width, y+height), (x, y+height)]


def finish(part, key, color='middle'):
    """Commit and rebuild a Part without discarding existing document edits."""
    document = adapter.load_document()
    document.add_part(part)
    adapter.save_document(document)
    result = adapter.rebuild_part(env.part_studio_scene(), part.id)
    assert result.success, (part.name, [e.message for e in result.errors])
    obj = source(part)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    assert all(e.is_manifold for e in bm.edges), part.name
    assert bm.calc_volume(signed=True) > 0, part.name
    # A printable Part must contain exactly one connected component.
    remaining = set(bm.verts)
    stack = [next(iter(remaining))]
    while stack:
        vertex = stack.pop()
        if vertex not in remaining:
            continue
        remaining.remove(vertex)
        stack.extend(e.other_vert(vertex) for e in vertex.link_edges)
    assert not remaining, f'Disconnected Part: {part.name}'
    bm.free()
    material = bpy.data.materials.new(part.name+' material')
    material.diffuse_color = COLORS[color]
    obj.data.materials.clear()
    obj.data.materials.append(material)
    parts[key] = part
    print('PART', key, len(obj.data.vertices), flush=True)
    return part


def gear_sketch(part, teeth, z=0):
    """Reuse the plugin involute generator at the original module and pressure angle."""
    sketch = SketchFeature.on_plane(f'm2 z{teeth} involute', 'XY', offset=z/1000)
    add_outline(sketch, spur_outline(.002, teeth, backlash=.00015))
    part.add_feature(sketch)
    return sketch


def board(key, bounds, pins=(), rails=()):
    """Create a flat print bed plate with integral low-load pins and guide rails."""
    part = Part(name=key)
    pad(part, profile(part, 'Base plate', rectangle(*bounds)), 4)
    for x, y, height in pins:
        pad(part, profile(part, 'Integral axle diameter 5.8', (x, y, 2.9), z=3.8), height-3.8, 'ADD')
    for rect, height in rails:
        pad(part, profile(part, 'Guide rail', rectangle(*rect), z=3.8), height-3.8, 'ADD')
    return finish(part, key, 'base')


def link(key, length, color='link'):
    """Make a capsule link with 6.3-mm clearance holes at its two pivots."""
    part = Part(name=key)
    sketch = SketchFeature.on_plane('Capsule outline R6', 'XY')
    sketch.entities = [SketchLine(x1=0, y1=-.006, x2=length/1000, y2=-.006),
                       SketchArc(cx=length/1000, radius=.006, start_angle=-math.pi/2, end_angle=math.pi/2),
                       SketchLine(x1=length/1000, y1=.006, x2=0, y2=.006),
                       SketchArc(radius=.006, start_angle=math.pi/2, end_angle=3*math.pi/2)]
    part.add_feature(sketch)
    pad(part, sketch, 4)
    holes = SketchFeature.on_plane('Pivot clearance holes', 'XY')
    holes.entities = [SketchCircle(cx=x/1000, radius=.00315) for x in (0, length)]
    part.add_feature(holes)
    pad(part, holes, 4, 'REMOVE')
    return finish(part, key, color)


def spacer(key, height):
    """Print a loose axial support sleeve for a 5.8-mm axle and 6.3-mm bore."""
    part=Part(name=key)
    pad(part,profile(part,'Outer diameter12',(0,0,6)),height)
    pad(part,profile(part,'Clearance bore6p3',(0,0,3.15)),height,'REMOVE')
    return finish(part,key,'base')


def build_parts():
    """Add reusable printable Parts while retaining both original gear UUIDs."""
    document = adapter.load_document()
    assert all(document.get_part(identifier) for identifier in BASE_IDS), 'Start from the original gear document.'
    assert not any(p.name == 'Compound_40_20' for p in document.parts), 'Examples already built.'
    OUT.mkdir(parents=True, exist_ok=True)
    parts['gear20'], parts['gear40'] = [document.get_part(i) for i in BASE_IDS]
    for key,color in (('gear20','input'),('gear40','output')):
        material=bpy.data.materials.new(key+' course material')
        material.diffuse_color=COLORS[color]
        source(parts[key]).data.materials.clear()
        source(parts[key]).data.materials.append(material)
    part = Part(name='Compound_40_20')
    pad(part, gear_sketch(part, 40), 8)
    # The upper gear starts on the lower gear's full face, avoiding an
    # unsupported overhang above a narrow hub during flat FDM printing.
    pad(part, gear_sketch(part, 20, z=7.9), 8.1, 'ADD')
    pad(part, profile(part, 'Common bore', (0, 0, 3.15)), 16, 'REMOVE')
    finish(part, 'compound')

    part = Part(name='Rack_m2_24T')
    pad(part, profile(part, 'Straight rack pitch pi*m', [(x*1000,y*1000) for x,y in rack_outline(.002,24,backlash=.00015)]), 8)
    finish(part, 'rack', 'output')
    part = Part(name='Ring_m2_80T')
    pad(part, profile(part, 'Ring blank OD181', (0,0,90.5)), 8)
    cut = SketchFeature.on_plane('Internal involute cutout z80', 'XY')
    add_outline(cut, internal_outline(.002,80,backlash=.00015))
    part.add_feature(cut)
    pad(part, cut, 8, 'REMOVE')
    finish(part, 'ring', 'ring')

    part = Part(name='Planet_carrier_3_pins')
    pad(part, profile(part, 'Carrier plate OD140', (0,0,70)), 4)
    for x,y in ((60*math.cos(k*2*math.pi/3),60*math.sin(k*2*math.pi/3)) for k in range(3)):
        pad(part, profile(part,'Planet axle',(x,y,2.9),z=3.8),10.2,'ADD')
    pad(part,profile(part,'Coaxial shaft bore',(0,0,3.15)),14,'REMOVE')
    finish(part,'carrier','middle')

    # One shared shouldered pin exercises the Revolve path as well as Extrude.
    part=Part(name='Shouldered_pin_5p8')
    sketch=SketchFeature.on_plane('Pin half section','XZ')
    add_outline(sketch,[(0,0),(.004,0),(.004,.002),(.0029,.002),(.0029,.014),(0,.014)])
    part.add_feature(sketch)
    part.add_feature(RevolveFeature(name='Full revolve of shoulder pin',sketch_id=sketch.id,axis_reference=AxisReference(axis='Z')))
    finish(part,'pin','middle')
    spacer('spacer1',1)
    spacer('spacer0p6',.6)
    spacer('spacer9p6',9.6)
    link('link20',20,'input')
    link('link40',40,'output')
    link('link60',60)

    part=Part(name='Slider_block_with_pin')
    pad(part,profile(part,'Slider block',rectangle(-10,-10,20,20)),5)
    pad(part,profile(part,'Link axle',(0,0,2.9),z=4.8),5.2,'ADD')
    finish(part,'slider','output')
    part=Part(name='Eccentric_disc_R30_e10')
    pad(part,profile(part,'Offset circular cam',(10,0,30)),8)
    pad(part,profile(part,'Shaft bore',(0,0,3.15)),8,'REMOVE')
    finish(part,'cam','input')
    part=Part(name='Flat_cam_follower')
    pad(part,profile(part,'Flat foot',rectangle(-40,0,80,4)),8)
    pad(part,profile(part,'Guided stem',rectangle(-4,3.8,8,40.2)),8,'ADD')
    finish(part,'follower','output')
    part=Part(name='Scotch_yoke')
    pad(part,profile(part,'Yoke blank',rectangle(-9,-30,18,60)),4)
    pad(part,profile(part,'Rod',rectangle(8.8,-4,51.2,8)),4,'ADD')
    pad(part,profile(part,'Pin slot width6p4',rectangle(-3.2,-25,6.4,50)),4,'REMOVE')
    finish(part,'yoke','output')

    board('Board_idler',(-14,-16,128,32),[(0,0,15),(40,0,15),(100,0,15)])
    board('Board_compound',(-14,-16,148,32),[(0,0,15),(60,0,24),(120,0,24)])
    board('Board_reverted',(-14,-16,88,32),[(0,0,24),(60,0,24)])
    board('Board_rack',(-90,-45,180,62),[(0,0,15)],[( (-85,-34.5,170,6.5),13)])
    board('Board_links',(-14,-18,112,36),[(0,0,9.2)],[( (25,-16.4,65,6),8),((25,10.4,65,6),8)])
    board('Board_fourbar',(-14,-16,88,32),[(0,0,9.2),(60,0,9.2)])
    board('Board_cam',(-48,-35,96,127),[(0,0,15)],[( (-10.4,55,6,25),15),((4.4,55,6,25),15)])
    board('Board_yoke',(-30,-36,116,72),[(0,0,9.2)],[( (32,-10.4,6,6),16),((32,4.4,6,6),16),((30,-4,10,8),10)])
    print('Reusable Parts complete.',flush=True)


def assembly_case(number, title, subtitle):
    """Create an Assembly Scene, preserving all original scenes and assemblies."""
    document=adapter.load_document()
    assembly=Assembly(name=f'{number:02d} {title}')
    document.add_assembly(assembly)
    scene=bpy.data.scenes.new(assembly.name)
    scene['cad_scene_role']='ASSEMBLY'
    env.commit_assembly(document,assembly,scene)
    scene.parametric_cad_ui.active_assembly_id=assembly.id
    case={'number':number,'title':title,'subtitle':subtitle,'scene':scene.name,
          'assembly_id':assembly.id,'instances':{},'checks':[]}
    cases.append(case)
    return case


def place(case,key,part_key,x=0,y=0,z=0,phase=0,angle=None,dx=None,dy=None,flip=False):
    """Place a linked Part and optionally add prescribed motion in its own axes."""
    document=adapter.load_document()
    assembly=document.get_assembly(case['assembly_id'])
    transform=Matrix.Translation((x/1000,y/1000,z/1000)) @ Matrix.Rotation(phase,4,'Z')
    if flip:
        transform=transform @ Matrix.Rotation(math.pi,4,'X')
    item=AssemblyInstance(name=f'{case["number"]:02d}_{key}',part_studio_id=parts[part_key].id,
                          transform=tuple(tuple(row) for row in transform))
    document.add_instance(assembly.id,item)
    env.commit_assembly(document,assembly,bpy.data.scenes[case['scene']])
    obj=set_planar_motion(item.id,angle=angle,x=dx,y=dy)
    case['instances'][key]={'id':item.id,'part':part_key,'phase':phase}
    return obj


def build_cases():
    """Append 13 mechanisms to the original spur pair rather than starting over."""
    document=adapter.load_document()
    original=document.assemblies[0]
    cases.append({'number':1,'title':'Spur gear pair','subtitle':'20 : 40 | reduction 2:1',
                  'scene':'CAD — Assembly','assembly_id':original.id,'instances':{
                      'input':{'id':original.instances[0].id,'part':'gear20','phase':0},
                      'output':{'id':original.instances[1].id,'part':'gear40','phase':math.pi/40}},'checks':[]})
    set_planar_motion(original.instances[0].id,angle=THETA)
    set_planar_motion(original.instances[1].id,angle='-'+THETA+'/2')
    c=assembly_case(2,'Idler gear train','20 - 20 - 40 | ratio 2:1 | same direction')
    place(c,'base','Board_idler')
    place(c,'input','gear20',z=5,angle=THETA)
    place(c,'idler','gear20',40,z=5,phase=math.pi/20,angle='-'+THETA)
    place(c,'output','gear40',100,z=5,angle=THETA+'/2')
    c=assembly_case(3,'Compound reducer','20/40 x 20/40 | reduction 4:1')
    place(c,'base','Board_compound')
    place(c,'input','gear20',z=5,angle=THETA)
    place(c,'compound','compound',60,z=5,phase=math.pi/40,angle='-'+THETA+'/2')
    place(c,'output','gear40',120,z=13.6,phase=math.pi/80,angle=THETA+'/4')
    c=assembly_case(4,'Reverted gear train','Coaxial input/output | reduction 4:1')
    place(c,'base','Board_reverted')
    place(c,'input','gear20',z=5,angle=THETA)
    place(c,'compound','compound',60,z=5,phase=math.pi/40,angle='-'+THETA+'/2')
    place(c,'output','gear40',z=13.6,phase=math.pi/80,angle=THETA+'/4')
    c=assembly_case(5,'Rack and pinion','m2 z20 | travel per turn = 125.664 mm')
    place(c,'base','Board_rack')
    place(c,'input','gear20',z=5,angle='2*sin('+THETA+')')
    place(c,'rack','rack',y=-20,z=4,dx='0.04*sin('+THETA+')')
    c=assembly_case(6,'Internal gear pair','20 inside 80 | reduction 4:1 | same direction')
    place(c,'input','gear20',60,angle=THETA)
    place(c,'ring','ring',angle=THETA+'/4')
    for number,title,ws,wr in ((7,'Planetary - ring fixed',1,0),(8,'Planetary - sun fixed',0,1),
                               (9,'Planetary - carrier fixed',1,-.5),(10,'Planetary differential',1,.5)):
        wc=(40*ws+80*wr)/120
        wp=3*wc-2*ws
        c=assembly_case(number,title,f'zS40 + 3 x zP20 + zR80 | wC=(wS+2wR)/3')
        c['speeds']={'sun':ws,'ring':wr,'carrier':wc,'planet':wp}
        place(c,'sun','gear40',z=5,phase=math.pi/40,angle=f'{ws}*{THETA}')
        place(c,'ring','ring',z=5,angle=f'{wr}*{THETA}')
        place(c,'carrier','carrier',angle=f'{wc}*{THETA}')
        for k in range(3):
            phi=k*2*math.pi/3
            # Delta location is in the carrier's parent axes, independent of its own rotation.
            place(c,f'planet{k}','gear20',60*math.cos(phi),60*math.sin(phi),5,phase=3*phi,
                  angle=f'{wp}*{THETA}',dx=f'0.06*(cos({phi}+{wc}*{THETA})-cos({phi}))',
                  dy=f'0.06*(sin({phi}+{wc}*{THETA})-sin({phi}))')
    c=assembly_case(11,'Slider crank','Crank 20 mm | rod 60 mm | stroke 40 mm')
    place(c,'base','Board_links')
    place(c,'crank','link20',z=5,angle=THETA)
    place(c,'rod','link60',z=9.6,angle=f'asin(-sin({THETA})/3)',
          dx=f'0.02*cos({THETA})',dy=f'0.02*sin({THETA})')
    place(c,'slider','slider',z=4,dx=f'0.02*cos({THETA})+sqrt(0.06**2-(0.02*sin({THETA}))**2)')
    place(c,'crank_pin','pin',z=18,flip=True,dx=f'0.02*cos({THETA})',dy=f'0.02*sin({THETA})')

    c=assembly_case(12,'Four bar linkage','Ground60 | crank20 | coupler60 | rocker40')
    # Long nested expressions exceed Blender's driver expression limit. The
    # two circle-intersection coordinates are evaluated through driver variables.
    control=bpy.data.objects.new('Fourbar analytic coordinates',None)
    bpy.data.scenes[c['scene']].collection.objects.link(control)
    control['theta']=0.0
    control.driver_add('["theta"]').driver.expression=THETA
    control['ax']=.02;control['ay']=0.0;control['d']=.04;control['a']=.045;control['h']=.04;control['cx']=.06;control['cy']=.04
    expressions={'ax':('.02*cos(t)',('t',)),'ay':('.02*sin(t)',('t',)),
                 'd':('sqrt((.06-ax)**2+ay**2)',('ax','ay')),
                 'a':('(.06**2-.04**2+d**2)/(2*d)',('d',)),
                 'h':('sqrt(.06**2-a**2)',('a',)),
                 'cx':('ax+a*(.06-ax)/d+h*ay/d',('ax','ay','a','h','d')),
                 'cy':('ay-a*ay/d+h*(.06-ax)/d',('ax','ay','a','h','d'))}
    for prop,(expression,variables) in expressions.items():
        driver=control.driver_add(f'["{prop}"]').driver
        driver.expression=expression
        for name in variables:
            path='theta' if name=='t' else name
            var=driver.variables.new();var.name=name;var.type='SINGLE_PROP'
            var.targets[0].id=control;var.targets[0].data_path=f'["{path}"]'
    place(c,'base','Board_fourbar')
    place(c,'crank','link20',z=5,angle=THETA)
    coupler=place(c,'coupler','link60',z=9.6,angle='atan2(cy-ay,cx-ax)',dx='ax',dy='ay')
    rocker=place(c,'rocker','link40',60,z=5,angle='atan2(cy,cx-.06)')
    for obj in (coupler,rocker):
        for curve in obj.animation_data.drivers:
            for name in ('ax','ay','cx','cy'):
                var=curve.driver.variables.new();var.name=name;var.type='SINGLE_PROP'
                var.targets[0].id=control;var.targets[0].data_path=f'["{name}"]'
    for key,px,py in (('joint_A','ax','ay'),('joint_C','cx','cy')):
        joint=place(c,key,'pin',z=18,flip=True,dx=px,dy=py)
        for curve in joint.animation_data.drivers:
            for name in (px,py):
                var=curve.driver.variables.new();var.name=name;var.type='SINGLE_PROP'
                var.targets[0].id=control;var.targets[0].data_path=f'["{name}"]'
    c['control']=control.name
    c=assembly_case(13,'Eccentric cam follower','R30 | eccentricity10 | stroke20 | gravity return')
    place(c,'base','Board_cam')
    place(c,'cam','cam',z=5,angle=THETA)
    place(c,'follower','follower',z=5,dy=f'.03+.01*sin({THETA})')
    c=assembly_case(14,'Scotch yoke','Crank20 | slot width6.4 | sinusoidal stroke40')
    place(c,'base','Board_yoke')
    place(c,'crank','link20',z=5,angle=THETA)
    place(c,'pin','pin',z=18,flip=True,dx=f'.02*cos({THETA})',dy=f'.02*sin({THETA})')
    place(c,'yoke','yoke',z=10,dx=f'.02*cos({THETA})')
    add_axial_supports()
    print('All assemblies appended.',flush=True)


def add_axial_supports():
    """Support horizontal demo assemblies with actual printable spacers."""
    for case in cases:
        n=case['number']
        specs={2:[('input',0,1),('idler',40,1),('output',100,1)],
               3:[('input',0,1),('compound',60,1),('output',120,9.6)],
               4:[('input',0,1),('compound',60,1),('output',0,.6)],
               5:[('input',0,1)],11:[('crank',0,1)],
               12:[('crank',0,1),('rocker',60,1)],13:[('cam',0,1)],14:[('crank',0,1)]}.get(n,[])
        case['surface_contacts']=[]
        for target,x,height in specs:
            key=target+'_spacer'
            part='spacer1' if height==1 else 'spacer0p6' if height==.6 else 'spacer9p6'
            place(case,key,part,x,z=13 if n==4 and target=='output' else 4)
            case['surface_contacts'].append([target,key])
            if n==4 and target=='output':case['surface_contacts'].append(['input',key])
        if n==11:
            for key,target,px,py in (('A_spacer','crank',f'.02*cos({THETA})',f'.02*sin({THETA})'),
                                     ('B_spacer','slider',f'.02*cos({THETA})+sqrt(.06**2-(.02*sin({THETA}))**2)','0')):
                place(case,key,'spacer0p6',z=9,dx=px,dy=py)
                case['surface_contacts'].extend([[key,target],[key,'rod']])
        if n==12:
            control=bpy.data.objects[case['control']]
            for key,target,px,py in (('A_spacer','crank','ax','ay'),('C_spacer','rocker','cx','cy')):
                obj=place(case,key,'spacer0p6',z=9,dx=px,dy=py)
                for curve in obj.animation_data.drivers:
                    for name in (px,py):
                        var=curve.driver.variables.new();var.name=name;var.type='SINGLE_PROP'
                        var.targets[0].id=control;var.targets[0].data_path=f'["{name}"]'
                case['surface_contacts'].extend([[key,target],[key,'coupler']])


def configure_scenes():
    """Set an orthographic view and native camera for every course example."""
    world=bpy.data.worlds.new('Course gallery background')
    world.color=(.025,.035,.055)
    for case in cases:
        scene=bpy.data.scenes[case['scene']]
        scene.unit_settings.system='METRIC'
        scene.unit_settings.length_unit='MILLIMETERS'
        scene.frame_start,scene.frame_end=1,241
        scene.render.fps=24
        scene.frame_set(1)
        if case['number']==2:center,span=(.05,0),.19
        elif case['number']==3:center,span=(.06,0),.24
        elif case['number']==4:center,span=(.03,0),.16
        elif case['number']==5:center,span=(0,-.005),.21
        elif case['number']==6 or 7<=case['number']<=10:center,span=(0,0),.30
        elif case['number']==11:center,span=(.04,0),.15
        elif case['number']==12:center,span=(.03,.02),.15
        elif case['number']==13:center,span=(0,.025),.22
        elif case['number']==14:center,span=(.025,0),.15
        else:center,span=(.04,0),.15
        case['view_center']=list(center);case['view_span']=span
        camera_data=bpy.data.cameras.new(f'{case["number"]:02d} camera')
        camera=bpy.data.objects.new(f'{case["number"]:02d} camera',camera_data)
        scene.collection.objects.link(camera)
        camera.location=(center[0],center[1]-.10,.30)
        if case['number']==4:camera.location=(center[0],center[1]-.28,.13)
        camera.rotation_euler=(Vector((center[0],center[1],.004))-camera.location).to_track_quat('-Z','Y').to_euler()
        camera_data.type='ORTHO';camera_data.ortho_scale=span;camera_data.clip_start=.001
        scene.camera=camera
        scene.render.engine='BLENDER_WORKBENCH'
        scene.render.resolution_x=960;scene.render.resolution_y=720;scene.render.resolution_percentage=100
        shading=scene.display.shading
        shading.light='STUDIO';shading.color_type='MATERIAL'
        shading.show_shadows=True;shading.show_cavity=True;shading.cavity_type='BOTH';shading.background_type='WORLD'
        scene.world=world
        scene.render.image_settings.file_format='PNG'
        scene.render.filepath=str(OUT/'previews'/f'{case["number"]:02d}.png')
    for window in bpy.context.window_manager.windows:
        window.scene=bpy.data.scenes[cases[2]['scene']]
        for area in window.screen.areas:
            if area.type=='VIEW_3D':
                space=area.spaces.active
                space.shading.type='SOLID';space.shading.color_type='MATERIAL'
                space.overlay.show_floor=False;space.overlay.show_axis_x=False;space.overlay.show_axis_y=False
                space.clip_start=.0001
                space.region_3d.view_location=Vector((.06,0,.01))
                space.region_3d.view_distance=.24
                space.region_3d.view_rotation=Quaternion((1,0,0),math.radians(25))
                space.region_3d.view_perspective='ORTHO'


def save():
    """Save the expanded document as a new file, keeping the original untouched."""
    payload={'base_file':'base_spur_gears.blend',
             'original_part_ids':list(BASE_IDS),'parts':{k:v.id for k,v in parts.items()},'cases':cases}
    (OUT/'catalog.json').write_text(json.dumps(payload,indent=2))
    text=bpy.data.texts.get('COURSE_CATALOG.json') or bpy.data.texts.new('COURSE_CATALOG.json')
    text.clear();text.write(json.dumps(payload,indent=2))
    text=bpy.data.texts.get('Extend_course_examples.py') or bpy.data.texts.new('Extend_course_examples.py')
    text.clear();text.write(Path(__file__).read_text())
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'mechanism_course_gallery.blend'))
    print('SAVED',len(parts),'Parts',len(cases),'cases',flush=True)


if __name__=='__main__':
    build_parts()
    build_cases()
    configure_scenes()
    save()
