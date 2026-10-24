"""Run outside Blender: JSON-RPC discovery/dispatch through a real Blender socket.

Uses an isolated loopback endpoint and one background Blender process. Set
BLENDER_CAD_GPU_BACKEND=metal on macOS builds which ship only Metal.
"""

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from blender_parametric_cad.mcp.server import BlenderBridge, StdioMcpServer


def main():
    with tempfile.TemporaryDirectory(prefix='cad_m11a_transport_') as directory:
        bridge = BlenderBridge(visible=False, gpu_backend=os.environ.get('BLENDER_CAD_GPU_BACKEND'),
                               port=19811, endpoint_file=str(Path(directory) / 'endpoint.json'))
        server = StdioMcpServer(bridge)

        def call(tool_name, **arguments):
            response = server.handle({'id': 1, 'method': 'tools/call', 'params': {
                'name': tool_name, 'arguments': arguments}})
            assert 'error' not in response, response
            assert not response['result']['isError'], response
            return response['result']['structuredContent']

        try:
            tools = server.handle({'id': 1, 'method': 'tools/list'})['result']['tools']
            assert any(tool['name'] == 'cad_add_assembly_instance' for tool in tools)
            sources = []
            for name, width, height, depth in [('A', 80, 50, 20), ('B', 20, 10, 30)]:
                part_id = call('cad_create_part', name=name)['part']['id']
                sketch_id = call('cad_create_sketch', part_id=part_id, plane='XY')['sketch']['id']
                rectangle = call('cad_sketch_add_rectangle', sketch_id=sketch_id, width_mm=width, height_mm=height)
                assert call('cad_create_extrude', sketch_id=sketch_id, distance_mm=depth, operation='NEW')['rebuild']['success']
                sources.append((part_id, sketch_id, rectangle['rectangle_id']))
            assembly_id = call('cad_create_assembly', name='Transport Assembly')['assembly']['id']
            call('cad_add_assembly_instance', assembly_id=assembly_id, part_studio_id=sources[0][0], name='A')
            ids = []
            for name, x in [('B1', -50), ('B2', 50)]:
                result = call('cad_add_assembly_instance', assembly_id=assembly_id, part_studio_id=sources[1][0],
                              name=name, translation_mm=[x, 0, 0], rotation_deg=[0, 0, 180 if x > 0 else 0])
                assert result['ok'] and result['part_studio_id'] == sources[1][0]
                ids.append(result['instance_id'])
            before = call('cad_get_assembly', assembly_id=assembly_id)['assembly']
            call('blender_execute_python', code="bpy.context.window.scene = next(scene for scene in bpy.data.scenes if scene.get('cad_scene_role') == 'ASSEMBLY')")
            assert call('cad_sketch_update_rectangle', sketch_id=sources[1][1], rectangle_id=sources[1][2], width_mm=35)['rebuild']['success']
            after = call('cad_get_assembly', assembly_id=assembly_id)['assembly']
            assert after == before
            geometry = call('cad_inspect_geometry', part_id=sources[1][0])
            assert abs(geometry['bbox_mm']['max_mm'][0] - geometry['bbox_mm']['min_mm'][0] - 35) < .001
            assert len(call('cad_status')['generated_objects']) == 2
            assert len(call('cad_get_document')['document']['assemblies'][0]['instances']) == 3
            failure = server.handle({'id': 1, 'method': 'tools/call', 'params': {
                'name': 'cad_delete_part', 'arguments': {'part_id': sources[1][0]}}})['result']
            assert failure['isError'] and failure['structuredContent']['error_code'] == 'PART_IN_USE'
            call('cad_save_scene', filepath=str(Path(directory) / 'assembly.blend'))
            print('M11A_MCP_SOCKET_PASS: public JSON-RPC tools, 2 Parts, 3 instances, independent placement, live update, active Assembly context')
        finally:
            bridge.close()


if __name__ == '__main__':
    main()
