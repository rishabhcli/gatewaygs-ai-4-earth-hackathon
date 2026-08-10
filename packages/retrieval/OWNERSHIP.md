# Retrieval ownership

Owns band alignment, quality/cloud/heterogeneity masks, orbit-and-geometry-safe
reference matching, MBMP/MBSP retrieval, and each scene's empirical null.

It must accept validated array/domain types rather than provider objects and
must never substitute L2A for a declared L1C retrieval. Its first executable
slice must include known-array radiometric/geometric tests, seasonal reference
regressions, a per-scene threshold property test, units, and complete input/LUT
provenance. Until then, retrieval is explicitly unavailable.
