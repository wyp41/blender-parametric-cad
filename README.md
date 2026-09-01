# Blender Parametric CAD

History-based parametric modeling extension for Blender 5.1.2. Version 0.6.0
implements the M3.5–M3.6 Part Studio, precise Sketch and unified Extrude
workflows, the M4 semantic face-selection/Revolve milestone, arc-based
composite sketch regions, and interactive sketch cleanup/snapping.

The persistent JSON CAD history is authoritative. Blender result meshes,
Boolean tools, and sketch overlays are disposable outputs resolved from stable
CAD UUIDs.

## Install

Open **Edit → Preferences → Extensions**, use the upper-right menu, choose
**Install from Disk**, and select `blender_parametric_cad-0.6.0.zip`. Enable
**Blender Parametric CAD** if needed.

## Part Studio workflow

In a 3D View, press `N` and open the **CAD** tab:

1. Use **+** to create a Part Studio.
2. Create a Sketch on XY, XZ, YZ, or a supported Extrude End Plane.
3. Draw a Rectangle, Circle, Arc, or connected line/arc loop with the mouse.
   Arc uses three clicks: center, start, and end.
4. To edit exact dimensions, use **Select**, click a Rectangle, Circle, or Arc,
   then update its millimeter fields. Individual lines can also be selected and
   highlighted; use **Delete Geometry** to remove one entity.
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

## Supported profiles and operations

- One Circle, mixed line/arc loop, or multiple closed loops/regions (including
  separate circles combined with line/arc loops).
- Rectangles, triangles, rounded profiles, and simple polygons use the same
  generic profile path.
- A regular Line can split a closed boundary into bounded regions. Deleted
  region IDs are persisted in the Sketch and excluded from feature profiles.
- Sketch intersection markers are highlighted in the active edit view, and
  drawing tools snap to nearby intersections, vertices, and curve interiors.
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
