# Flux ownership

Owns column conversion, integrated mass enhancement, wind coupling, uncertainty
propagation, and abstention when required inputs or quality are missing.

It may consume versioned masks and retrieval products but never emit a point
flux without mask quality, wind source/time, interval, units, and dominant
uncertainty. Its first executable slice must property-test units and interval
coverage across wind sensitivity and refuse every incomplete-input state. Until
then, flux estimation is explicitly unavailable.
