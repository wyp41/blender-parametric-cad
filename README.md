# Blender Parametric CAD

History-based parametric modeling extension for Blender 5.1.2. Version 0.10.0
implements the M3.5–M3.6 Part Studio, precise Sketch and unified Extrude
workflows, the M4 semantic face-selection/Revolve milestone, arc-based
composite sketch regions, interactive sketch cleanup/snapping, and robust
Revolve Boolean tools.

The persistent JSON CAD history is authoritative. Blender result meshes,
Boolean tools, and sketch overlays are disposable outputs resolved from stable
CAD UUIDs.

## Install

Open **Edit → Preferences → Extensions**, use the upper-right menu, choose
**Install from Disk**, and select `blender_parametric_cad-0.10.0.zip`. Enable
**Blender Parametric CAD** if needed.

## AI/API skill

The repository includes the reusable [`3d-modelling` skill](skills/3d-modelling/SKILL.md)
and its complete [Blender Parametric CAD API reference](skills/3d-modelling/references/blender_parametric_cad_api.md)
for direct, non-UI modeling from AI-generated Python scripts.

## MCP server

The repository also includes a dependency-free MCP server. It starts one
persistent Blender 5.1.2 background worker on the first tool call, keeps it
alive for the MCP session, and closes it when the client disconnects. This
avoids starting/stopping Blender for every modeling operation and does not
require mouse-driven computer use.

Configure the MCP client with the checked-out server file:

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

`BLENDER_CAD_FILE` is optional. When set, the worker opens that file and
autosaves mutations to it; otherwise use the `cad_save_scene` tool. The MCP
tools use millimeters and degrees for human-friendly inputs, while the direct
Python API keeps its documented meter/radian units. Tool discovery also
exposes the skill and API reference as MCP resources.

## Part Studio workflow

In a 3D View, press `N` and open the **CAD** tab:

1. Use **+** to create a Part Studio.
2. Create a Sketch on XY, XZ, YZ, or a supported Extrude End Plane.
3. Draw a Rectangle, Circle, Arc, or connected line/arc loop with the mouse.
   Arc uses three clicks: center, start, and end.
4. To edit exact dimensions, use **Select**, click a Rectangle, Circle, or Arc,
   then update its millimeter fields. Individual lines can also be selected and
   highlighted; use **Delete Selected** (or the click-based **Delete Geometry**)
   to remove one entity. A green cross shows the active snap target while
   drawing.
5. To split a closed boundary, choose **Line** and click two points on its
   boundary. Endpoints snap to nearby vertices/edges/intersections and the
   boundary is split into bounded regions. Choose **Delete Region**, then click
   a region to omit it from subsequent Extrude/Revolve profiles; its unique
   outer contour is hidden in the sketch overlay.
6. Finish the Sketch. **Show Sketches** keeps resolved Sketch references visible.
7. Select the Sketch and use one **Extrude** command with **New**, **Add**, or
   **Remove**, plus **Blind** or **Through All** where supported.
8. Select Features to edit, rename, delete with dependency confirmation,
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
- The active Part Studio can be exported independently as STL, OBJ, or PLY;
  other Part Studio result objects are never included in that export.

Numeric edits update the existing Sketch entities and preserve entity UUIDs.
Closed loop winding is normalized before mesh generation so clockwise and
counter-clockwise Rectangles, arcs, and simple polygons use the same Add/Remove
path. Multiple active loops are emitted as one composite tool.
Feature-derived Sketch overlays are resolved from history, so they move with
semantic `END_PLANE` references after rebuilds.

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
editing.
