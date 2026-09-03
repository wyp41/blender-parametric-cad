---
name: 3d-modelling
description: "Use the Blender Parametric CAD Python API and MCP tools for direct, non-UI 3D modeling from sketches, features, booleans, and per-Part exports."
---

# 3D Modelling

Use this skill when an AI needs to build or edit a model in the Blender 5.1.2
Parametric CAD extension without mouse-driven computer use. Prefer the MCP
tools below when an MCP client is available: the checked-out server first
connects to an existing Blender **CAD MCP Service** and only starts one
persistent, visible worker when no service endpoint is available. A shared
endpoint file and startup lock make MCP process restarts/concurrency reuse the
same Blender window. Requests are serviced by a Blender timer, so the normal
Blender UI stays open and each operation is visible as it completes. Visible
mode keeps Blender's normal startup/preferences, making the enabled CAD panel
and workspace available for human edits.
When writing a Blender Python script directly, construct the persistent
`CadDocument`/`Part`/`Feature` graph, then call `rebuild_part` once. Use Blender
operators only when an existing UI workflow is specifically required.

For manual editing in Blender, the CAD N-panel is organized with a compact
left icon rail: Model, Sketch, Features, and Output. Only the selected section
is expanded, and entering Sketch Edit selects the Sketch section automatically.
The add-on registration path replaces stale or partially registered RNA classes
left by an extension reload, including the transient panel state used by this
icon rail.

The complete callable surface, MCP schemas, field values, units, limitations,
and copyable examples are in
[references/blender_parametric_cad_api.md](references/blender_parametric_cad_api.md).
Read that reference before generating a CAD script. Do not call names starting
with `_`; those are implementation details.

## MCP fast path

Configure an MCP client to run `mcp/server.py` with Python. Set
`BLENDER_CAD_EXECUTABLE` to the Blender 5.1.2 executable and optionally set
`BLENDER_CAD_FILE` to the `.blend` file to open. To bind to a specific already
open window, enable the extension there, open the CAD tab, click **Start
Service in This Window**, and then start/restart the MCP client once. The
bridge reads `BLENDER_CAD_ENDPOINT_FILE` (default: a file in the system temp
directory) and connects to that service before considering a new worker. If no
service is available, the endpoint lock allows at most one fallback worker for
the selected port/path. Mutating calls can autosave to
`BLENDER_CAD_AUTOSAVE` (or to `BLENDER_CAD_FILE` when that variable is omitted).
The worker loads the CAD scene properties itself, so enabling the UI add-on is
not required for a fallback MCP-only session; enable the add-on when you want
the CAD panel and interactive sketch tools in the chosen visible window.
When an endpoint is already available, the bridge ignores `BLENDER_CAD_FILE` so
the selected open Blender window remains authoritative.

Use the same `BLENDER_CAD_PORT` (default `9876`) and optional endpoint path in
the MCP client and the Blender service. A reachable endpoint is authoritative:
the bridge does not launch another Blender window. If an endpoint's process is
still alive but not accepting connections, the bridge fails with a reconnect
message instead of spawning a duplicate.
Set `BLENDER_CAD_AUTOSTART=0` (or pass `--no-autostart`) to enforce an
existing-window-only policy; the client then fails instead of opening a worker
when no service is available.

Workers from releases before 0.15.0 did not publish a reconnectable endpoint;
close any such orphan Blender windows once after upgrading.

Use `--headless` or `BLENDER_CAD_HEADLESS=1` only on machines without a display
or in CI. On macOS, headless mode selects Blender's OpenGL backend by default
to avoid known Metal startup crashes; override it with
`--gpu-backend opengl|metal|vulkan` or `BLENDER_CAD_GPU_BACKEND`. A visible
session can use the same override when the system Metal backend is unstable.

MCP tool groups:

- Document: `cad_status`, `cad_create_part`, `cad_set_active_part`,
  `cad_delete_part`, `cad_validate_document`, `cad_save_scene`.
- Sketch: `cad_create_sketch`, `cad_add_geometry`, `cad_update_geometry`,
  `cad_delete_geometry`, `cad_profile`, `cad_delete_region`,
  `cad_restore_region`.
- Features: `cad_create_extrude`, `cad_create_revolve`, `cad_create_transform`,
  `cad_create_mirror`, `cad_update_feature`,
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
- `TransformFeature` is a normal single-body history entry. Store translation in
  meters and XYZ Euler rotation in radians in direct Python; MCP/UI inputs use
  millimeters/degrees. Its frame is applied to downstream datum and semantic
  Sketch references during every rebuild.
- Store Sketch support plus `plane_reference.offset` (meters) instead of baking
  an offset into `origin`; use `SketchFeature.set_plane_offset()` or the MCP
  `offset_mm` field.
- `MirrorFeature` references one earlier additive `ExtrudeFeature` or
  `RevolveFeature` UUID and a datum/semantic `SketchPlaneReference`. It mirrors
  only that source tool and unions it with the current body. Keep the P0
  one-connected-solid invariant: a disconnected/non-manifold Boolean Add is an
  error.
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
