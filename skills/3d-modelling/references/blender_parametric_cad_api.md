# Blender Parametric CAD API

This reference describes the public API in the Blender Parametric CAD
extension (current extension release 0.16.6). It covers both direct Python
scripts and the dependency-free MCP bridge for AI-generated, non-UI modeling.

## MCP bridge

Run `mcp/server.py` with Python as an MCP stdio server. The bridge first reads
the shared CAD service endpoint and connects to an already-open Blender 5.1.2
window. If no live endpoint is available, it starts one visible worker and
publishes the endpoint for future MCP processes. An endpoint lock prevents
concurrent/restarted MCP clients from opening duplicate Blender windows; an
unresponsive live process is reported as an error instead of being bypassed.
The worker polls the socket through `bpy.app.timers`, leaving Blender's normal
event loop available for viewport redraws and human edits. The same window
remains listening after the stdio MCP client disconnects.

Example client entry:

```json
{
  "mcpServers": {
    "blender-parametric-cad": {
      "command": "python3",
      "args": ["/absolute/path/to/blender_parametric_cad/mcp/server.py"],
      "env": {
        "BLENDER_CAD_EXECUTABLE": "/Applications/Blender.app/Contents/MacOS/Blender",
        "BLENDER_CAD_PORT": "9800",
        "BLENDER_CAD_ENDPOINT_FILE": "/tmp/blender_parametric_cad_mcp.json",
        "BLENDER_CAD_AUTOSTART": "1",
        "BLENDER_CAD_FILE": "/absolute/path/to/model.blend"
      }
    }
  }
}
```

`BLENDER_CAD_EXECUTABLE` may be omitted when `blender` is on `PATH`.
`BLENDER_CAD_FILE` is optional; when set it is opened at worker startup and
mutations are autosaved to the same path. `BLENDER_CAD_AUTOSAVE` can set a
separate autosave target. Without either path, call `cad_save_scene`. When an
existing endpoint is found, `BLENDER_CAD_FILE` is ignored so the already-open
Blender window remains authoritative. The endpoint path defaults to the system
temporary directory when
`BLENDER_CAD_ENDPOINT_FILE` is omitted. For the exact-window workflow, enable
the extension in the desired open Blender window, expand **CAD MCP Service**,
click **Start Service in This Window**, and start/restart the MCP client once. Use
`BLENDER_CAD_AUTOSTART=0` (or `--no-autostart`) to require that exact-window
service and prohibit fallback Blender startup. Use
`--headless` or `BLENDER_CAD_HEADLESS=1` for a worker without a window. On
macOS headless mode defaults to `--gpu-backend opengl` to avoid Blender 5.1.2
Metal initialization crashes; `--gpu-backend` and
`BLENDER_CAD_GPU_BACKEND` accept `opengl`, `metal`, or `vulkan`.
Enable the extension in Blender Preferences when the visible worker should
also expose the CAD panel and interactive sketch tools. The panel's **CAD MCP
Service** box is the explicit binding point for the current window; the
extension's semantic `cad_*` protocol is not automatically provided by a
generic third-party Blender MCP add-on.
Starting the service from that box probes the shared endpoint before binding.
If a reachable CAD service already owns the port, startup is refused with its
host and port so the existing Blender window can remain authoritative; if an
unrelated process owns the port, choose a different port and keep the endpoint
file unchanged for MCP discovery.
The visible worker imports bundled modules through Blender's qualified
`bl_ext.<repository>.blender_parametric_cad` namespace. Therefore Preferences
warnings of the form `Policy violation with top level module` are not a port or
other-add-on conflict; restart Blender once after upgrading to clear modules
left in memory by an older worker.
Workers from releases before 0.15.0 used a private per-client socket and are
not reconnectable after their MCP parent exits; close those old orphan windows
once after upgrading.
MCP tool inputs use millimeters and degrees; the direct Python API below uses
meters and radians as documented in [Units and identifiers](#units-and-identifiers).

The MCP tools are:

| Group | Tools |
| --- | --- |
| Document | `cad_status`, `cad_create_part`, `cad_set_active_part`, `cad_delete_part`, `cad_validate_document`, `cad_save_scene` |
| Sketch | `cad_create_sketch`, `cad_add_geometry`, `cad_update_geometry`, `cad_delete_geometry`, `cad_profile`, `cad_delete_region`, `cad_restore_region` |
| Features | `cad_create_extrude`, `cad_create_revolve`, `cad_create_transform`, `cad_create_mirror`, `cad_update_feature`, `cad_delete_feature`, `cad_suppress_feature`, `cad_rollback`, `cad_rebuild` |
| Output | `cad_export_part` |

The server exposes the same documentation through MCP resources
`cad://skill/3d-modelling` and `cad://api-reference`.

The Blender add-on registration is reload-safe: stale or partially registered
UI RNA classes are replaced before the current Scene properties are attached.
The N-panel uses staged workspaces: while a Sketch is being edited, the native
left 3D View toolbar exposes CAD geometry and cleanup tools; finishing the
Sketch returns to **Model**. The selected Sketch then presents vertical
**Create Extrude**/**Create Revolve** actions, while a selected body presents
**Create Transform**/**Create Mirror**. The matching left-toolbar feature icon
is the single parameter editor: it shows the source or selected history item,
all operation fields, **Name**, **Rename**, and **Apply & Rebuild** beside the
icon. Transform's Translation and Rotation groups are collapsed by default to
keep the complete viewport visible. Rollback and roll-forward remain under
**Model → History**, and Model
also exposes vertical Feature Actions for delete, suppress, and Sketch edit;
there is no separate Features workspace.
When Sketch Edit is not active, the native toolbar exposes the same contextual
Extrude/Revolve/Transform/Mirror tools for the selected history item, with the
create or edit parameters rendered beside the active icon. Model buttons select
the matching tool automatically when you want an immediate create action
without a viewport click. Sketch drawing tools consume the first 3D View click
as the first point.

The N-panel's **Measure** page and the left-toolbar **CAD Measure** ruler are a
non-destructive point-to-point inspection workflow. Click two viewport points;
the picker uses a screen-pixel tolerance to prefer mesh vertices and, during
Sketch Edit, Sketch endpoints/intersections. The result is shown in the
viewport and stored in transient UI state as a true 3D distance in millimeters,
signed world-axis components, point labels, and A/B coordinates. Press Esc to
leave the modal tool, use Start / Reset for another measurement, or clear the
result from the panel. It does not add a Feature or change the CAD JSON.

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
cad_create_transform({"part_id": "<part UUID>",
                      "translation_mm": {"x": 0, "y": 0, "z": 0},
                      "rotation_deg": {"x": 0, "y": -12, "z": 0}})
cad_create_mirror({"part_id": "<part UUID>",
                   "source_feature_id": "<additive feature UUID>",
                   "mirror_plane": "YZ"})
cad_export_part({"part_id": "<part UUID>", "filepath": "/tmp/bracket.stl",
                 "file_format": "STL"})
```

Use the IDs returned by each call; never infer them from Blender object names.
For an Add/Remove feature, create or edit the source Sketch first, then pass
the previous body feature through the persistent history (the worker computes
the required UUID dependencies automatically).

M5 MCP feature calls use these fields:

- `cad_create_sketch`: add `offset_mm` to offset the datum/face/feature support
  along its resolved normal.
- `cad_create_transform`: optional `part_id`, `translation_mm`, and
  `rotation_deg`; each vector is an object such as `{"x": 0, "y": -12,
  "z": 0}` (translation is mm, rotation is degrees).
- `cad_create_mirror`: `source_feature_id` must be an earlier additive Extrude
  or Revolve; `mirror_plane` is `"XY"`, `"XZ"`, `"YZ"`, or a semantic object with
  `type`, `feature_id`, `role`, and optional `offset_mm`.
- `cad_update_feature` accepts `offset_mm` for Sketch support planes,
  `translation_mm`/`rotation_deg` for Transform, `source_feature_id`/`mirror_plane`
  for Mirror, and the existing Extrude or Revolve fields for those feature types.

For example, a six-line closed guide profile can be appended with six `LINE`
entities in exact local millimeter coordinates, followed by `cad_create_extrude`
with `operation: "ADD"`; the generic detector does not special-case rectangles.
Two independent `CIRCLE` entities in one Sketch are emitted as two loops and
can be used by `REMOVE` + `THROUGH_ALL` to cut both holes in one feature.

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
- Transform translations are meters and XYZ Euler rotations are radians in the
  core (`TransformFeature`); MCP and Blender UI inputs use millimeters/degrees.
- UI state fields ending in `_mm` and `_deg` use millimeters and degrees.
- Every `Feature`, `Part`, and `SketchEntity` has a UUID. Keep references by
  UUID, never by Blender object name or mesh polygon index.
- Feature status values are `NOT_EVALUATED`, `OK`, `ERROR`, `BLOCKED`, and
  `SUPPRESSED`.  When a rebuild fails, the generated viewport result is left
  untouched; downstream features are marked `BLOCKED` with the upstream reason.

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
    CadDocumentError,
    addon_enabled,
    load_document_from_scene,
    save_document_to_scene,
    rebuild_part,
    export_part,
    remove_part_geometry,
    rename_part_geometry,
    sync_active_part_from_object,
    validate_cad_document,
)
```

- `addon_enabled() -> bool`
- `load_document_from_scene(scene) -> CadDocument`; raises `CadDocumentError`
  with an actionable enable/re-enable message when the extension is missing,
  scene JSON is invalid, or schema/UUID validation fails.
- `save_document_to_scene(scene, document) -> None`
- `rebuild_part(scene, part_id=None) -> EvaluationResult`
- `sync_active_part_from_object(scene, object) -> str | None`; uses a generated
  object's `cad_part_id` to switch the persistent active Part Studio.
- `validate_cad_document(scene) -> list[str]`; read-only checks for dangling
  dependencies, invalid Sketch/profile sources, failed features, and empty
  generated results.
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

Generated `*_Result` objects are disposable outputs and are treated as
read-only. If one is selected, the CAD panel offers **Edit CAD History**; a
double-click enters the source Sketch when the terminal Feature has one.
Editing a result mesh directly and then rebuilding is rejected so those edits
cannot be silently lost.

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
    previous_body_feature,
)
```

- `get_recursive_dependents(part, feature_id) -> list[str]`
- `delete_feature(part, feature_id) -> list[Feature]`: cascades through all
  UUID-dependent downstream features and clears rollback.
- `previous_body_feature(part, before_index=None) -> Feature | None`: returns
  the nearest unsuppressed `EXTRUDE`, `REVOLVE`, `TRANSFORM`, or `MIRROR`
  history entry that supplies the current body.

### `Feature`

Base fields shared by Sketch, Extrude, Revolve, Transform, and Mirror:

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

`feature_type` is `SKETCH`, `EXTRUDE`, `REVOLVE`, `TRANSFORM`, or `MIRROR` for
concrete features.

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

- `SketchFeature.on_plane(name, plane_type, offset=0.0)` where `plane_type` is
  `XY`, `XZ`, or `YZ`; `offset` is meters along the resolved normal.
- `SketchFeature.on_feature_plane(name, feature_id, role="END_PLANE", offset=0.0)`.
  Currently only an Extrude `END_PLANE` is supported.
- `SketchFeature.on_face(name, topo_reference, offset=0.0)` for supported
  Extrude faces.

Other functions:

- `sketch_to_world(sketch, u, v) -> (x, y, z)`
- `sketch_normal(sketch) -> (x, y, z)`
- `sketch.apply_resolved_plane(resolved_plane) -> None`
- `sketch.plane_offset` returns the persistent support offset in meters.
- `sketch.set_plane_offset(offset) -> None` updates the support offset without
  baking it into `origin`.

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

The Blender Sketch panel shows dimensions after selecting a Circle, Rectangle,
or Arc (the Sketch row itself has a direct edit button). Numeric edits are
marked dirty until **Apply & Rebuild** or **Finish Sketch** succeeds; repeating
the current dimensions is treated as a no-op and leaves the Sketch clean.
Shift-selecting circles exposes an overall diameter group edit.

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

Every `SketchPlaneReference` also has `offset` (meters). The resolver computes
`resolved_origin = support_origin + support_normal * offset` after resolving
the datum, feature plane, or semantic face. A Transform history feature updates
the downstream datum frame, so offsets follow the transformed support.

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

### `TransformFeature`

```python
from blender_parametric_cad.features.transform import TransformFeature

TransformFeature(
    translation=(0.0, 0.0, 0.0),  # meters
    rotation=(0.0, -0.20943951, 0.0),  # XYZ radians
    dependencies=[previous_body_id],
)
```

`TransformFeature` applies a rigid XYZ Euler transform to the current body. The
same accumulated frame is used by every later datum/semantic Sketch plane and
datum Revolve axis. It requires an earlier body feature and never creates a
second Body.

### `MirrorFeature`

```python
from blender_parametric_cad.features.mirror import MirrorFeature
from blender_parametric_cad.sketch.plane import SketchPlaneReference

MirrorFeature(
    source_feature_id=add_feature.id,
    mirror_plane=SketchPlaneReference("DATUM", datum_plane="YZ", offset=0.0),
    dependencies=[add_feature.id, previous_body_id],
)
```

The supported sources are earlier additive `ExtrudeFeature` or `RevolveFeature`
entries. Extrudes must be positive blind additions. The evaluator regenerates
that source tool, reflects it across the resolved datum/semantic plane, then
performs Boolean Add. The Boolean must remain one connected, manifold,
non-zero-volume solid; disconnected mirrors are rejected.

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
  `.evaluated_features`, `.face_provenance`, `.frame_matrix`

`GeometryBackend` is the replaceable kernel interface:

- `create_extrusion(sketch, profile, distance, direction)`
- `create_extrusion_tool(sketch, profile, body, direction)`
- `create_blind_extrusion_tool(sketch, profile, distance, direction)`
- `revolve_profile(sketch, profile, axis_origin, axis_direction, angle)`
- `register_extrude_provenance(body, feature_id, profile)`
- `face_provenance(body)`
- `boolean_difference(body, tool)`
- `boolean_union(body, tool)`
- `transform_body(body, transform)`
- `mirror_tool(tool, plane_origin, plane_normal)`

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
`deleted_regions`; `plane_reference.offset` stores a support-plane offset in
meters. Entity records use `entity_type` values `LINE`, `CIRCLE`, or `ARC`.
Extrude records contain `sketch_id`, `distance`, `direction`, `operation`, and
`depth_mode`. Revolve records contain `sketch_id`, `axis_reference`, `angle`,
and `operation`. Transform records contain `translation` (meters) and `rotation`
(radians). Mirror records contain `source_feature_id` and a serialized
`mirror_plane` reference. Schema-v1 documents migrate to v2 with
`migrate_document_data`.

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
bpy.ops.parametric_cad.transform()
bpy.ops.parametric_cad.apply_transform()
bpy.ops.parametric_cad.mirror()
bpy.ops.parametric_cad.apply_mirror()
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
ui.new_sketch_offset_mm
ui.sketch_plane_offset_mm
ui.transform_translate_x_mm
ui.transform_translate_y_mm
ui.transform_translate_z_mm
ui.transform_rotate_x_deg
ui.transform_rotate_y_deg
ui.transform_rotate_z_deg
ui.mirror_source_feature_id
ui.mirror_plane_reference   # DATUM|XY/XZ/YZ or FEATURE|<id>|END_PLANE
ui.mirror_plane_offset_mm
```

The Transform and Mirror operators append history features after the current
body; their **Apply** variants edit the selected feature and rebuild. The
Mirror source selector only lists earlier additive Extrudes and Revolves.

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
bpy.ops.parametric_cad.measure()
bpy.ops.parametric_cad.clear_measurement()
```

These are intended for human viewport interaction. Direct AI scripts should
append entities, use the numeric helpers, and construct semantic references
instead of synthesizing mouse events. `track_sketch_cursor` is an internal
cursor tracker and should not be called by model-building scripts. `measure`
is a modal two-point inspection tool and requires a 3D View; it snaps to nearby
mesh vertices or active Sketch endpoints/intersections and reports millimeters
without changing persistent history. The transient UI fields are:

```python
ui.measure_snap_tolerance_px
ui.measure_pending
ui.measure_has_result
ui.measure_point_a          # Blender-world meters, 3-tuple
ui.measure_point_b          # Blender-world meters, 3-tuple
ui.measure_distance_mm
ui.measure_delta_x_mm
ui.measure_delta_y_mm
ui.measure_delta_z_mm
ui.measure_point_a_label
ui.measure_point_b_label
```

## Runtime-only viewport helpers

These functions affect display feedback only and do not modify persistent CAD
data:

- `blender.viewport.sketch_overlay.set_preview`, `clear_preview`
- `set_snap_preview`, `clear_snap_preview`
- `set_face_hover`, `set_face_selection`, `clear_face_selection`
- `set_measurement_pending`, `clear_measurement_pending`,
  `set_measurement_result`, `clear_measurement`
- `tag_redraw`, `start`, `stop`
- `blender.viewport.provenance.set_face_provenance`,
  `get_face_provenance`, `clear_face_provenance`

The provenance registry is rebuilt after each evaluation and must not be used
as a persistent face identity.
