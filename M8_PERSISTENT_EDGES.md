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

## Verification status

The Blender-independent M8 tests cover canonical direction, runtime cache
construction, semantic resolution, Chamfer/Fillet evaluator calls,
missing/ambiguous blocking, semantic-only serialization, and MCP schemas.
The complete repository Python test suite and compile check pass.

Per the development instruction for this iteration, Blender was not launched.
Consequently the Blender 5.1.2 GUI hover/click path and live BMesh bevel output
still require a later in-Blender smoke test. This is intentional and is not
reported as completed real-GUI validation.

## Known limitations / next milestone

M8 does not add curved persistent edges, tangent-chain propagation,
variable-radius fillets, asymmetric chamfers, Fillet-created downstream edge
identity, multiple bodies, OpenCASCADE, STEP, or a general topological naming
system. The recommended next milestone remains M9 — Sketch Constraints and
Dimensions.
