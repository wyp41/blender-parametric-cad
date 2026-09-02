---
name: 3d-modelling
description: "Use the Blender Parametric CAD Python API for direct, non-UI 3D modeling from sketches, features, booleans, and per-Part exports."
---

# 3D Modelling

Use this skill when an AI needs to build or edit a model in the Blender 5.1.2
Parametric CAD extension without mouse-driven computer use. Prefer constructing
the persistent `CadDocument`/`Part`/`Feature` graph directly, then call
`rebuild_part` once. Use Blender operators only when an existing UI workflow is
specifically required.

The complete callable surface, field values, schema, units, limitations, and
copyable examples are in [references/blender_parametric_cad_api.md](references/blender_parametric_cad_api.md).
Read that reference before generating a CAD script. Do not call names starting
with `_`; those are implementation details.

Important invariants:

- The extension must be enabled in Blender before using `bpy` bridge functions.
- Core sketch lengths and feature distances are meters; core angles are radians.
  N-panel properties use millimeters and degrees.
- The persistent JSON in `scene.parametric_cad_document` is authoritative;
  generated meshes and Blender polygon indices are disposable.
- A profile must be a valid closed circle, line/arc loop, or composite set of
  bounded loops. Validate with `ProfileDetector.detect` before creating a
  feature.
- Use UUID references (`sketch_id`, `feature_id`, `entity_id`) and include the
  previous body feature in `dependencies` for Add/Remove operations.
- To export one Part Studio, call `export_part(scene, part_id, filepath,
  file_format)`. Supported formats are STL, OBJ, and PLY; the function rebuilds
  and selects only that Part Studio's generated result.
