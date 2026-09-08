"""Task registration. One scene per reference, one fixed prompt, one pinned reference.

``sacpaint/line-v0`` is the built-in Sacramento task. Every other discoverable
reference (package assets or ``~/.sacpaint/references/<name>.spec.json``)
registers as ``sacpaint/<name>`` when this module is imported, which happens
whenever Inspect Robots loads the ``sacpaint/line-v0`` entry point.
"""

from __future__ import annotations

from typing import Any, Callable

from inspect_robots.registry import task
from inspect_robots.scene import Scene, Target
from inspect_robots.task import Task

from sacpaint.reference import DEFAULT_REFERENCE, available, get_spec, reference_sha256
from sacpaint.scorers import composite, discipline, efficiency, landmark_geometry, structure

INSTRUCTION = (
    "Draw the reference image on the canvas with the pen. You may look at the "
    "overhead camera to inspect your work and make corrections. Stop when you "
    "believe the drawing is complete."
)

TASK_NAME = "sacpaint/line-v0"
DEFAULT_MAX_STEPS = 3000
DEFAULT_EPOCHS = 3


def task_name_for(reference: str) -> str:
    """The registry name a reference runs under."""
    return TASK_NAME if reference == DEFAULT_REFERENCE else f"sacpaint/{reference}"


def make_task(reference: str = DEFAULT_REFERENCE, max_steps: int = DEFAULT_MAX_STEPS, epochs: int = DEFAULT_EPOCHS) -> Task:
    """Build the benchmark task for a reference; the scene's target names the reference for the scorers."""
    spec = get_spec(reference)
    sha = reference_sha256(spec.name)
    return Task(
        name=task_name_for(spec.name),
        scenes=[
            Scene(
                id=f"{spec.name}",
                instruction=spec.instruction or INSTRUCTION,
                target=Target(kind="reference_drawing", spec={"reference": spec.name, "sha256": sha, "rubric": spec.rubric()}),
                metadata={"description": spec.description},
            )
        ],
        scorer=[composite(max_steps), landmark_geometry(), structure(), discipline(), efficiency(max_steps)],
        max_steps=max_steps,
        epochs=epochs,
        metadata={
            "benchmark": "sacpaint",
            "reference": spec.name,
            "prompt_fixed": spec.instruction is None,
            "reference_sha256": sha,
            "track": "closed_loop",
        },
    )


@task(TASK_NAME)
def line_v0(max_steps: int = DEFAULT_MAX_STEPS, epochs: int = DEFAULT_EPOCHS) -> Task:
    """Sacramento PaintBench V0: the line-drawing reference, rubric-scored."""
    return make_task(DEFAULT_REFERENCE, max_steps=max_steps, epochs=epochs)


def _factory(reference: str) -> Callable[..., Task]:
    def build(max_steps: int = DEFAULT_MAX_STEPS, epochs: int = DEFAULT_EPOCHS, **_: Any) -> Task:
        return make_task(reference, max_steps=max_steps, epochs=epochs)

    build.__doc__ = f"PaintBench task for the {reference!r} reference."
    build.__name__ = f"task_{reference.replace('-', '_')}"
    return build


def register_discovered() -> list[str]:
    """Register every non-default reference as ``sacpaint/<name>``; returns the names registered."""
    from inspect_robots.registry import registered

    names = []
    already = registered("task")
    for name in available():
        if name == DEFAULT_REFERENCE:
            continue
        key = task_name_for(name)
        if key not in already:
            task(key)(_factory(name))
        names.append(key)
    return names


register_discovered()
