# M7 — Persistent derived planar references

M7 extends the M6 planar support model for planar regions created by an ADD or
REMOVE Boolean when the region does not lie on an existing semantic plane.

## Persistent identity

The saved `DERIVED_PLANE` reference contains only:

- the Boolean producer Feature UUID;
- a canonical producer-local unit normal and plane offset;
- source Feature UUID hints; and
- an optional `RegionHint` containing local centroid and area.

The runtime candidate also records the current polygon group, but polygon
indices are never copied into the reference, CAD JSON, or Blender custom
properties.

Equivalent planes use one canonical normal sign, so `n` and `-n` serialize to
the same identity. The producer-local frame is obtained from the current
history frame before downstream Transform propagation.

## Candidate extraction and matching

After a Boolean evaluation, planar mesh polygons are grouped by local plane and
shared runtime boundary edges. Connected split/triangulated polygons become
one candidate. Existing M6 semantic planes are checked first and suppress a
derived candidate when they match.

Resolution order is exact provenance, existing semantic plane, then derived
plane. A derived reference matches its producer, local plane normal, and local
offset. If several candidates share that plane, the centroid and area hint must
select exactly one; otherwise the reference is reported as ambiguous. If no
candidate remains, it is reported as missing. A downstream Sketch is marked
`BLOCKED` in either case instead of attaching to a guessed face.

`PlaneMatchTolerance` remains centralized. M7 adds centroid tolerance
`1e-6 m`, relative centroid tolerance `1e-5`, and relative area tolerance
`1e-5`; the M6 normal/distance values remain unchanged.

## Runtime and reload behavior

The candidate cache is rebuilt after every Part evaluation and after loading a
`.blend`. Downstream Transform updates candidate world planes while preserving
their producer-local signatures. The viewport uses the same cache for hover,
selection, and Sketch creation. The cache is intentionally not serialized.

M7 does not add persistent edges, curved-face supports, fillets, chamfers,
topology repair, or external modifier support.
