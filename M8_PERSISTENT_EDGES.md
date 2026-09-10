# M8 — Persistent straight edges, Chamfer, and Fillet

M8 extends the M6/M7 semantic reference system with persistent references for
supported straight edges. It does not attempt general topological naming.

## Persistent identity

`EdgeReference` stores only CAD information:

- the producer Feature UUID;
- a role such as `PLANAR_INTERSECTION` or `PLANAR_BOUNDARY`;
- up to two adjacent `PlaneReference` values;
- source Sketch/entity UUID hints; and
- a producer-local `EdgeSignature`.

`EdgeSignature` canonicalizes the unit direction and the closest point on the
infinite line to the producer-local origin. Reversing the edge endpoints, or
using `d` instead of `-d`, therefore produces the same direction identity.
Midpoint and length are disambiguation hints only; neither is accepted as a
sole identity.

Blender mesh edge indices are present only in `ResolvedEdge` and
`EdgeCandidate`, which are runtime objects rebuilt after every evaluation and
after a `.blend` reload. They are not written to the CAD JSON, Blender custom
properties, or Feature definitions.

## Resolution and supported edges

`PersistentEdgeResolver` uses this order:

1. exact runtime provenance;
2. the set of adjacent persistent planes and source entity IDs;
3. the producer-local straight-line signature when no adjacent planes exist;
4. `MISSING` or `AMBIGUOUS` without guessing.

The first supported candidates are:

- Extrude perimeter and vertical edges bounded by known planar faces;
- straight planar/planar Boolean edges;
- straight boundaries of supported partial-Revolve planar caps when the source
  SketchLine is known; and
- straight edges on transformed or mirrored bodies when their semantic planes
  remain resolvable.

Curved, spline, tangent-chain, circular, and fillet-generated downstream edge
references remain unsupported. A tessellation boundary inside one planar
surface is rejected explicitly.

## Viewport and features

The **Select Edges** modal tool uses screen-space hover highlighting and click
selection. `Shift`-click adds another persistent edge; `Enter` confirms the
selection and `Esc` cancels. The UI stores a JSON list of `EdgeReference`
objects, never the runtime edge IDs.

`ChamferFeature` applies one equal distance to one or more selected straight
edges. `FilletFeature` applies one constant radius. Both participate in
history dependencies, editing, rebuild, suppression, rollback, cascade
delete, and save/reload. The Blender backend copies the current body into a
temporary BMesh and calls Blender bevel with one segment for Chamfer and eight
segments for Fillet. A backend failure returns `ERROR` while preserving CAD
history and the last valid display mesh.

MCP exposes `cad_create_chamfer` and `cad_create_fillet`, plus matching edit
fields on `cad_update_feature`. They accept serialized semantic edge
references and reject mesh-index-based inputs by construction.

## Tolerances

Edge matching tolerances are centralized in `EdgeMatchTolerance`:

| category | default |
| --- | ---: |
| direction | `1e-6` |
| absolute line distance | `1e-7 m` |
| relative line distance | `1e-6` |
| absolute midpoint | `1e-6 m` |
| relative midpoint | `1e-5` |
| absolute length | `1e-7 m` |
| relative length | `1e-5` |
| endpoint | `1e-6 m` |
| relative endpoint | `1e-5` |
| full-Revolve angle | `1e-9 rad` |

No feature-specific edge epsilon is introduced. The existing centralized
`PlaneMatchTolerance` remains responsible for adjacent planar-face matching.

## M8.1 verification status

Validated against Blender `5.1.2` / Python `3.13.9` through the connected CAD
MCP service. The trusted `blender_execute_python` path was verified directly
against the running Blender process, so the validation did not require
Computer Use for script execution.

The real Blender validation covers:

- Chamfer and Fillet on persistent straight edges;
- multi-edge Chamfer;
- Transform edits with edge-reference re-resolution;
- Boolean-derived straight edges;
- missing and ambiguous references becoming `BLOCKED`;
- suppression, rollback, roll-forward, and cascade delete;
- repeated rebuilds without duplicate result objects or leaked Boolean helpers;
- semantic-only save data with no mesh edge index; and
- save, `open_mainfile`, runtime-cache rebuild, and post-reload resolution.

Results:

- `BLENDER_PARAMETRIC_CAD_M8_1_CORE_VALIDATION_OK`;
- `BLENDER_PARAMETRIC_CAD_M8_1_RELOAD_OK`;
- repository regression suite: `96` tests passed;
- `cad_validate_document`: valid with no diagnostics; and
- changed Python files compile cleanly with `git diff --check` passing.

The edge-selection operator and CAD scene properties are registered in the
live Blender process. In the unlocked Blender window, the modal was entered,
a supported straight edge highlighted blue on hover, changed to orange after
click, showed `Edges selected: 1`, and returned to the feature editor after
`Enter`. An unsupported edge produced an explicit warning. Shift multi-select
is covered by the real multi-edge rebuild path and the selection code, but a
separate pointer-level Shift-click was not automated in this pass.

A standalone Blender 5.1.2 process also ran the core script and a second
process reopened the saved file; both completed successfully. This particular
Blender build reports only `metal` as an accepted `--gpu-backend` value, so an
attempted OpenGL override printed a startup warning but did not prevent either
validation script from running.

## Known limitations / next milestone

M8 does not add curved persistent edges, tangent-chain propagation,
variable-radius fillets, asymmetric chamfers, Fillet-created downstream edge
identity, multiple bodies, OpenCASCADE, STEP, or a general topological naming
system. The recommended next milestone remains M9 — Sketch Constraints and
Dimensions.
