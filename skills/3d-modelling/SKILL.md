---
name: 3d-modelling
description: "Use the Blender Parametric CAD Python API and MCP tools for direct, non-UI 3D modeling from sketches, features, booleans, and per-Part exports."
---

# 3D Modelling

Use this skill when an AI needs to build or edit a model in the Blender 5.1.2
Parametric CAD extension without mouse-driven computer use. Prefer the MCP
tools below when an MCP client is available: the checked-out server starts one
persistent Blender worker automatically and reuses it for the whole session.
When writing a Blender Python script directly, construct the persistent
`CadDocument`/`Part`/`Feature` graph, then call `rebuild_part` once. Use Blender
operators only when an existing UI workflow is specifically required.

The complete callable surface, MCP schemas, field values, units, limitations,
and copyable examples are in
[references/blender_parametric_cad_api.md](references/blender_parametric_cad_api.md).
Read that reference before generating a CAD script. Do not call names starting
with `_`; those are implementation details.

## MCP fast path

Configure an MCP client to run `mcp/server.py` with Python. Set
`BLENDER_CAD_EXECUTABLE` to the Blender 5.1.2 executable and optionally set
`BLENDER_CAD_FILE` to the `.blend` file to open and autosave. The bridge starts
Blender on the first `tools/call`, keeps it alive, and shuts it down only when
the MCP client ends the session; no per-operation start/stop or computer use is
needed. The worker loads the CAD scene properties itself, so enabling the UI
add-on is not required for MCP-only sessions.

MCP tool groups:

- Document: `cad_status`, `cad_create_part`, `cad_set_active_part`,
  `cad_delete_part`, `cad_validate_document`, `cad_save_scene`.
- Sketch: `cad_create_sketch`, `cad_add_geometry`, `cad_update_geometry`,
  `cad_delete_geometry`, `cad_profile`, `cad_delete_region`,
  `cad_restore_region`.
- Features: `cad_create_extrude`, `cad_create_revolve`, `cad_update_feature`,
  `cad_delete_feature`, `cad_suppress_feature`, `cad_rollback`,
  `cad_rebuild`.
- Output: `cad_export_part` (isolated STL, OBJ, or PLY export by `part_id`).

MCP geometry lengths are millimeters and arc/revolve angles are degrees. Every
response includes stable UUIDs and rebuild errors where applicable. The server
also exposes `cad://skill/3d-modelling` and `cad://api-reference` resources.

Important invariants:

- Direct `bpy` bridge functions require the extension to be enabled in Blender;
  the MCP worker registers the scene properties it needs for MCP-only sessions.
- `load_document_from_scene` raises the user-facing `CadDocumentError` when the
  extension is disabled, scene properties are missing, JSON is corrupt, or the
  schema/UUID checks fail.  Do not catch this as a generic Blender traceback;
  report the message and enable/re-enable the extension as directed.
- Core sketch lengths and feature distances are meters; core angles are radians.
  N-panel properties use millimeters and degrees.
- The persistent JSON in `scene.parametric_cad_document` is authoritative;
  generated meshes and Blender polygon indices are disposable.
- A profile must be a valid closed circle, line/arc loop, or composite set of
  bounded loops. Validate with `ProfileDetector.detect` before creating a
  feature.
- Use UUID references (`sketch_id`, `feature_id`, `entity_id`) and include the
  previous body feature in `dependencies` for Add/Remove operations.
- Generated `*_Result` objects are disposable and read-only.  Never edit them in
  Edit Mode; use the CAD history/Sketch entry point.  A failed rebuild keeps the
  last valid result mesh and marks the failed feature `ERROR` and downstream
  features `BLOCKED`.
- Numeric Sketch edits set a dirty flag until `Apply & Rebuild` or `Finish
  Sketch` succeeds.  MCP geometry updates rebuild immediately and return the
  rebuild payload.
- Run `cad_validate_document` (or `validate_cad_document(scene)`) before
  handing a generated model to another agent or exporting it.
- To export one Part Studio, call `export_part(scene, part_id, filepath,
  file_format)`. Supported formats are STL, OBJ, and PLY; the function rebuilds
  and selects only that Part Studio's generated result.
