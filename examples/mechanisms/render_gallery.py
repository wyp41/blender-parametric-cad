"""Add non-printing labels/rotation marks and render a GitHub-ready gallery."""
import json
from pathlib import Path
import sys

import bpy

OUT=Path(__file__).resolve().parent


def annotate():
    """Add camera labels and visual rotation marks without changing CAD Parts."""
    from blender_parametric_cad.blender.environments import instance_object
    catalog=json.loads((OUT/'catalog.json').read_text())
    for collection in list(bpy.data.collections):
        if collection.name.endswith('annotations - not STL geometry'):
            for obj in list(collection.objects):bpy.data.objects.remove(obj,do_unlink=True)
            bpy.data.collections.remove(collection)
    white=bpy.data.materials.get('Course annotations') or bpy.data.materials.new('Course annotations')
    white.diffuse_color=(.96,.97,1,1)
    for case in catalog['cases']:
        scene=bpy.data.scenes[case['scene']]
        collection=bpy.data.collections.new(f'{case["number"]:02d} annotations - not STL geometry')
        scene.collection.children.link(collection)
        span=case['view_span']
        for label,body,y,size in (('Title',f'{case["number"]:02d}  {case["title"]}',.325,.024),
                                  ('Subtitle',case['subtitle'],.292,.0125)):
            data=bpy.data.curves.new(label,'FONT');data.body=body;data.size=span*size
            obj=bpy.data.objects.new(label,data);collection.objects.link(obj)
            obj.parent=scene.camera;obj.location=(-.46*span,y*span,-.2)
            obj.data.materials.append(white)
        for item in case['instances'].values():
            mark={'gear20':(8,17,8.03),'gear40':(10,35,8.03),
                  'compound':(8,17,16.03),'ring':(84,88,8.03),
                  'carrier':(8,28,4.03),'cam':(8,25,8.03)}.get(item['part'])
            if not mark:continue
            a,b,z=mark
            mesh=bpy.data.meshes.new('Rotation stripe')
            mesh.from_pydata([(a/1000,-.0006,z/1000),(b/1000,-.0006,z/1000),
                              (b/1000,.0006,z/1000),(a/1000,.0006,z/1000)],[],[(0,1,2,3)])
            obj=bpy.data.objects.new('Rotation mark - display only',mesh)
            collection.objects.link(obj);obj.parent=instance_object(item['id'])
            mesh.materials.append(white)


def stills():
    """Render one preview per mechanism and a four-column contact sheet."""
    import numpy as np
    catalog=json.loads((OUT/'catalog.json').read_text())
    directory=OUT/'previews';directory.mkdir(exist_ok=True)
    for case in catalog['cases']:
        scene=bpy.data.scenes[case['scene']]
        bpy.context.window.scene=scene
        scene.frame_set(31 if case['number']>=11 else 1)
        scene.render.image_settings.media_type='IMAGE'
        scene.render.image_settings.file_format='PNG'
        scene.render.filepath=str(directory/f'{case["number"]:02d}.png')
        bpy.ops.render.render(write_still=True,scene=scene.name)
        print('PREVIEW',case['number'],flush=True)
        scene.frame_set(1)
    canvas=np.zeros((1440,1920,4),dtype=np.float32)
    canvas[:,:,:3]=(.025,.035,.055);canvas[:,:,3]=1
    for index,case in enumerate(catalog['cases']):
        image=bpy.data.images.load(str(directory/f'{case["number"]:02d}.png'),check_existing=False)
        pixels=np.array(image.pixels[:],dtype=np.float32).reshape(720,960,4)[::2,::2]
        x=(index%4)*480;y=(3-index//4)*360
        canvas[y:y+360,x:x+480]=pixels
        bpy.data.images.remove(image)
    result=bpy.data.images.new('Mechanism gallery overview',width=1920,height=1440,alpha=True)
    result.pixels.foreach_set(canvas.ravel());result.filepath_raw=str(OUT/'overview.png');result.file_format='PNG';result.save()


def movies():
    """Render each mechanism using Blender's native H.264 encoder."""
    catalog=json.loads((OUT/'catalog.json').read_text())
    directory=OUT/'videos';directory.mkdir(exist_ok=True)
    for case in catalog['cases']:
        scene=bpy.data.scenes[case['scene']]
        bpy.context.window.scene=scene
        scene.frame_start=1;scene.frame_end=241;scene.frame_step=4
        scene.render.image_settings.media_type='VIDEO'
        scene.render.image_settings.file_format='FFMPEG'
        scene.render.ffmpeg.format='MPEG4';scene.render.ffmpeg.codec='H264'
        scene.render.ffmpeg.constant_rate_factor='HIGH'
        scene.render.filepath=str(directory/f'{case["number"]:02d}.mp4')
        bpy.ops.render.render(animation=True,scene=scene.name)
        print('VIDEO',case['number'],flush=True)
    montage=bpy.data.scenes.new('Course video montage')
    montage.render.resolution_x=960;montage.render.resolution_y=720;montage.render.resolution_percentage=100
    montage.render.fps=24
    montage.view_settings.view_transform='Standard'
    editor=montage.sequence_editor_create()
    cursor=1
    for case in catalog['cases']:
        strip=editor.strips.new_movie(case['title'],str(directory/f'{case["number"]:02d}.mp4'),channel=1,frame_start=cursor)
        cursor+=strip.frame_final_duration
    montage.frame_start=1;montage.frame_end=cursor-1
    montage.render.image_settings.media_type='VIDEO'
    montage.render.image_settings.file_format='FFMPEG'
    montage.render.ffmpeg.format='MPEG4';montage.render.ffmpeg.codec='H264'
    montage.render.ffmpeg.constant_rate_factor='HIGH'
    montage.render.filepath=str(OUT/'mechanism_showcase.mp4')
    bpy.context.window.scene=montage
    bpy.ops.render.render(animation=True,scene=montage.name)
    (OUT/'video_manifest.json').write_text(json.dumps({'fps':24,'frames':cursor-1,
        'duration_seconds':(cursor-1)/24,'clips':14,'output':'mechanism_showcase.mp4'},indent=2))
    print('MONTAGE COMPLETE',cursor-1,'frames',flush=True)


if __name__=='__main__':
    import importlib.util
    repo=next((p for p in OUT.parents if (p/'blender_manifest.toml').exists()),None)
    if repo is None:repo=OUT.parents[1]/'blender_parametric_cad'
    spec=importlib.util.spec_from_file_location('blender_parametric_cad',repo/'__init__.py',submodule_search_locations=[str(repo)])
    addon=importlib.util.module_from_spec(spec);sys.modules['blender_parametric_cad']=addon
    spec.loader.exec_module(addon);addon.register()
    bpy.ops.wm.open_mainfile(filepath=str(OUT/'mechanism_course_gallery.blend'))
    movies()
