# Blender Parametric CAD

An AI-first, history-based parametric CAD extension for Blender 5.1.2, designed
for Codex, Claude, and other tool-using AI systems. Version 0.13.1 provides a
real MCP interface and a Python API so an AI can create sketches, features,
booleans, transforms, mirrors, and per-Part exports through normal CAD
operations—not by spending tokens on mouse clicks or computer-use screenshots.

The resulting model is still a native, editable Blender workflow: every AI
operation is stored as persistent CAD history, and the same Sketches, feature
parameters, dimensions, references, and generated result can be inspected and
modified directly in Blender. This makes human–AI co-design practical: the AI
can handle precise, repeatable construction while a person reviews, adjusts,
or continues the design interactively, reducing both the token cost and the
technical barrier of 3D modeling.

The extension implements the M3.5–M3.6 Part Studio, precise Sketch and unified
Extrude workflows, the M4 semantic face-selection/Revolve milestone, and M5
parametric Transform, Sketch-plane offset, and Mirror features. Arc-based
composite sketch regions, interactive sketch cleanup/snapping, and robust
Boolean connectivity checks remain enabled.

The persistent JSON CAD history is authoritative. Blender result meshes,
Boolean tools, and sketch overlays are disposable outputs resolved from stable
CAD UUIDs.

## Install

Open **Edit → Preferences → Extensions**, use the upper-right menu, choose
**Install from Disk**, and select `blender_parametric_cad-0.13.1.zip`. Enable
**Blender Parametric CAD** if needed.

## AI/API skill

The repository includes the reusable [`3d-modelling` skill](skills/3d-modelling/SKILL.md)
and its complete [Blender Parametric CAD API reference](skills/3d-modelling/references/blender_parametric_cad_api.md)
for Codex/Claude workflows. It documents the callable MCP tools, direct Python
API, stable UUID references, units, and examples for direct, non-UI modeling
from AI-generated instructions or scripts.

## MCP server

The repository includes a dependency-free MCP server for Codex, Claude, and
other MCP clients. By default it starts one persistent, **visible Blender 5.1.2
window** on the first tool call and keeps that same window open after the MCP
client disconnects. Requests are serviced through Blender's timer API instead
of blocking Blender's UI thread, so each sketch, feature, Boolean, rebuild, and
export is reflected in the open viewport as the AI works. The AI therefore
calls semantic CAD actions in one normal modeling session instead of repeatedly
starting Blender, driving the UI, or describing screenshots. This substantially
reduces token consumption while preserving a complete, inspectable feature
history that a person can continue editing in the same Blender window. Visible
mode uses Blender's normal startup/preferences, so an enabled CAD extension and
your usual workspace are available; `BLENDER_CAD_FILE` can then open a specific
model into that window.

If a machine has no display, or if a CI job needs a background worker, pass
`--headless` or set `BLENDER_CAD_HEADLESS=1`. On macOS, headless mode selects
the OpenGL backend by default to avoid Blender 5.1.2 Metal initialization
crashes observed on some systems. Override this with `--gpu-backend` or
`BLENDER_CAD_GPU_BACKEND=opengl|metal|vulkan` when needed. A visible session
can also use `BLENDER_CAD_GPU_BACKEND=opengl` if the normal Metal backend is
unstable.

Configure the MCP client with the checked-out server file:

```json
{
  "mcpServers": {
    "blender-parametric-cad": {
      "command": "python3",
      "args": ["/absolute/path/to/blender_parametric_cad/mcp/server.py"],
      "env": {
        "BLENDER_CAD_EXECUTABLE": "/Applications/Blender.app/Contents/MacOS/Blender",
        "BLENDER_CAD_FILE": "/absolute/path/to/model.blend",
        "BLENDER_CAD_AUTOSAVE": "/absolute/path/to/model.blend"
      }
    }
  }
}
```

`BLENDER_CAD_FILE` is optional. When set, the worker opens that file at startup;
`BLENDER_CAD_AUTOSAVE` makes every mutating call save it (when omitted, the
worker autosaves to `BLENDER_CAD_FILE`). Otherwise use the `cad_save_scene`
tool. The MCP tools use millimeters and degrees for human-friendly inputs,
while the direct Python API keeps its documented meter/radian units. Tool
discovery also exposes the skill and API reference as MCP resources. Because
the visible worker is the same live Blender session, there is no separate
AI-only copy to reopen: the person can inspect or edit the CAD history while
the MCP session is running, and later calls rebuild from that shared document.
Enable the extension in Blender Preferences to show its CAD panel and
interactive sketch tools in the visible worker window.

## Part Studio workflow

In a 3D View, press `N` and open the **CAD** tab:

1. Use **+** to create a Part Studio.
2. Create a Sketch on XY, XZ, YZ, or a supported Extrude End Plane.
3. Draw a Rectangle, Circle, Arc, or connected line/arc loop with the mouse.
   Arc uses three clicks: center, start, and end.
4. To edit exact dimensions, click the Sketch row's pencil button (or
   double-click a generated result to enter its source history), then select a
   Rectangle, Circle, or Arc. The matching millimeter fields appear
   automatically. Use **Apply & Rebuild** for an immediate result update;
   individual lines can be removed with **Delete Selected**. Shift-select
   circles to edit their shared diameter. A green cross shows the active snap
   target while drawing.
5. To split a closed boundary, choose **Line** and click two points on its
   boundary. Endpoints snap to nearby vertices/edges/intersections and the
   boundary is split into bounded regions. Choose **Delete Region**, then click
   a region to omit it from subsequent Extrude/Revolve profiles; its unique
   outer contour is hidden in the sketch overlay.
6. Finish the Sketch. **Show Sketches** keeps resolved Sketch references visible.
7. Select the Sketch and use one **Extrude** command with **New**, **Add**, or
   **Remove**, plus **Blind** or **Through All** where supported.
8. Add a **Transform** after the current body to enter translation in mm and
   rotation in degrees. Downstream datum/semantic Sketch planes follow its
   transformed coordinate frame.
9. Add a **Mirror**, choose an earlier additive Extrude or Revolve and a datum
   or semantic plane (with optional offset). The mirrored tool is unioned with
   the current body and must remain one connected solid.
10. Select Features to edit, rename, delete with dependency confirmation,
   suppress/unsuppress, or set the rollback point.

To attach a Sketch to generated geometry, press **Select Face**, click a
supported planar face of a simple New Extrude, then press **New Sketch**. The
support is stored as `START_FACE`, `END_FACE`, or `SIDE_FACE(source line UUID)`;
the temporary Blender polygon hit is never part of the CAD history.

To create a Revolve, select a Sketch and use its **Revolve** section. Choose a
datum X/Y/Z axis or a visible SketchLine, set **New**, **Add**, or **Remove**,
toggle **Reverse Axis** when the sweep should run in the opposite direction,
and enter an angle in degrees (360° by default).

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
- Simple Extrude start/end faces and line-based side faces can be selected as
  semantic Sketch supports.
- Face selection is intentionally limited to the generated mesh of a simple
  **New Extrude**: START_FACE, END_FACE, and SIDE_FACE(source SketchLine UUID).
  Boolean and Revolve result faces, plus arc-based side faces, remain visible
  but report that they cannot yet be persistent CAD references.
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

Numeric edits update the existing Sketch entities and preserve entity UUIDs.
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
