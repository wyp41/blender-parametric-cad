# Blender Parametric CAD

History-based parametric modeling extension for Blender 5.1.2. Version 0.3.0
implements the M3.5–M3.6 Part Studio, Feature management, precise Sketch, and
unified Extrude workflows.

The persistent JSON CAD history is authoritative. Blender result meshes,
Boolean tools, and sketch overlays are disposable outputs resolved from stable
CAD UUIDs.

## Install

Open **Edit → Preferences → Extensions**, use the upper-right menu, choose
**Install from Disk**, and select `blender_parametric_cad-0.3.0.zip`. Enable
**Blender Parametric CAD** if needed.

## Part Studio workflow

In a 3D View, press `N` and open the **CAD** tab:

1. Use **+** to create a Part Studio.
2. Create a Sketch on XY, XZ, YZ, or a supported Extrude End Plane.
3. Draw with the mouse or enter an exact Rectangle (`X`, `Y`, `Width`,
   `Height`) or Circle (`Center X`, `Center Y`, `Diameter`) in millimeters.
4. Finish the Sketch. **Show Sketches** keeps resolved Sketch references visible.
5. Select the Sketch and use one **Extrude** command with **New**, **Add**, or
   **Remove**, plus **Blind** or **Through All** where supported.
6. Select Features to edit, rename, delete with dependency confirmation,
   suppress/unsuppress, or set the rollback point.

The Part Studio selector switches between independent single-body histories.
Part Studios can be renamed or deleted without relying on Blender object names.

## Supported profiles and operations

- One Circle or one simple connected closed line loop.
- Rectangles, triangles, and simple polygons use the same generic profile path.
- `New + Blind`, `Add + Blind`, `Remove + Blind`, and
  `Remove + Through All`.
- Existing saved `CUT` features remain compatible and evaluate as Remove.

Numeric edits update the existing Sketch entities and preserve entity UUIDs.
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
```

The Blender validations cover the legacy M3 model, independent Part Studios,
Feature lifecycle controls, numeric Sketch editing, persistent semantic overlays,
generic Remove profiles, Add, blind pocket depth, repeated deletion, and
save/reopen editing.
