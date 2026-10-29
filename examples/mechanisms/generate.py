"""Rebuild this gallery from its original gear document using the local add-on."""
import importlib.util
from pathlib import Path
import runpy
import sys

import bpy

here=Path(__file__).resolve().parent
repo=next((p for p in here.parents if (p/'blender_manifest.toml').exists()),None)
if repo is None:repo=here.parents[1]/'blender_parametric_cad'
spec=importlib.util.spec_from_file_location('blender_parametric_cad',repo/'__init__.py',submodule_search_locations=[str(repo)])
addon=importlib.util.module_from_spec(spec)
sys.modules['blender_parametric_cad']=addon
spec.loader.exec_module(addon)
addon.register()
bpy.ops.wm.open_mainfile(filepath=str(here/'base_spur_gears.blend'))
runpy.run_path(str(here/'extend_examples.py'),run_name='__main__')
runpy.run_path(str(here/'validate_examples.py'),run_name='__main__')
render=runpy.run_path(str(here/'render_gallery.py'))
render['annotate']();render['stills']()
bpy.ops.wm.save_as_mainfile(filepath=str(here/'mechanism_course_gallery.blend'))
runpy.run_path(str(here/'validate_examples.py'))['verify_reload']()
