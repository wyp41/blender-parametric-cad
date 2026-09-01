# Blender Parametric CAD

History-based parametric modeling extension for Blender 5.1.2. Version 0.4.0
implements the M3.5–M3.6 Part Studio, precise Sketch and unified Extrude
workflows, plus the M4 semantic face-selection and Revolve milestone.

The persistent JSON CAD history is authoritative. Blender result meshes,
Boolean tools, and sketch overlays are disposable outputs resolved from stable
CAD UUIDs.

## Install

Open **Edit → Preferences → Extensions**, use the upper-right menu, choose
**Install from Disk**, and select `blender_parametric_cad-0.4.0.zip`. Enable
**Blender Parametric CAD** if needed.

## Part Studio workflow

In a 3D View, press `N` and open the **CAD** tab:

1. Use **+** to create a Part Studio.
2. Create a Sketch on XY, XZ, YZ, or a supported Extrude End Plane.
3. Draw a Rectangle, Circle, or connected line loop with the mouse.
4. To edit exact dimensions, use **Select**, click a Rectangle or Circle, then
   update its millimeter fields. The selected shape is highlighted.
5. Finish the Sketch. **Show Sketches** keeps resolved Sketch references visible.
6. Select the Sketch and use one **Extrude** command with **New**, **Add**, or
   **Remove**, plus **Blind** or **Through All** where supported.
7. Select Features to edit, rename, delete with dependency confirmation,
   suppress/unsuppress, or set the rollback point.

To attach a Sketch to generated geometry, press **Select Face**, click a
supported planar face of a simple New Extrude, then press **New Sketch**. The
support is stored as `START_FACE`, `END_FACE`, or `SIDE_FACE(source line UUID)`;
the temporary Blender polygon hit is never part of the CAD history.

To create a Revolve, select a Sketch and use its **Revolve** section. Choose a
datum X/Y/Z axis or a visible SketchLine, set **New**, **Add**, or **Remove**,
and enter an angle in degrees (360° by default).

The Part Studio selector switches between independent single-body histories.
Part Studios can be renamed or deleted without relying on Blender object names.

## Supported profiles and operations

- One Circle or one simple connected closed line loop.
- Rectangles, triangles, and simple polygons use the same generic profile path.
- `New + Blind`, `Add + Blind`, `Remove + Blind`, and
  `Remove + Through All`.
- Existing saved `CUT` features remain compatible and evaluate as Remove.
- Simple Extrude start/end faces and line-based side faces can be selected as
  semantic Sketch supports.
- Revolve supports New, Add, and Remove with datum axes or SketchLine axes.

Numeric edits update the existing Sketch entities and preserve entity UUIDs.
Closed line-loop winding is normalized before mesh generation so clockwise and
counter-clockwise Rectangles and simple polygons use the same Add/Remove path.
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
