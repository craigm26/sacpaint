"""Sacramento PaintBench: an Inspect Robots benchmark.

The task is one sentence: draw the fixed reference image on the canvas, using
the camera to inspect and correct, and stop when done. The built-in reference
is a deliberately simplified Sacramento composition (Tower Bridge above the
Capitol dome, joined by the Capitol Mall); any ``.spec.json`` of strokes makes
another. Scoring is geometric, not aesthetic: each landmark must be present,
in the right place, in the right relation to the others.
"""

from sacpaint.reference import DEFAULT_REFERENCE, ReferenceSpec, available, canonical_size, get_spec, load_rubric, reference_image
from sacpaint.scorers import composite, discipline, efficiency, landmark_geometry, score_canvas, structure

__all__ = [
    "DEFAULT_REFERENCE",
    "ReferenceSpec",
    "available",
    "canonical_size",
    "composite",
    "discipline",
    "efficiency",
    "get_spec",
    "landmark_geometry",
    "load_rubric",
    "reference_image",
    "score_canvas",
    "structure",
]
