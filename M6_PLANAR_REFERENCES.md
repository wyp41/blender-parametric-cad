# M6 — Persistent planar references

## Persistent data

`FaceReference` identifies a producer feature, role, and optional source
SketchLine UUID. `PlaneReference` identifies a datum, feature plane, or semantic
face plus a meter-valued offset. FACE references carry a `FaceReference`;
legacy flattened fields remain readable and are emitted for compatibility.
`TopoReference` and `SketchPlaneReference` remain available to existing callers.
No polygon, face, or edge index is serialized. Sketch dependencies point to
the producer UUID, including Mirror producers.

## Runtime resolution

Successful history evaluation builds `EvaluationContext.semantic_planes`.
Extrude contributes start/end and source-line side planes. Through All tools
contribute side planes only because their end caps depend on runtime bounds.
Partial Revolve contributes `START_CAP` on the source Sketch plane and
`END_CAP` on that plane rotated parametrically around the resolved datum or
SketchLine axis. A full 360-degree Revolve has no sweep-boundary caps, but each
profile SketchLine perpendicular to the axis can generate a real planar disk
or annulus. Those top/bottom caps are published as `START_CAP`/`END_CAP` with
the source SketchLine UUID. A full-turn profile without such a line remains
unsupported for face attachment.
Boolean operations discard old polygon provenance but preserve semantic planes.
After rebuilding a display mesh, `PlanarFaceResolver` produces a runtime
`FaceCandidate` for each polygon. Exact provenance is tried first and verified
geometrically; remaining historical planes, including transformed/mirrored
planes, are tried in stable history order. Polygon normals must be parallel
or antiparallel and every vertex must lie on the candidate plane.

End-face matches are canonicalized to `END_PLANE`, so split polygons share one
persistent support. Coincident planes without exact provenance prefer the
earliest historical producer. The cache is never saved to custom properties
or document JSON. Entering face selection rebuilds it after reopening a file.

`PlaneMatchTolerance` centralizes the normal tolerance (1e-6), absolute local
distance (1e-7 meters), and polygon-size-relative distance factor (1e-8).
Matching uses mesh-local coordinates, the same coordinates as evaluated CAD
planes. Display object transforms are applied only when rendering highlights.

## Transform and Mirror

Transform updates every semantic origin and all three frame vectors together.
Downstream Sketch resolution reads those updated planes without baking world
coordinates. Editing Transform and rebuilding regenerates the same references.
Mirror derives references using the Mirror feature UUID and the source role /
line UUID for supported additive Extrudes and Revolves. Its frames reflect the
origin and axes, reversing Y to retain a right-handed frame. Later Transform
operations also update those mirrored planes.

## Viewport workflow

Face selection and hover read the runtime candidate cache. A supported click
stores the PlaneReference in transient selection state. New Sketch deserializes
that reference, enters Sketch Edit, and aligns the orthographic view using the
complete resolved frame, including tilted planes. Unsupported selections report:
“This face cannot yet be used as a persistent Sketch reference.”

## Supported and unsupported surfaces

Supported: Extrude START/END and SketchLine SIDE surfaces; partial Revolve
`START_CAP`/`END_CAP` surfaces; full-turn Revolve profile-line disk/annulus
caps; surviving semantic planes after Add/Remove or
other Boolean operations; transformed versions; and known mirrored additive
Extrude/Revolve planes. Unsupported: arbitrary intersection faces without a
semantic match, curved conical/cylindrical surfaces, fillets, chamfers, and
arbitrary mesh topology. A conical bottom/end cap is supported because its
plane is derived from the Revolve history; the conical side is not.

## Validation and limits

91 Python tests passed using the available Python test runner. The
M6/M6.2 tests cover split-top and split-cap matching, side UUIDs and rectangle
edits, SketchLine-axis edits, Transform changes, Mirror and subsequent
Transform, unsupported geometry, Remove propagation, exact-provenance
priority, rollback/suppression, full-turn profile-cap resolution, right-handed
frames, and serialization without polygon indices.

Blender 5.1.2 real-mesh and GUI checks were also executed: a 120° frustum
Revolve produced START_CAP and END_CAP candidates, GUI selection stored
`FACE/END_CAP`, and New Sketch entered edit mode aligned to the cap. A real
REMOVE Through All split the end cap into two polygons, both mapping to the
same END_CAP reference. SketchLine-axis reversal, Transform -12° to -8°,
full-turn top/bottom cap selection, and downstream Sketch propagation all passed. Saving
and reopening `m6_2_validation.blend` rebuilt the 191-vertex/139-polygon
cache, retained two END_CAP candidates, and left the downstream Sketch OK.
The earlier `m6_1_validation.blend` Extrude/Transform/Mirror GUI and reload
checks also remain passing.
The service timer is re-armed from the persistent load handler because
Blender clears timers while opening a file.

Known limits: a full-turn profile must contain a straight profile SketchLine
perpendicular to the current axis to expose a planar cap; curved
conical/cylindrical side surfaces remain unsupported. Coincident producers are
resolved by provenance then history order; matching is O(polygons × semantic
planes); manually modified generated meshes / external modifiers are outside
the persistent CAD contract. M7 now adds derived planar references for
Boolean-created faces that cannot map to an existing semantic plane; see
`M7_DERIVED_PLANAR_REFERENCES.md`. Persistent edges, curved-face references,
and topology repair remain outside the current scope.

## M6.2 — Revolve cap references

`START_CAP` and `END_CAP` are derived from the source Sketch frame and the
current resolved axis. For a partial sweep the end frame is a Rodrigues
rotation of the complete source frame around that axis and therefore remains
right-handed. For a full sweep, each supported radial profile SketchLine gets
a deterministic cap role and its UUID is part of the reference. Axis
direction, Transform, Mirror, Boolean splitting, and save/reopen all reuse
the same derivation; no mesh vertex, polygon, edge, or Blender topology index
is stored in the CAD document.
