# User guide

[Home](../README.md) · English | [简体中文](guide.zh-CN.md)

## Install and open

Use Blender **5.1.2**, the version used for validation. Download the extension ZIP
from the [0.18.1 release](https://github.com/wyp41/blender-parametric-cad/releases/tag/v0.18.1).
In **Edit → Preferences → Extensions**, open the menu, choose **Install from Disk**,
select the ZIP, and enable **Blender Parametric CAD**. Open the 3D View sidebar
with `N`, then choose **CAD**.

## Manual modeling

1. In **Model**, create a Part Studio with **+**.
2. Create a Sketch on `XY`, `XZ`, `YZ`, or a supported persistent planar face.
3. Use the contextual CAD toolbar to draw a closed profile. Lines, circles,
   arcs, mixed boundaries, multiple regions, and region deletion are supported.
4. Add numeric dimensions or the basic constraints below, then finish the Sketch.
5. Use **Create Extrude** or **Create Revolve**. Extrude supports `New`, `Add`,
   `Remove`, `Blind`, and `Through All`; Revolve accepts a datum or SketchLine axis.
6. Select a history item to edit it. Use **Apply & Rebuild** to update the result.
   Transform, Mirror, equal-distance Chamfer, and constant-radius Fillet are
   available for their supported inputs.
7. Save the `.blend` file. Reopening restores the CAD history and references.

**Model** owns the history tree, rollback/roll-forward, suppression and feature
actions. **Sketch** manages supports and editing. **Measure** inspects geometry;
**Output** validates and exports. Contextual native toolbar icons expose drawing,
selection and feature parameters; Model also provides the parameter card when
the toolbar popover is unavailable. The first drawing click is the first point.

| Capability | Supported scope |
| --- | --- |
| Dimensions | Length, horizontal/vertical distance, distance, radius, diameter |
| Constraints | Horizontal, Vertical, Coincident, Parallel, Perpendicular, Equal |
| Rectangles | Four editable SketchLines plus semantic width/height metadata |
| Sketch supports | Datum planes and supported semantic/derived planar references |
| Edge features | Persistent straight edges; Shift-click for multiple edges |
| History | Edit, delete, suppress, rollback, roll forward, rebuild |

An invalid feature keeps the last valid display mesh. The failing feature is
`ERROR`; affected downstream features are `BLOCKED`. Fix the upstream history
instead of editing the generated `*_Result` mesh in Blender Edit Mode.

## Linked Assemblies

Choose **Open Assembly Window**, create an Assembly, and **Add Part** to reuse a
Part Studio. Instances share the source geometry and have independent names,
placements and suppression. **Transform** edits millimeters and XYZ degrees;
**Edit Source Part** opens the existing source workspace. Rebuilding that source
updates all linked instances while preserving their placements and motion.

A referenced Part cannot be deleted: `PART_IN_USE` lists the referencing
Assemblies/instances. Remove those instances first. Assemblies are flat instance
lists; mates, general joints, nested Assemblies and a contact solver are not
implemented. The [mechanism gallery](../examples/mechanisms/README.md) uses native
Blender drivers for prescribed planar motion.

## Measure and export

The **Measure** ruler picks two viewport points and reports true 3D distance,
`ΔX/ΔY/ΔZ` and coordinates in millimeters. It snaps to nearby mesh vertices and
active Sketch endpoints/intersections using a screen-pixel tolerance. Press
`Esc` to leave the tool, or clear the result. It does not create a CAD Feature.

Validate in **Output**, then export each Part Studio separately:

| Output/API | Length | Angle |
| --- | --- | --- |
| UI and semantic MCP tools | Millimeters | Degrees |
| Direct Python geometry API | Meters | Radians |
| STL files, since 0.18.1 | Millimeters; no extra ×1000 scaling | — |
| OBJ / PLY files | Core meter coordinates | — |

STL export ignores Scene display-unit scaling. Check the expected bounds in the
slicer; changing the Scene unit label does not repair an old, wrongly scaled file.

## Connect an AI client with MCP

The extension supplies its own semantic CAD service. A generic third-party
Blender MCP add-on does not automatically provide these tools.

To bind a particular open Blender window, expand **CAD MCP Service** in the CAD
panel and click **Start Service in This Window**. Configure the client below and
start/restart it. Replace the absolute path with your checkout path.

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

A reachable service is reused. If none exists, autostart creates one visible
Blender worker. Use `BLENDER_CAD_AUTOSTART=0` for an existing-window-only session.
The endpoint lock prevents duplicate fallback workers. An unresponsive live
worker is reported rather than bypassed with another window.

| Setting | Purpose |
| --- | --- |
| `BLENDER_CAD_EXECUTABLE` | Blender executable, optional if on `PATH` |
| `BLENDER_CAD_FILE` | Optional startup file; ignored when reusing a live service |
| `BLENDER_CAD_AUTOSAVE` | Optional separate autosave target |
| `BLENDER_CAD_ENDPOINT_FILE` | Shared endpoint JSON; defaults to system temporary directory |
| `BLENDER_CAD_PORT` | Match the Blender service; default 9800 |
| `BLENDER_CAD_HEADLESS=1` | Background worker for CI/headless use |
| `BLENDER_CAD_GPU_BACKEND` | Explicit backend override supported by the local Blender build |

The macOS headless launcher currently defaults to OpenGL. The tested local
Blender build accepts only Metal, so its headless checks use
`BLENDER_CAD_GPU_BACKEND=metal`. Choose a backend your build actually provides.
After upgrading from an old worker, restart Blender to clear stale imported
modules; a Preferences top-level-module warning is separate from port ownership.

Use returned UUIDs rather than Blender object names or mesh indices. A typical
semantic flow is `cad_create_part` → `cad_create_sketch` →
`cad_sketch_add_rectangle` → `cad_create_extrude` → `cad_get_history` →
`cad_export_part`. Geometry mutations solve/rebuild and roll back on failure.

For trusted arbitrary Python, `blender_execute_python` runs on Blender's main
thread with a persistent namespace and returns stdout, stderr and the final
expression. It has full Python/`bpy` access. Prefer semantic `cad_*` calls for CAD
history and unit-aware validation. See the [complete API reference](../skills/3d-modelling/references/blender_parametric_cad_api.md)
for signatures, fields and executable examples.

## Limits and next steps

Supported planar/straight references survive supported edits and reloads;
missing or ambiguous references block downstream work instead of guessing.
Curved-face supports, curved/tangent-chain edge references, variable-radius
Fillets, asymmetric Chamfers, multiple bodies, general topological naming and
STEP export are not implemented. Advanced Sketch constraints such as Tangent,
Symmetric, Midpoint, Concentric and Fix, and general DOF analysis, are absent.

For practical examples use the [mechanism gallery](../examples/mechanisms/README.md).
For data ownership, reference matching and regression evidence see
[Architecture and validation](development.md). Physical printability and loads
still require real tests; the gallery records its specific checks and limits.
