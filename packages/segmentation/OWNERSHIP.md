# Segmentation ownership

Owns morphology model training/inference, artifact rejection, calibration, and
held-out event evaluation; it does not own retrieval thresholds or flux policy.

Real validation events must remain outside training and hyperparameter
selection. Its first executable slice must pair a deterministic baseline with a
model-deletion ablation and fixed clean-scene false-positive evidence before any
learned-morphology claim can be published. Until then, segmentation is
explicitly unavailable.
