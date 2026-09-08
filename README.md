# Blender Parametric CAD

AI-first, history-based parametric CAD for Blender 5.1.2.

Version `0.16.12` provides:

- A dependency-free MCP server and a direct Python API.
- Persistent, editable CAD history based on stable UUIDs.
- Sketch, Extrude, Revolve, Transform, Mirror, Chamfer, and Fillet tools.
- Semantic planar and straight-edge references that survive rebuilds.
- Per-Part Studio export to `STL`, `OBJ`, and `PLY`.
- Direct Blender Python execution through `blender_execute_python`.

Generated Blender meshes are disposable outputs. A failed rebuild keeps the last
valid viewport mesh and marks downstream history as `BLOCKED`.

## UI at a glance

- `Model`: Part Studios, feature history, rollback, and feature actions.
- `Sketch`: support selection and sketch editing.
- `Measure`: point-to-point 3D measurements with snapping.
- `Output`: validation and per-Part export.
- Contextual CAD tools are independent left-toolbar buttons; they are not folded
  into Blender's native **Add Cube** group.
- Feature parameters stay beside the matching toolbar icon. The Model panel
  also provides a visible fallback parameter card.
- Sketch Edit shows sketch tools. Feature Edit shows body-feature tools.

## What is supported

- M3.5–M3.6 Part Studio, Sketch, and unified Extrude workflows.
- M4 semantic face selection and Revolve.
- M5 Transform, Sketch-plane offset, and Mirror.
- M6 persistent planar references; see [M6 planar references](M6_PLANAR_REFERENCES.md).
- M7 derived planar references; see [M7 derived planar references](M7_DERIVED_PLANAR_REFERENCES.md).
- M8 persistent straight edges, Chamfer, and Fillet; see [M8 persistent edges](M8_PERSISTENT_EDGES.md).

The persistent JSON CAD history is authoritative. Blender result meshes, Boolean
tools, and sketch overlays are disposable outputs resolved from stable CAD UUIDs.

## Install

Open **Edit → Preferences → Extensions**, use the upper-right menu, choose
**Install from Disk**, and select `blender_parametric_cad-0.16.12.zip`. Enable
**Blender Parametric CAD** if needed.

## M7 derived planar references

Boolean-created planar regions that do not match an existing M6 semantic plane
can now be selected as persistent Sketch supports when their producer-local
plane and optional region hint resolve uniquely. See [M7 derived planar
references](M7_DERIVED_PLANAR_REFERENCES.md) for the matching rules and limits.

## M8 persistent straight edges

M8 adds persistent straight `EdgeReference` objects, screen-space hover/click
edge selection, Shift-click multi-selection, equal-distance Chamfer, and
constant-radius Fillet. Edge references use adjacent semantic planes and
producer-local line signatures; Blender edge indices remain runtime-only.
Missing or ambiguous edges block the dependent feature instead of silently
choosing another edge. Curved edges, tangent chains, and variable-radius
operations remain out of scope. See [M8 persistent edges](M8_PERSISTENT_EDGES.md)
for the identity, resolver, persistence, tolerance, and verification details.

## AI/API skill

M6 development adds persistent planar supports on surviving Boolean surfaces,
Revolve boundary/profile caps, Transform results, and supported Mirror results. See
[M6 planar references](M6_PLANAR_REFERENCES.md) for the reference model,
selection behavior, validation results, and current limitations.

The repository includes the reusable [`3d-modelling` skill](skills/3d-modelling/SKILL.md)
and its complete [Blender Parametric CAD API reference](skills/3d-modelling/references/blender_parametric_cad_api.md)
for Codex/Claude workflows. It documents the callable MCP tools, direct Python
API, stable UUID references, units, and examples for direct, non-UI modeling
from AI-generated instructions or scripts.

## MCP server

The repository includes a dependency-free MCP server for Codex, Claude, and
other MCP clients.

### How it works

- The bridge first discovers an already-running **CAD MCP Service** in Blender.
- If none is available, it starts one persistent, visible Blender 5.1.2 window
  on the first tool call.
- A shared endpoint file and startup lock prevent duplicate fallback workers.
- The service remains available after the stdio MCP process exits.
- Blender timer callbacks keep the UI thread responsive while sketches, features,
  Booleans, rebuilds, and exports run in the same viewport.

### Use an existing Blender window

1. Enable the extension in the Blender window to keep.
2. Open the CAD tab and expand **CAD MCP Service**.
3. Click **Start Service in This Window**.
4. Start or restart the MCP client once.

If the port is already in use, the add-on points to the reachable existing
service instead of silently opening a second Blender window. For an unrelated
process, stop it or choose another port while keeping the endpoint path aligned.

### Configure the MCP client

Use the checked-out server file:

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
        "BLENDER_CAD_FILE": "/absolute/path/to/model.blend",
        "BLENDER_CAD_AUTOSAVE": "/absolute/path/to/model.blend"
      }
    }
  }
}
```

Configuration notes:

- `BLENDER_CAD_FILE` is optional and opens a file at worker startup.
- `BLENDER_CAD_AUTOSAVE` saves every mutating call. If omitted, the worker
  saves to `BLENDER_CAD_FILE`; without either path, use `cad_save_scene`.
- `BLENDER_CAD_PORT` defaults to `9800`.
- `BLENDER_CAD_ENDPOINT_FILE` is optional; the system temporary directory is
  used when it is omitted.
- Set `BLENDER_CAD_AUTOSTART=0` to use only an already-running service.
- Keep the same port and endpoint path in Blender and the MCP client.
- MCP tools use millimeters/degrees. The direct Python API uses its documented
  meter/radian units.
- When an existing service is found, `BLENDER_CAD_FILE` is ignored because the
  open Blender window is the source of truth.
- The built-in service speaks this extension's semantic `cad_*` protocol. A
  third-party Blender MCP add-on may expose a different protocol.

### Blender Preferences warnings

- `Policy violation with top level module: blender_parametric_cad` is a Blender
  extension namespace warning, not an MCP port error.
- After upgrading, restart Blender once or disable/re-enable the extension so
  modules from an older worker are cleared.
- `Address already in use` means the endpoint belongs to an existing service or
  another application. Reuse that service or choose another port.
- Windows from releases before `0.15.0` used private per-client sockets. Close
  those orphan windows once, then install `0.16.12` and use the in-window toggle.

### Headless mode

For CI or machines without a display, pass `--headless` or set
`BLENDER_CAD_HEADLESS=1`. On macOS, headless mode defaults to OpenGL to avoid
some Blender 5.1.2 Metal initialization crashes. Override it with
`--gpu-backend` or `BLENDER_CAD_GPU_BACKEND=opengl|metal|vulkan`.

### Direct Blender Python via MCP

The `blender_execute_python` tool runs trusted single-line or multiline Python
in the same Blender process and on Blender's main thread. Its namespace persists
between calls, so it can be used like Blender's Python Console while returning
captured `stdout`, `stderr`, and the `repr` of a final expression:

```text
blender_execute_python({"code": "import bpy\nbpy.ops.mesh.primitive_cube_add()\nprint(bpy.context.object.name)"})
```

This provides direct `bpy` control without Computer Use. It is full Python
access and can change the scene, files, or Blender process, so only expose it to
a trusted MCP client. Use the semantic `cad_*` tools when persistent Part
Studio history, unit conversion, and CAD validation are desired.

## Part Studio workflow

In a 3D View, press `N` and open the **CAD** tab:

The CAD panel now uses a compact icon rail on its left side. Choose **Model**
for the Part Studio and history tree, **Sketch** for support and sketch
editing, **Measure** for CAD point-to-point measurements, or **Output** for
validation and per-Part export. Feature parameters
are not duplicated in a long N-panel page: the matching native left-toolbar
icon is the single create/edit surface for Extrude, Revolve, Transform, and
Mirror. Its settings popover keeps the current object, Create/Edit state,
common parameters, Rename, Apply & Rebuild/Create, and Cancel together;
parameters are stacked vertically so labels are not truncated. Entering Sketch Edit opens the Sketch workspace automatically;
finishing returns to Model, where the next operation is available without
hunting through another page.

1. Use **+** to create a Part Studio.
2. Create a Sketch on XY, XZ, YZ, or a supported Extrude End Plane.
3. Draw a Rectangle, Circle, Arc, or connected line/arc loop with the mouse.
   Arc uses three clicks: center, start, and end.
   During Sketch Edit, the left Blender toolbar also contains CAD Sketch tools
   for Select, Line, Rectangle, Circle, Arc, Delete Region, and Delete Geometry;
   choose one there to arm the matching viewport action; the first click in the
   3D View is consumed as the first point, so no extra arming click is needed.
   After finishing, the
   same toolbar switches to contextual **Extrude**, **Revolve**, **Transform**,
   **Mirror**, **Chamfer**, and **Fillet** tools for the selected history item;
   the Model buttons remain
   the direct, no-viewport-click entry point.
4. To edit exact dimensions, click the Sketch row's pencil button (or
   double-click a generated result to enter its source history), then select a
   Rectangle, Circle, or Arc. The matching millimeter fields appear
   automatically. Use **Apply & Rebuild** for an immediate result update;
   only an effective geometry/plane change marks the Sketch as pending—repeating
   the same dimensions leaves the result clean;
   individual lines can be removed with **Delete Selected**. Shift-select
   circles to edit their shared diameter. A green cross shows the active snap
   target while drawing.
5. To split a closed boundary, choose **Line** and click two points on its
   boundary. Endpoints snap to nearby vertices/edges/intersections and the
   boundary is split into bounded regions. Choose **Delete Region**, then click
   a region to omit it from subsequent Extrude/Revolve profiles; its unique
   outer contour is hidden in the sketch overlay.
6. Finish the Sketch. **Show Sketches** keeps resolved Sketch references visible.
7. With the finished Sketch selected in **Model**, click **Create Extrude** or
   **Create Revolve**. The matching left-toolbar tool is selected and its
   settings appear beside the icon; the popover identifies the source Sketch,
   exposes one field per row, and provides **Create** and **Cancel** at the
   bottom. Choose **New**, **Add**, or **Remove**, set the extent/axis, and
   press **Create**.
8. Select a body feature in **Model** and click **Create Transform**. Its
   matching toolbar tool exposes translation and rotation in the same place;
   **Apply & Rebuild** updates the history.
9. Select a body feature and click **Create Mirror**, then choose an earlier
   additive Extrude or Revolve and a datum or semantic plane (with optional
   offset). The mirrored tool is unioned with the current body and must remain
   one connected solid.
10. Select straight edges with **Select Edges**. Hold **Shift** to add more
   edges, then press **Enter**. Choose **Chamfer** or **Fillet**, set the
   distance/radius, and press **Create**. Unsupported curved or ambiguous
   edges show an explicit diagnostic and are not reassigned.
11. Select any feature in the Model history and click its matching toolbar
   icon. The toolbar shows the current object, **Edit** state, editable
   parameters, **Name**, **Rename**, **Apply & Rebuild**, and **Cancel** together.
   Model keeps compact inline **Feature Actions**
   for Sketch edit, delete with dependency confirmation, and
   suppress/unsuppress; **Model → History** sets rollback or roll-forward.

For CAD measurements, choose **Measure** in the N-panel or the ruler icon in
the left toolbar. Click two points in the viewport: mesh vertices are preferred
when the cursor is nearby, and Sketch endpoints/intersections are available
while editing a Sketch. The overlay keeps points A/B and the dimension line
visible, while the panel reports true 3D distance and signed **ΔX/ΔY/ΔZ** in
millimeters. Adjust **Snap Tolerance (px)** for the current zoom level, press
**Start CAD Measure** to measure again, and press **Esc** or **Clear Measurement**
when finished. Measurement is display-only and never changes CAD history.

To attach a Sketch to generated geometry, press **Select Face**, click a
supported planar face of an Extrude or Revolve, then press **New Sketch**. The
support is stored as `START_FACE`, `END_FACE`, `SIDE_FACE(source line UUID)`,
`START_CAP`, or `END_CAP`; the temporary Blender polygon hit is never part of
the CAD history. Partial Revolve sweep-boundary caps and full-turn profile-line
disk/annulus caps are supported. A Revolve's conical/cylindrical side is curved
and remains unsupported.

To create or edit a Revolve, select the Sketch or Revolve history item and use
the **Revolve** icon in the left toolbar. Choose a datum X/Y/Z axis or a
visible SketchLine, set **New**, **Add**, or **Remove**, toggle **Reverse Axis**
when the sweep should run in the opposite direction, and enter an angle in
degrees (360° by default).

The Part Studio selector switches between independent single-body histories.
Part Studios can be renamed or deleted without relying on Blender object names.

Each Part Studio can be exported independently from the CAD panel or from
Python with `blender_parametric_cad.blender.adapter.export_part(scene,
part_id, filepath, file_format)`. Supported formats are `STL`, `OBJ`, and
`PLY`; only the requested Part Studio is rebuilt and selected for export.

## Supported profiles and operations

- One Circle, mixed line/arc loop, or multiple closed loops/regions (including
  separate circles combined with line/arc loops).
- Rectangles, triangles, rounded profiles, and simple polygons use the same
  generic profile path.
- A regular Line can split a closed boundary into bounded regions. Deleted
  region IDs are persisted in the Sketch and excluded from feature profiles.
- Sketch intersection markers are highlighted in the active edit view, and
  every drawing tool snaps to nearby intersections, line vertices, circle/arc
  centers and endpoints, and curve interiors. The green preview marker follows
  the active snap target for Rectangle, Circle, Arc, and Line tools alike.
- `New + Blind`, `Add + Blind`, `Remove + Blind`, and
  `Remove + Through All`.
- Existing saved `CUT` features remain compatible and evaluate as Remove.
- Simple Extrude start/end faces, line-based side faces, partial Revolve caps,
  and full-turn Revolve profile-line disk/annulus caps can be selected as
  semantic Sketch supports.
- Face selection supports Extrude START_FACE/END_FACE/SIDE_FACE(source
  SketchLine UUID) and Revolve START_CAP/END_CAP. Curved Revolve sides, arc
  side faces, and arbitrary Boolean-created faces remain visible but report
  that they cannot yet be persistent CAD references.
- Revolve supports New, Add, and Remove with datum axes or SketchLine axes,
  including persistent positive/negative axis direction.
- Full-turn Revolve tools are topologically closed at the seam, and their face
  winding is normalized for reliable Add/Remove Boolean operations even when
  the axis direction is reversed.
- Transform is a persistent rigid history feature. Its translation is stored in
  meters and its XYZ Euler rotation in radians; the UI/MCP expose mm/degrees.
  The same frame is used to resolve all downstream datum and semantic Sketch
  references after a rebuild.
- Sketch supports a parametric plane offset along the resolved support normal;
  changing the upstream face/feature or the offset moves downstream geometry
  without changing local entity coordinates.
- Mirror duplicates one earlier additive Extrude or Revolve tool across a datum
  plane or supported semantic plane and unions it with the current body. A
  disconnected or non-manifold Boolean Add is rejected; multiple Bodies are
  still out of scope.
- The active Part Studio can be exported independently as STL, OBJ, or PLY;
  other Part Studio result objects are never included in that export.

Numeric edits update the existing Sketch entities and preserve entity UUIDs;
repeating the current dimensions is detected as a no-op and does not mark the
Sketch dirty.
Closed loop winding is normalized before mesh generation so clockwise and
counter-clockwise Rectangles, arcs, and simple polygons use the same Add/Remove
path. Multiple active loops are emitted as one composite tool.
Feature-derived Sketch overlays are resolved from history, so they move with
semantic `END_PLANE` references after rebuilds.

Generated `*_Result` meshes are disposable and read-only. The CAD panel warns
when one is active and provides **Edit CAD History**; double-clicking the result
opens its source Sketch/Feature. A rebuild is atomic from the viewport's point
of view: a failed Feature leaves the previous valid mesh in place, records the
specific error, and marks downstream Features `BLOCKED`.

Use **Validate CAD Document** (or `validate_cad_document(scene)` / MCP
`cad_validate_document`) for a read-only check of UUID dependencies, Sketch
profiles, Transform/Mirror references, disconnected generated results, failed
history entries, and empty generated results. When the
extension is not enabled or the scene JSON/schema is damaged, the panel shows
an actionable error instead of raising an AttributeError.

## Persistence and schema

CAD data remains schema-v2 JSON in the Blender Scene. Stable UUIDs encode Part
Studio identity, Feature dependencies, source Sketches, and semantic planes; no
Blender face, polygon, mesh-element index, or object name is authoritative.
Schema-v1 datum sketches and extrusions still migrate automatically on load.

## Tests

From the directory containing this package:

```bash
python3 -m unittest discover -s blender_parametric_cad/tests -t . -v
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --factory-startup \
  --python blender_parametric_cad/tests/blender_headless_validation.py
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --factory-startup \
  --python blender_parametric_cad/tests/blender_headless_m35_validation.py
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --factory-startup \
  --python blender_parametric_cad/tests/blender_headless_m36_validation.py
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --factory-startup \
  --python blender_parametric_cad/tests/blender_headless_m4_validation.py
```

The Blender validations cover the legacy M3 model, independent Part Studios,
Feature lifecycle controls, numeric Sketch editing, persistent semantic overlays,
generic Remove profiles, Add, blind pocket depth, semantic END/SIDE face
supports, datum and SketchLine Revolve axes, Revolve Add/Remove, and save/reopen
editing. The pure-Python suite additionally covers the M5 single-body history
sequence, Transform frame/edit rebuilds, Sketch offsets, six-line guides,
Mirror source UUIDs, mirrored Add failure atomicity, and multi-circle Through All
Remove. Per the extension workflow, Blender UI/headless validation is optional;
the source-level suite does not launch Blender.
