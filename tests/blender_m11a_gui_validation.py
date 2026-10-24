"""Actual two-main-window GUI acceptance test (never run in background mode).

Uses normal GUI operators and real window/Scene contexts, with event-loop turns
between edits. Writes screenshots and a machine-readable result under /tmp.
"""

import json
from pathlib import Path
import sys
import tempfile
import traceback

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import blender_parametric_cad as addon
from blender_parametric_cad.blender import adapter
from blender_parametric_cad.blender.environments import instance_object
from blender_parametric_cad.blender.ui.tools import _context_tools
from blender_parametric_cad.mcp.blender_worker import BlenderCadWorker
from blender_parametric_cad.mcp.server import StdioMcpServer
from blender_parametric_cad.tests.blender_m11a_validation import PublicBridge, create_block, evaluated_instances

OUTPUT = Path(tempfile.gettempdir())
state = {}
bpy.context.preferences.view.show_splash = False


def override(window):
    area = next(area for area in window.screen.areas if area.type == 'VIEW_3D')
    region = next(region for region in area.regions if region.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=area, region=region)


def apply_width(width):
    with override(state['part_window']):
        ui = bpy.context.scene.parametric_cad_ui
        ui.active_feature_id = state['sketch']
        ui.active_sketch_id = state['sketch']
        ui.mode = 'SKETCH_EDIT'
        ui.active_sketch_dimension_id = state['rectangle']['width_dimension_id']
        ui.sketch_dimension_value_mm = width
        assert bpy.ops.parametric_cad.apply_dimension() == {'FINISHED'}


def setup():
    assert not bpy.app.background
    addon.register()
    worker = BlenderCadWorker()
    server = StdioMcpServer(PublicBridge(worker))
    create_block(server, 'Base', 80, 50, 20)
    guide, sketch, rectangle, _extrude = create_block(server, 'Guide', 20, 10, 30)
    state.update(guide=guide, sketch=sketch, rectangle=rectangle, part_window=bpy.context.window)
    with override(state['part_window']):
        assert bpy.ops.parametric_cad.open_assembly_window() == {'FINISHED'}
    state['assembly_window'] = next(window for window in bpy.context.window_manager.windows
                                    if window.scene.get('cad_scene_role') == 'ASSEMBLY')
    assert len(bpy.context.window_manager.windows) == 2
    assert state['assembly_window'].scene != state['part_window'].scene
    with override(state['assembly_window']):
        assert bpy.ops.parametric_cad.new_assembly() == {'FINISHED'}
        assert bpy.ops.parametric_cad.add_assembly_instance(part_id=guide, name='Guide Left') == {'FINISHED'}
        left = bpy.context.scene.parametric_cad_ui.selected_instance_id
        assert bpy.ops.parametric_cad.transform_assembly_instance(translation_mm=(-50, 0, 0)) == {'FINISHED'}
        assert bpy.ops.parametric_cad.add_assembly_instance(part_id=guide, name='Guide Right') == {'FINISHED'}
        right = bpy.context.scene.parametric_cad_ui.selected_instance_id
        assert bpy.ops.parametric_cad.transform_assembly_instance(translation_mm=(50, 0, 0), rotation_deg=(0, 0, 180)) == {'FINISHED'}
    state.update(left=left, right=right)
    state['transforms'] = {item: [list(row) for row in instance_object(item).matrix_world] for item in (left, right)}
    for window in bpy.context.window_manager.windows:
        with override(window):
            bpy.context.space_data.show_region_ui = True
            bpy.context.space_data.clip_start = .001
            bpy.ops.view3d.view_all(center=True)
    with override(state['part_window']):
        bpy.ops.parametric_cad.open_assembly_window()
    assert len(bpy.context.window_manager.windows) == 2, 'Open operator duplicated an existing window'
    return edit_first


def edit_first():
    apply_width(35)
    with override(state['part_window']):
        ui = bpy.context.scene.parametric_cad_ui
        state['editing'] = (ui.active_part_id, ui.active_feature_id, ui.active_sketch_id, ui.mode)
        assert len(_context_tools(bpy.context)) > 1
    return select_instance


def select_instance():
    scene = state['assembly_window'].scene
    displayed = evaluated_instances(scene)
    assert all(abs(displayed[state[key]]['width'] - .035) < 1e-6 for key in ('left', 'right')), displayed
    with override(state['assembly_window']):
        assert _context_tools(bpy.context) == ()
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        toolbar = ToolSelectPanelHelper._tool_class_from_space_type('VIEW_3D')
        visible = list(ToolSelectPanelHelper._tools_flatten(toolbar.tools_from_context(bpy.context)))
        assert not any(item and item.idname.startswith('parametric_cad.') for item in visible)
        assert bpy.ops.parametric_cad.select_assembly_instance(instance_id=state['right']) == {'FINISHED'}
        bpy.context.view_layer.update()
        adapter._on_depsgraph_update_post(scene, bpy.context.evaluated_depsgraph_get())
    return edit_source


def edit_source():
    ui = state['part_window'].scene.parametric_cad_ui
    assert state['editing'] == (ui.active_part_id, ui.active_feature_id, ui.active_sketch_id, ui.mode)
    selection = state['assembly_window'].scene.parametric_cad_ui.selected_instance_id
    # Activate Base first, then Edit Source Part must route the other window to Guide.
    document = adapter.load_document()
    ui.active_part_id = next(part.id for part in document.parts if part.id != state['guide'])
    with override(state['assembly_window']):
        assert bpy.ops.parametric_cad.edit_source_part() == {'FINISHED'}
    assert state['part_window'].scene.parametric_cad_ui.active_part_id == state['guide']
    assert state['assembly_window'].scene.get('cad_scene_role') == 'ASSEMBLY'
    assert state['assembly_window'].scene.parametric_cad_ui.selected_instance_id == selection
    apply_width(42)
    return preview


def preview():
    for key in ('part_window', 'assembly_window'):
        with override(state[key]):
            bpy.ops.wm.call_panel('INVOKE_DEFAULT', name='PARAMETRIC_CAD_PT_main', keep_open=True)
    return finish


def finish():
    displayed = evaluated_instances(state['assembly_window'].scene)
    assert all(abs(displayed[state[key]]['width'] - .042) < 1e-6 for key in ('left', 'right')), displayed
    assert state['transforms'] == {item: [list(row) for row in instance_object(item).matrix_world]
                                   for item in (state['left'], state['right'])}
    for key in ('part_window', 'assembly_window'):
        with override(state[key]):
            bpy.ops.screen.screenshot(filepath=str(OUTPUT / f'cad_m11a_{key}.png'))
    result = {'passed': True, 'blender': bpy.app.version_string, 'windows': len(bpy.context.window_manager.windows),
              'checks': ['independent real main windows', '20→35 mm GUI dimension edit updates both instances',
                         'Assembly selection preserves Part Sketch/Feature state', 'Edit Source Part routes to existing window',
                         '35→42 mm second GUI edit updates both instances', 'placements unchanged',
                         'toolbar isolated per Scene', 'existing window reused']}
    (OUTPUT / 'cad_m11a_gui_result.json').write_text(json.dumps(result, indent=2))
    print('M11A_TWO_WINDOW_GUI_PASS', json.dumps(result), flush=True)
    return None


next_step = setup


def tick():
    global next_step
    try:
        next_step = next_step()
        if next_step is not None:
            return 1.0
    except Exception:
        error = traceback.format_exc()
        (OUTPUT / 'cad_m11a_gui_result.json').write_text(json.dumps({'passed': False, 'error': error}, indent=2))
        print(error, flush=True)
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=2.0)
    return None


bpy.app.timers.register(tick, first_interval=2.0)
