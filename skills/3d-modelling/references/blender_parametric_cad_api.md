# Blender Parametric CAD API

This reference describes the public API in the Blender Parametric CAD
extension (current extension release 0.10.0). It covers both direct Python
scripts and the dependency-free MCP bridge for AI-generated, non-UI modeling.

## MCP bridge

Run `mcp/server.py` with Python as an MCP stdio server. The bridge starts one
background Blender 5.1.2 worker on the first tool call, proxies all subsequent
calls over a private localhost connection, and keeps that worker alive for the
MCP session. Blender is launched once per MCP session rather than once per
operation. Blender's own stdout is isolated from the MCP stream.

Example client entry:

```json
{
  "mcpServers": {
    "blender-parametric-cad": {
      "command": "python3",
      "args": ["/absolute/path/to/blender_parametric_cad/mcp/server.py"],
      "env": {
        "BLENDER_CAD_EXECUTABLE": "/Applications/Blender.app/Contents/MacOS/Blender",
        "BLENDER_CAD_FILE": "/absolute/path/to/model.blend"
      }
    }
  }
}
```

`BLENDER_CAD_EXECUTABLE` may be omitted when `blender` is on `PATH`.
`BLENDER_CAD_FILE` is optional; when set it is opened at worker startup and
mutations are autosaved to the same path. Without it, call `cad_save_scene`.
MCP tool inputs use millimeters and degrees; the direct Python API below uses
meters and radians as documented in [Units and identifiers](#units-and-identifiers).

The MCP tools are:

| Group | Tools |
| --- | --- |
| Document | `cad_status`, `cad_create_part`, `cad_set_active_part`, `cad_delete_part`, `cad_save_scene` |
| Sketch | `cad_create_sketch`, `cad_add_geometry`, `cad_update_geometry`, `cad_delete_geometry`, `cad_profile`, `cad_delete_region`, `cad_restore_region` |
| Features | `cad_create_extrude`, `cad_create_revolve`, `cad_update_feature`, `cad_delete_feature`, `cad_suppress_feature`, `cad_rollback`, `cad_rebuild` |
| Output | `cad_export_part` |

The server exposes the same documentation through MCP resources
`cad://skill/3d-modelling` and `cad://api-reference`.

A minimal MCP modeling sequence is:

```text
cad_create_part({"name": "Bracket"})
cad_create_sketch({"name": "Base", "plane": "XY"})
cad_add_geometry({
  "sketch_id": "<sketch UUID>",
  "geometry": {"type": "RECTANGLE", "x_mm": -40, "y_mm": -25,
               "width_mm": 80, "height_mm": 50}
})
cad_create_extrude({"sketch_id": "<sketch UUID>", "distance_mm": 20,
                    "operation": "NEW", "depth_mode": "BLIND"})
cad_export_part({"part_id": "<part UUID>", "filepath": "/tmp/bracket.stl",
                 "file_format": "STL"})
```

Use the IDs returned by each call; never infer them from Blender object names.
For an Add/Remove feature, create or edit the source Sketch first, then pass
the previous body feature through the persistent history (the worker computes
the required UUID dependencies automatically).

## Fast path: build without UI

Create the persistent feature graph with the Blender-independent classes, save
it to the current scene, and rebuild once. This avoids modal drawing tools and
computer-use clicks.

```python
import math
import bpy

from blender_parametric_cad.core.document import CadDocument
from blender_parametric_cad.core.part import Part
from blender_parametric_cad.core.references import AxisReference
from blender_parametric_cad.features.extrude import ExtrudeFeature
from blender_parametric_cad.features.revolve import RevolveFeature
from blender_parametric_cad.sketch.numeric import set_rectangle
from blender_parametric_cad.sketch.sketch import SketchFeature
from blender_parametric_cad.blender.adapter import (
    rebuild_part,
    save_document_to_scene,
)

scene = bpy.context.scene
document = CadDocument()
part = Part(name="AI Part")
document.add_part(part)

base = SketchFeature.on_plane("Base Sketch", "XY")
set_rectangle(base, -0.04, -0.025, 0.08, 0.05)
part.add_feature(base)

pad = ExtrudeFeature(
    sketch_id=base.id,
    distance=0.02,
    direction=1,
    operation="NEW",
    depth_mode="BLIND",
)
part.add_feature(pad)

cut_profile = SketchFeature.on_plane("Revolve Cut", "XZ")
set_rectangle(cut_profile, 0.0, 0.0, 0.01, 0.02)
part.add_feature(cut_profile)

cut = RevolveFeature(
    sketch_id=cut_profile.id,
    axis_reference=AxisReference(axis="Z", direction=-1),
    angle=math.radians(180.0),
    operation="REMOVE",
    dependencies=[cut_profile.id, pad.id],
)
part.add_feature(cut)

save_document_to_scene(scene, document)
result = rebuild_part(scene, part.id)
if not result.success:
    raise RuntimeError("; ".join(error.message for error in result.errors))
```

`rebuild_part` creates or replaces only the generated result for the requested
Part Studio. The generated Blender object is tagged with `cad_generated=True`
and its Part Studio UUID in `cad_part_id`.

## Units and identifiers

- Core 2D coordinates, radii, diameters, and Extrude distances are meters.
- Core angles (`SketchArc`, `RevolveFeature`) are radians.
- UI state fields ending in `_mm` and `_deg` use millimeters and degrees.
- Every `Feature`, `Part`, and `SketchEntity` has a UUID. Keep references by
  UUID, never by Blender object name or mesh polygon index.
- Feature status values are `NOT_EVALUATED`, `OK`, `ERROR`, and `SUPPRESSED`.

## Add-on and scene bridge

```python
import blender_parametric_cad

blender_parametric_cad.register()    # only once if the add-on is not enabled
blender_parametric_cad.unregister()
```

The extension should normally be enabled through Blender first; do not call
`register()` repeatedly in the same session.

```python
from blender_parametric_cad.blender.adapter import (
    load_document_from_scene,
    save_document_to_scene,
    rebuild_part,
    export_part,
    remove_part_geometry,
    rename_part_geometry,
)
```

- `load_document_from_scene(scene) -> CadDocument`
- `save_document_to_scene(scene, document) -> None`
- `rebuild_part(scene, part_id=None) -> EvaluationResult`
- `remove_part_geometry(part_id) -> None`
- `rename_part_geometry(part_id, part_name) -> None`
- `export_part(scene, part_id, filepath, file_format="STL") -> str`

`export_part` supports `STL`, `OBJ`, and `PLY`. It rebuilds the requested
Part Studio, selects only its generated result object, exports it, restores the
previous Blender selection, and returns the final path. If the path has no
extension, one is added from the selected format. It raises `ValueError` for an
unknown Part Studio, invalid format, missing filepath, or failed rebuild, and
`RuntimeError` if Blender's exporter does not finish.

Example:

```python
path = export_part(
    bpy.context.scene,
    part.id,
    "/tmp/bracket.stl",
    "STL",
)
```

## Persistent document model

### `CadDocument`

```python
from blender_parametric_cad.core.document import CadDocument

CadDocument(parts=[], active_part_id=None, schema_version=2)
```

Methods and property:

- `get_part(part_id) -> Part | None`
- `get_active_part() -> Part | None`
- `set_active_part(part_id | None) -> Part | None`; unknown IDs raise
  `ValueError`.
- `add_part(part) -> None`; also makes it active.
- `remove_part(part_id) -> Part | None`; updates the active Part Studio.
- `active_part -> Part | None`
- `to_dict() -> dict`
- `CadDocument.from_dict(data) -> CadDocument`

### `Part`

```python
from blender_parametric_cad.core.part import Part

Part(id=<uuid>, name="Part001", features=[], rollback_index=None)
```

- `add_feature(feature) -> None`
- `remove_feature(feature_id) -> Feature | None` (single entry)
- `get_feature(feature_id) -> Feature | None`
- `get_feature_index(feature_id) -> int | None`
- `next_feature_name(prefix) -> str`
- `rollback_index`: `None` or zero-based last evaluated feature index

History helpers:

```python
from blender_parametric_cad.core.part import (
    get_recursive_dependents,
    delete_feature,
)
```

- `get_recursive_dependents(part, feature_id) -> list[str]`
- `delete_feature(part, feature_id) -> list[Feature]`: cascades through all
  UUID-dependent downstream features and clears rollback.

### `Feature`

Base fields shared by Sketch, Extrude, and Revolve:

```python
Feature(
    id=<uuid>,
    name="Feature",
    suppressed=False,
    status="NOT_EVALUATED",
    error_message="",
    dependencies=[],
)
```

`feature_type` is `SKETCH`, `EXTRUDE`, or `REVOLVE` for concrete features.

## Sketch API

### Sketch entities

```python
from blender_parametric_cad.sketch.entities import (
    SketchEntity,
    SketchLine,
    SketchCircle,
    SketchArc,
)
```

```python
SketchLine(x1, y1, x2, y2, construction=False)
SketchCircle(cx, cy, radius, construction=False)
SketchArc(
    cx, cy, radius,
    start_angle, end_angle,
    construction=False,
)
```

`construction=True` geometry is retained in the Sketch but ignored by profile
detection and general snapping. `SketchArc` also provides:

- `point(angle) -> (x, y)`
- `start_point`
- `end_point`

Angles increase counter-clockwise; a negative end-minus-start value creates a
clockwise sweep.

### `SketchFeature`

```python
from blender_parametric_cad.sketch.sketch import SketchFeature
```

Fields include `plane_reference`, `origin`, `x_axis`, `y_axis`, `entities`, and
`deleted_regions`.

Constructors:

- `SketchFeature.on_plane(name, plane_type)` where `plane_type` is `XY`, `XZ`,
  or `YZ`.
- `SketchFeature.on_feature_plane(name, feature_id, role="END_PLANE")`.
  Currently only an Extrude `END_PLANE` is supported.
- `SketchFeature.on_face(name, topo_reference)` for supported Extrude faces.

Other functions:

- `sketch_to_world(sketch, u, v) -> (x, y, z)`
- `sketch_normal(sketch) -> (x, y, z)`
- `sketch.apply_resolved_plane(resolved_plane) -> None`

### Numeric dimensions

```python
from blender_parametric_cad.sketch.numeric import (
    rectangle_entity_ids,
    rectangle_parameters,
    set_rectangle,
    circle_parameters,
    set_circle,
    arc_parameters,
    set_arc,
)
```

- `set_rectangle(sketch, x, y, width, height, entity_id=None)`
- `rectangle_parameters(sketch, entity_id=None)` returns
  `(x, y, width, height)` or `None`.
- `rectangle_entity_ids(sketch, entity_id=None)` returns the four line UUIDs.
- `set_circle(sketch, x, y, diameter, entity_id=None)`
- `circle_parameters(sketch, entity_id=None)` returns `(cx, cy, diameter)` or
  `None`.
- `set_arc(sketch, x, y, radius, start_angle, end_angle, entity_id=None)`
- `arc_parameters(sketch, entity_id=None)` returns
  `(cx, cy, radius, start_angle, end_angle)` or `None`.

When a Sketch is empty, the setters create the requested geometry. When editing
an existing shape, pass its UUID to preserve identity. Width, height, radius,
and diameter must be positive; an arc's start and end angles must differ.

### Profile detection and region deletion

```python
from blender_parametric_cad.sketch.profile import (
    ProfileDetector,
    ProfileLoop,
    SketchProfile,
    ProfileResult,
)
```

- `ProfileDetector().detect(sketch) -> ProfileResult`: validates the active
  profile while honoring `sketch.deleted_regions`.
- `ProfileDetector().detect_regions(sketch) -> tuple[ProfileLoop, ...]`:
  returns all regions, including deleted ones.
- `ProfileDetector().detect_entities(entities, excluded_regions=())`.
- `ProfileDetector.area(points) -> float`.
- `ProfileDetector.point_in_loop(point, loop) -> bool`.
- `SketchProfile.iter_loops()` returns the active loops.

`ProfileResult` has `success`, `profile`, and `message`. `SketchProfile.kind`
is normally `CIRCLE`, `RECTANGLE`, `POLYGON`, `ARC_LOOP`, or `COMPOSITE`.
`ProfileLoop` has `points`, `entity_ids`, `region_id`, and optional `circle`.

To delete a bounded region without changing geometry:

```python
regions = ProfileDetector().detect_regions(sketch)
sketch.deleted_regions.append(regions[index].region_id)
```

The region ID is derived from the sorted boundary UUIDs. To restore it, remove
that ID from `deleted_regions`. If geometry is removed or replaced, clear stale
region IDs before detecting again.

Supported profiles are circles, simple polygons, mixed line/arc loops, multiple
closed loops, and split closed boundaries. Open, branching, self-intersecting,
or unsupported geometry is rejected.

### Snapping

```python
from blender_parametric_cad.sketch.snapping import (
    intersection_points,
    reference_points,
    snap_targets,
    snap_point,
)
```

- `intersection_points(entities, tolerance=1e-7)`
- `reference_points(entities, tolerance=1e-7)` returns line endpoints,
  circle/arc centers, and arc endpoints.
- `snap_targets(entities, tolerance=1e-7)` combines intersections and reference
  points.
- `snap_point(entities, point, tolerance=0.0015)` returns the nearest discrete
  target or curve projection within tolerance.

Construction geometry is excluded from all four helpers.

## Planes and semantic references

### `SketchPlaneReference`

```python
from blender_parametric_cad.sketch.plane import (
    SketchPlaneReference,
    PlaneResolver,
    ResolvedPlane,
    PlaneResolutionError,
    resolve_sketch_plane_from_history,
)
```

Reference types:

- `DATUM`: `datum_plane` is `XY`, `XZ`, or `YZ`.
- `FEATURE_PLANE`: `feature_id` plus `role="END_PLANE"`.
- `FACE`: `feature_id`, role, and optional `source_entity_id`.

- `PlaneResolver().resolve(reference, context) -> ResolvedPlane`
- `resolve_sketch_plane_from_history(part, sketch_id) -> ResolvedPlane`

`ResolvedPlane` contains `origin`, `x_axis`, `y_axis`, and `normal`.

### `TopoReference` and `AxisReference`

```python
from blender_parametric_cad.core.references import (
    TopoReference,
    AxisReference,
    SelectionReference,
)
```

`TopoReference(feature_id, role, source_entity_id=None, reference_type="FACE")`
supports `START_FACE`, `END_FACE`, and line-based `SIDE_FACE` from a simple
`NEW` Extrude. It provides `to_dict()` and `from_dict(data)`.

`AxisReference` fields:

```python
AxisReference(
    reference_type="DATUM_AXIS",  # or "SKETCH_LINE"
    axis="Z",                     # X / Y / Z for datum axes
    sketch_id=None,
    entity_id=None,
    direction=1,                   # normalized to 1 or -1
)
```

It also provides `to_dict()` and `from_dict(data)`. For a SketchLine axis,
provide `sketch_id` and `entity_id`; `direction=-1` reverses the sweep axis.
`SelectionReference` is a generic non-persistent container for future selection
flows.

## Feature operations

### `ExtrudeFeature`

```python
from blender_parametric_cad.features.extrude import ExtrudeFeature

ExtrudeFeature(
    sketch_id="...",
    distance=0.02,
    direction=1,
    operation="NEW",       # NEW / ADD / REMOVE / legacy CUT
    depth_mode="BLIND",    # BLIND / THROUGH_ALL
)
```

`NEW` and `ADD` require `BLIND`; `REMOVE` supports `BLIND` and `THROUGH_ALL`.
For Add/Remove, include the previous body Feature UUID in `dependencies` when
constructing the graph directly.

### `RevolveFeature`

```python
from blender_parametric_cad.features.revolve import RevolveFeature

RevolveFeature(
    sketch_id="...",
    axis_reference=AxisReference(axis="Z", direction=-1),
    angle=3.141592653589793,
    operation="REMOVE",    # NEW / ADD / REMOVE
)
```

Angles must be greater than zero and no more than 360 degrees. Reverse axis is
meaningful for partial sweeps; a full 360-degree sweep has the same geometric
occupancy in either direction. Revolve Add/Remove tools normalize face winding
before Blender Boolean evaluation.

## Evaluation and geometry backends

```python
from blender_parametric_cad.core.evaluator import (
    PartEvaluator,
    EvaluationResult,
    EvaluationContext,
    EvaluationError,
)
```

- `PartEvaluator(geometry_backend).evaluate(part) -> EvaluationResult`
- `EvaluationResult.success`, `.body`, `.errors`, `.context`
- `EvaluationError.feature_id`, `.feature_name`, `.message`
- `EvaluationContext.part`, `.current_body`, `.resolved_planes`,
  `.evaluated_features`, `.face_provenance`

`GeometryBackend` is the replaceable kernel interface:

- `create_extrusion(sketch, profile, distance, direction)`
- `create_extrusion_tool(sketch, profile, body, direction)`
- `create_blind_extrusion_tool(sketch, profile, distance, direction)`
- `revolve_profile(sketch, profile, axis_origin, axis_direction, angle)`
- `register_extrude_provenance(body, feature_id, profile)`
- `face_provenance(body)`
- `boolean_difference(body, tool)`
- `boolean_union(body, tool)`

`BlenderMeshBackend` is the concrete Blender mesh implementation. A custom
exact-kernel backend can implement the same interface without changing the
persistent document model.

`SketchSolver().solve(sketch) -> SolverResult` currently performs basic
zero-length and non-positive-radius validation; it is not yet a constraint
solver.

## Serialization schema

```python
from blender_parametric_cad.core.serialization import (
    dumps,
    loads,
    document_to_dict,
    document_from_dict,
    feature_to_dict,
    feature_from_dict,
    entity_to_dict,
    entity_from_dict,
    migrate_document_data,
)
```

`dumps(document)` and `loads(value)` use compact schema-v2 JSON. The top-level
shape is:

```json
{
  "schema_version": 2,
  "active_part_id": "part-uuid",
  "parts": [
    {
      "id": "part-uuid",
      "name": "Part Studio 1",
      "rollback_index": null,
      "features": []
    }
  ]
}
```

Sketch feature records contain `plane_reference`, `entities`, and
`deleted_regions`. Entity records use `entity_type` values `LINE`, `CIRCLE`, or
`ARC`. Extrude records contain `sketch_id`, `distance`, `direction`,
`operation`, and `depth_mode`. Revolve records contain `sketch_id`,
`axis_reference`, `angle`, and `operation`. Schema-v1 documents migrate to v2
with `migrate_document_data`.

## Blender operator façade

Operators are convenient for UI-compatible scripts but require the active scene
and, for modal tools, a 3D View context. Set state through:

```python
ui = bpy.context.scene.parametric_cad_ui
```

### Part Studio and history operators

```python
bpy.ops.parametric_cad.new_part()
bpy.ops.parametric_cad.rename_part(name="Bracket")
bpy.ops.parametric_cad.delete_part(part_id=part_id)
bpy.ops.parametric_cad.select_feature(feature_id=feature_id)
bpy.ops.parametric_cad.rename_feature(feature_id=feature_id, name="Base")
bpy.ops.parametric_cad.delete_feature(feature_id=feature_id)
bpy.ops.parametric_cad.rollback_here()
bpy.ops.parametric_cad.roll_forward()
bpy.ops.parametric_cad.toggle_suppression()
```

`delete_feature` cascades through dependent Features. `toggle_suppression`,
`rollback_here`, and `roll_forward` operate on the active Feature/Part Studio.

### Sketch lifecycle and numeric operators

```python
bpy.ops.parametric_cad.new_sketch()
bpy.ops.parametric_cad.edit_sketch()
bpy.ops.parametric_cad.finish_sketch()
bpy.ops.parametric_cad.cancel_sketch()
bpy.ops.parametric_cad.clear_sketch()
bpy.ops.parametric_cad.numeric_rectangle()
bpy.ops.parametric_cad.numeric_circle()
bpy.ops.parametric_cad.numeric_arc()
```

Relevant UI fields:

```python
ui.active_part_id
ui.active_feature_id
ui.active_sketch_id
ui.active_sketch_entity_id
ui.new_sketch_reference       # DATUM|XY, DATUM|XZ, DATUM|YZ,
                              # FEATURE|<extrude_uuid>|END_PLANE
ui.selected_face_reference    # serialized TopoReference JSON
```

Numeric fields are `rectangle_x_mm`, `rectangle_y_mm`,
`rectangle_width_mm`, `rectangle_height_mm`, `circle_x_mm`, `circle_y_mm`,
`circle_diameter_mm`, `arc_x_mm`, `arc_y_mm`, `arc_radius_mm`,
`arc_start_deg`, and `arc_end_deg`.

### Feature creation/editing operators

```python
bpy.ops.parametric_cad.extrude()
bpy.ops.parametric_cad.apply_extrude()
bpy.ops.parametric_cad.cut()       # legacy Remove Through All
bpy.ops.parametric_cad.revolve()
bpy.ops.parametric_cad.apply_revolve()
```

Set these fields before calling them:

```python
ui.extrude_distance_mm
ui.extrude_operation       # NEW / ADD / REMOVE
ui.extrude_depth_mode      # BLIND / THROUGH_ALL
ui.revolve_operation       # NEW / ADD / REMOVE
ui.revolve_axis_type       # DATUM_AXIS / SKETCH_LINE
ui.revolve_axis            # X / Y / Z
ui.revolve_axis_line_id
ui.revolve_axis_reverse
ui.revolve_angle_deg
```

### Per-Part export operator

```python
bpy.ops.parametric_cad.export_part(
    part_id=part_id,
    filepath="/tmp/part.obj",
    file_format="OBJ",
)
```

The panel exposes the same operation for the active Part Studio. The direct
`export_part(...)` function is preferred for AI scripts because it accepts an
explicit Part UUID and returns the exported path.

### Modal sketch/selection operators

```python
bpy.ops.parametric_cad.draw_line()
bpy.ops.parametric_cad.draw_rectangle()
bpy.ops.parametric_cad.draw_circle()
bpy.ops.parametric_cad.draw_arc()
bpy.ops.parametric_cad.select_tool()
bpy.ops.parametric_cad.delete_region()
bpy.ops.parametric_cad.delete_geometry(selected_only=False)
bpy.ops.parametric_cad.select_face()
```

These are intended for human viewport interaction. Direct AI scripts should
append entities, use the numeric helpers, and construct semantic references
instead of synthesizing mouse events. `track_sketch_cursor` is an internal
cursor tracker and should not be called by model-building scripts.

## Runtime-only viewport helpers

These functions affect display feedback only and do not modify persistent CAD
data:

- `blender.viewport.sketch_overlay.set_preview`, `clear_preview`
- `set_snap_preview`, `clear_snap_preview`
- `set_face_hover`, `set_face_selection`, `clear_face_selection`
- `tag_redraw`, `start`, `stop`
- `blender.viewport.provenance.set_face_provenance`,
  `get_face_provenance`, `clear_face_provenance`

The provenance registry is rebuilt after each evaluation and must not be used
as a persistent face identity.
