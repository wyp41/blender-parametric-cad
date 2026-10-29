# Architecture and validation

[Home](../README.md) · English | [简体中文](development.zh-CN.md)

This consolidates the former M6, M7, M8 and M11A implementation notes into the
current 0.18.1 design. Milestone-specific claims below are historical records,
not a claim that every suite was rerun for a documentation/video update.

## Document ownership and history

The Blender-independent `CadDocument`, `Part`, `Feature`, `Assembly` and
`AssemblyInstance` classes own persistent state. Each Part Studio has one
ordered, single-body feature history. Assemblies reference Parts; they do not
copy histories or undergo the single-connected-body check themselves.

Schema v3 stores one canonical document in the fake-user Text datablock
`CAD_DOCUMENT.json`. `adapter.load_document()` / `save_document()` are the
primary bridge; the Scene-named load/save functions remain compatibility
wrappers. Document JSON uses short, indented lines to avoid Blender Text's
quadratic insertion cost on megabyte-long single lines.

Migration deep-copies legacy data, preserves UUIDs and semantic references, and
adds `assemblies: []` to v2 documents. Without a canonical Text, loading scans
all Scenes. Conflicting nonempty legacy documents raise `MIGRATION_CONFLICT`
without modifying them. Successful migration retires writable Scene copies;
an empty active Scene cannot overwrite an existing nonempty model.

Evaluation follows dependencies, suppression and rollback. Failed features
become `ERROR`, dependent features become `BLOCKED`, and the last valid mesh
remains visible. Generated meshes are disposable; UUIDs and CAD history are the
contract. Externally modified meshes/modifiers are outside that contract.

## Persistent planar references

`PlaneReference` / `SketchPlaneReference` store datum, feature-plane, semantic
face or supported derived-plane identity plus a meter-valued offset.
`FaceReference` identifies the producer Feature, role and optional source
SketchLine UUID. Compatibility aliases and legacy flattened fields remain
readable. Blender polygon indices are never serialized.

Evaluation builds semantic planes. Extrude supplies start/end planes and
SketchLine side planes; Through All supplies side planes only because its caps
depend on runtime bounds. A partial Revolve supplies source `START_CAP` and
parametrically rotated `END_CAP` frames. A full-turn Revolve exposes disk/annulus
caps only when a straight profile line is perpendicular to its resolved axis;
the source line UUID identifies each cap. Curved sides remain unsupported.

Runtime face matching tries verified exact provenance, then semantic planes in
stable history order. A polygon's normal must be parallel/antiparallel and all
vertices must lie on the plane. Split end polygons share canonical `END_PLANE`
support; coincident producers without exact provenance prefer the earliest
historical producer. Matching uses mesh-local coordinates. Display transforms
are applied to highlights, not saved as polygon identities.

Transform updates origins and complete frame vectors. Mirror derives supported
additive Extrude/Revolve references using its own producer UUID and source
role/line UUID; reflecting the axes and reversing Y preserves a right-handed
frame. Later transforms propagate those frames without baking downstream
Sketch coordinates.

Boolean-created planar regions without semantic matches use `DERIVED_PLANE`:
producer UUID, canonical producer-local normal/offset, source Feature hints,
and optional centroid/area `RegionHint`. Connected coplanar split/triangulated
polygons form one candidate; an existing semantic plane takes precedence.
Resolution order is exact provenance → semantic plane → derived plane. Hints
must distinguish one candidate; otherwise resolution is `MISSING` or
`AMBIGUOUS` and the downstream Sketch is blocked.

Face hover/selection and New Sketch share the rebuilt runtime cache. A supported
selection stores a semantic reference and aligns the orthographic view to its
complete frame, including tilted planes. Unsupported faces produce an explicit
message. The cache is rebuilt on evaluation/reload, not persisted in JSON or
custom properties. Matching is O(polygons × semantic planes), not general
geometry/topology repair.

## Persistent straight edges and edge features

`EdgeReference` stores a producer UUID, role (`PLANAR_INTERSECTION` or
`PLANAR_BOUNDARY`), up to two adjacent planes, source entity hints and a
producer-local `EdgeSignature`. The signature canonicalizes direction and the
closest point on the infinite line to the origin; reversing endpoints gives
the same identity. Midpoint and length only disambiguate, never identify alone.

Resolution tries exact provenance, adjacent planes/source IDs, then the local
line signature when adjacent planes are absent. Missing or ambiguous matches
are never guessed. Supported cases are Extrude perimeter/vertical edges,
planar/planar Boolean edges, supported partial-Revolve cap boundaries, and
resolvable transformed/mirrored straight edges. Tessellation boundaries inside
one plane, curved edges, tangent chains and Fillet-created downstream edge
identities are unsupported.

Select Edges uses hover/click, Shift-click adds, Enter confirms, Esc cancels.
Transient selection stores semantic JSON, not runtime edge indices.
`ChamferFeature` uses equal distance; `FilletFeature` uses constant radius.
The backend bevels a temporary BMesh with one/eight segments respectively.
Both participate in dependencies, edits, rebuilds, suppression, rollback,
cascade deletion and reload; failures preserve the last valid result.

### Central tolerances

| Matching quantity | Default |
| --- | ---: |
| Plane normal | `1e-6` |
| Plane absolute distance | `1e-7 m` |
| Plane size-relative distance | `1e-8` |
| Derived-plane centroid | `1e-6 m`, relative `1e-5` |
| Derived-plane area | relative `1e-5` |
| Edge direction | `1e-6` |
| Edge line distance | `1e-7 m`, relative `1e-6` |
| Edge midpoint | `1e-6 m`, relative `1e-5` |
| Edge length | `1e-7 m`, relative `1e-5` |
| Edge endpoint | `1e-6 m`, relative `1e-5` |
| Full-Revolve angle | `1e-9 rad` |

`PlaneMatchTolerance` and `EdgeMatchTolerance` own these values. No separate
feature-specific edge epsilon is introduced.

## Linked Assembly implementation

Each `AssemblyInstance` has its own UUID, source Part UUID, name, suppression
and rigid 4×4 transform. Stored transforms must have proper rotation, no scale
or shear. UI/MCP use mm/degrees; core data uses meters and rotation matrices,
with XYZ input composed as `Rz @ Ry @ Rx`.

A stable `CAD_PART_<uuid>` source collection lives under fake-user
`CAD_SOURCE_ROOT`. Rebuilding retains the result Object, swaps its Mesh,
preserves material slots and refreshes provenance caches; unused old meshes
are removed. Source object/collection offsets remain identity/zero.
Each visible instance is an Empty referencing that source collection inside
`CAD_ASSEMBLY_<uuid>`, tagged by Part/Assembly/Instance UUID. No source mesh is
copied. Suppression removes the carrier while retaining its persistent UUID.

A source rebuild updates shared geometry without writing instance placements.
Failure marks source/carriers stale and explains last-valid-geometry display.
Synchronization assigns base location/quaternion/scale separately to avoid
baking animated deltas into `matrix_world`. Native planar-motion helpers use
quaternion driver channels and remove default F-curve mapping keys, which would
otherwise snap tiny positive meter-valued translations to zero. Static helper
calls without motion expressions are valid no-ops.

Scene roles are `PART_STUDIO` and `ASSEMBLY`, independent of names. Each Scene
links its own active source/Assembly collection without global viewport hiding.
Existing main windows are reused; headless and load handlers do not create GUI
windows. Assembly selection does not alter source Sketch/Feature editing state.
Edit Source Part routes to the existing source window, or changes the current
window when none exists. Toolbar entries are contextual per window; Sketch
face/edge picking is disabled in Assembly scenes.

Deleting an in-use source raises `PART_IN_USE` with all references. Deleting an
Assembly removes its owned collections/carriers, not source Parts.
`commit_assembly()` validates and allocates missing carriers before committing;
allocation failure cleans additions and restores the previous document/display
without destroying existing carriers. The MCP worker resolves authoring to the
Part Studio independently of its active window and reuses one process service.
The persistent load handler re-arms that service because file loading clears
timers.

## Validation evidence

| Area | Recorded coverage |
| --- | --- |
| M6/M6.2 | 91 historical Python tests; real Extrude/Revolve cap picking, tilted frames, Boolean splits, Transform/Mirror, reload |
| M8.1 | 96 historical regression tests; real Chamfer/Fillet, multi-edge rebuild, Boolean edges, missing/ambiguous handling, cleanup, separate-process reload |
| M11A | 124 historical Python checks on Python 3.9.6/3.13.9; actual shared-instance geometry, schema migration, GUI windows and socket transport |
| 0.18.1 gear workflow | 41 focused Python checks; millimeter STL bounds, materials, small motions, sync, source rebuild and save/reopen |
| Mechanism gallery | 25 manifold positive-volume meshes; 14 scenes × 73 samples; actual world transforms, closure/interference and STL dimensions |
| Promotion media | Actual 8→12 mm CAD rebuilds; full video/audio decode and caption-timing checks in each production report |

Historical M6 checks included a 120° frustum, split end-cap polygons mapping to
one support, full-turn cap selection, axis reversal and save/reload caches.
M8.1 pointer-level Shift-click was not separately automated, although native
hover/single-click and the real multi-edge rebuild path were verified.

M11A uses A=80×50×20 mm and B=20×10×30 mm, with B instances at ±50 mm and one
rotated 180°. Evaluated world bounds verify a single shared B source, width
edits 20→35→40 mm, stable IDs/placements, stale/error recovery, suppression,
source-delete protection and allocation rollback. Two actual GUI windows verify
20→35→42 mm edits, independent toolbars, source routing and window reuse.
The current migration script generates a temporary v2 fixture; the old ZipString
sample used in an earlier run has been removed. Conflict migration remains
non-destructive. GUI evidence is from macOS, not Windows/Linux desktop testing.

Gallery collision sampling is not a continuous collision proof or a load test.
The [gallery documentation](../examples/mechanisms/README.md) records allowed
contacts and omitted supports. Metadata reports actual checks; historical counts
are not universal coverage guarantees.

## Reproduce selected checks

For tests that import `blender_parametric_cad`, clone using that importable folder
name. From the repository root, with its parent on the Python import path:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t .. -q
blender --background --factory-startup --python-exit-code 1 --python tests/blender_gear_workflow_validation.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_m11a_validation.py
blender --factory-startup --python-exit-code 1 --python tests/blender_m11a_gui_validation.py
BLENDER_CAD_GPU_BACKEND=metal python3 tests/m11a_mcp_transport_validation.py
```

The first command runs the full Python suite; use individual test modules for a
focused change. The GUI script opens real windows. GPU overrides must match the
installed build. Additional stage-specific scripts remain under `tests/`; they
have not been deleted during documentation consolidation.

Implementation is organized in `core/`, `sketch/`, `features/`, `geometry/`,
`blender/`, and `mcp/`. The [complete API reference](../skills/3d-modelling/references/blender_parametric_cad_api.md)
remains at its MCP resource path. The four old milestone documents are available
in [the v0.18.1 Git history](https://github.com/wyp41/blender-parametric-cad/tree/v0.18.1)
for the original per-run details.
