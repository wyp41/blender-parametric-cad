# Blender Parametric CAD

Parametric CAD extension for Blender 5.1.2.

Create editable Part Studio models and linked Assemblies with sketches, feature
history, semantic references, MCP, and Python.


## Watch the mechanisms

14 mechanism examples built with the plugin: gears, planetary trains, linkages,
and cam followers. Play the 36-second showcase directly below.

https://github.com/user-attachments/assets/f0776b6b-0ca6-455e-9513-564a8cb349cb

[Models, STL files, formulas, and reproducible scripts](examples/mechanisms/README.md)


## Features

### Modeling

- Part Studio with single-body parametric history.
- Flat Assemblies with linked Part instances and independent numeric placements.
- Involute spur, internal-cutout, and straight-rack profile helpers for printed
  teaching mechanisms (`sketch.gears`; lengths in meters).
- Prescribed planar Assembly animation with native persistent Blender drivers
  (`blender.motion`); this is not an assembly joint or contact solver.
- Part Studio and Assembly Scenes in separate windows of one Blender process.
- Sketches on datum planes, Extrude faces, Revolve caps, Transform faces, and
  supported Mirror faces.
- Semantic rectangles backed by four editable SketchLines, stable rectangle and
  line UUIDs, and width/height dimensions.
- Circle, Line, Arc, mixed loops, multiple regions, and region deletion.
- Numeric Sketch editing with millimeter dimensions and UUID preservation.
- Sketch constraints: Horizontal, Vertical, Coincident, Parallel,
  Perpendicular, and Equal.
- Lightweight transactional Sketch solver for dimensions and constraints.
- Extrude: `New`, `Add`, `Remove`, Blind, and Through All.
- Revolve: `New`, `Add`, `Remove`, datum axes, SketchLine axes, angle, and
  reverse direction.
- Transform: translation, rotation, and Sketch-plane offset.
- Mirror across datum or supported semantic planes.
- Chamfer with equal distance.
- Fillet with constant radius.

### Persistent references

- Planar face references for Extrude, Revolve, Boolean, Transform, and Mirror
  results.
- Straight edge references for Chamfer and Fillet.
- Face and edge references survive rebuild, save, and reopen.
- Blender polygon and edge indices are runtime-only.
- Missing or ambiguous references block the dependent feature instead of
  selecting another face or edge.

### Blender UI

- `Model`: Part Studios, feature history, edit, delete, suppress, and rollback.
- `Sketch`: support selection and sketch editing.
- `Measure`: point-to-point 3D measurement with snapping.
- `Output`: document validation and Part Studio export.
- CAD tools are separate left-toolbar buttons for each window’s editing stage; they are not
  folded into Blender's **Add Cube** group.
- Hover and click selection for planar faces and straight edges.
- Shift-click multi-edge selection.
- Sketch endpoint/center selection with hover highlighting and constraint markers.
- Feature parameters stay beside the selected toolbar tool.
- Sketch Edit and Feature Edit show their relevant tools only.

### Measurement and export

- True 3D distance in millimeters.
- Signed `ΔX`, `ΔY`, and `ΔZ` components.
- Vertex, Sketch endpoint, intersection, and curve snapping.
- Independent Part Studio export to `STL`, `OBJ`, and `PLY`.
- STL coordinates are exported in millimeters for slicers; OBJ/PLY retain meters.

### MCP and Python

- Semantic MCP tools for sketches, features, rebuilds, validation, and export.
- MCP Sketch authoring for lines, circles, rectangles, dimensions, and basic
  constraints, rectangle updates, and document/feature inspection by UUID.
- MCP reference listing and generated-geometry inspection (components, bounds,
  manifold status, and volume).
- MCP mutations return stable IDs, solver/rebuild status, and structured error
  codes; failed Sketch mutations are rolled back.
- `blender_execute_python` for trusted Python in the connected Blender process.
- Direct Python API for automation and per-Part export.
- Blender UI and MCP can edit the same CAD history.

## Install

1. Open **Edit → Preferences → Extensions** in Blender.
2. Open the upper-right menu and choose **Install from Disk**.
3. Select `blender_parametric_cad-0.18.1.zip`.
4. Enable **Blender Parametric CAD**.

## Quick start

1. Open the 3D View sidebar with `N`, then select the **CAD** tab.
2. In **Model**, click **+** to create a Part Studio.
3. Create a Sketch on `XY`, `XZ`, `YZ`, or a supported generated face.
4. Draw a closed profile and finish the Sketch.
5. Create an Extrude or Revolve from the Model panel or left toolbar.
6. Select a feature to edit, Transform, Mirror, Chamfer, or Fillet it.
7. Save the `.blend` file. CAD history and semantic references are restored on
   reopen.

## Linked Assemblies

Click **Open Assembly Window** in the CAD panel. Create an Assembly, then use
**Add Part** to place an existing Part Studio multiple times. **Transform** edits
translation in millimeters and XYZ rotation in degrees. **Edit Source Part**
activates the original Part in the existing Part Studio window; editing its
Sketch or features updates all linked instances automatically.

The `.blend` file stores one schema-v3 CAD document in `CAD_DOCUMENT.json`.
Legacy Scene JSON is migrated without changing UUIDs. Conflicting legacy Scene
documents produce `MIGRATION_CONFLICT` instead of selecting one silently.
Referenced Part deletion produces `PART_IN_USE`; remove its instances first.

See [the M11A implementation and validation report](M11A_LINKED_ASSEMBLIES.md).

## Mechanical course examples

The [mechanism gallery](examples/mechanisms/README.md) extends the original
20/40-tooth gear document into 14 prescribed-motion examples, with 25 shared
printable Parts, validated STL dimensions, previews, and a video showcase.
The gallery also records the limits of the checks; these are low-load teaching
prototypes rather than load-rated, print-tested machines.

## MCP setup

Enable the extension, open **CAD MCP Service** in the CAD panel, and click
**Start Service in This Window**. Then configure the MCP client with:

```json
{
  "mcpServers": {
    "blender-parametric-cad": {
      "command": "python3",
      "args": ["/absolute/path/to/blender_parametric_cad/mcp/server.py"],
      "env": {
        "BLENDER_CAD_PORT": "9800",
        "BLENDER_CAD_AUTOSTART": "1"
      }
    }
  }
}
```

Use `BLENDER_CAD_AUTOSTART=0` when the MCP client must only connect to an
already-running Blender service.

MCP inputs use millimeters and degrees. The direct Python API uses its documented
meter and radian units.

Common AI workflow:

```text
cad_create_part
→ cad_create_sketch
→ cad_sketch_add_rectangle
→ cad_sketch_add_constraint / cad_sketch_add_dimension
→ cad_create_extrude
→ cad_get_sketch / cad_get_history
```

See [the MCP API reference](skills/3d-modelling/references/blender_parametric_cad_api.md)
for schemas, units, return values, and a complete plate example.

## Python examples

Run trusted Python in Blender through MCP:

```text
blender_execute_python({"code": "import bpy\nbpy.ops.mesh.primitive_cube_add()"})
```

Export one Part Studio:

```python
blender_parametric_cad.blender.adapter.export_part(
    scene, part_id, filepath, file_format
)
```

Supported formats: `STL`, `OBJ`, and `PLY`.

## History behavior

- Sketch and feature edits rebuild the history from upstream parameters.
- Delete, suppress, unsuppress, rollback, and roll-forward are supported.
- A failed rebuild keeps the last valid viewport mesh.
- Downstream features are marked `BLOCKED` with a diagnostic.
- Generated `*_Result` meshes are disposable outputs, not CAD references.

## Current limitations

- Curved faces cannot yet be used as persistent Sketch references.
- Curved edges, tangent chains, variable-radius Fillets, and asymmetric
  Chamfers are not supported.
- Multiple Bodies and full general topological naming are not implemented.
- M9C does not include DOF analysis or advanced constraints such as Tangent,
  Symmetric, Midpoint, Concentric, or Fix.
