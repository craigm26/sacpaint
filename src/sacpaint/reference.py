"""References: a spec of strokes grouped by landmark, rendered to a PNG and a rubric.

A reference is a ``ReferenceSpec``: the canvas size, polylines grouped by
landmark name (canvas millimetres, origin bottom-left, x right, y up), the
landmark weights and boxes, the relations between landmarks, and the scorer
tolerances. Everything else (the PNG the model sees, the rubric the scorers
read, the oracle policy's stroke list) derives from it, so nothing can drift.

The built-in reference is ``sacramento-line-v0``. Any ``<name>.spec.json`` in
the package assets or in ``$SACPAINT_REFERENCES`` (default
``~/.sacpaint/references``) becomes a task named ``sacpaint/<name>`` as soon as
the package is imported; ``sacpaint new`` writes one for you.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import cv2
import numpy as np

DEFAULT_REFERENCE = "sacramento-line-v0"
# The physical sheet is 150 x 200 mm (fits A5 or half-letter with margins) so a
# desk arm like the SO-ARM101 (reach ~370 mm) can cover all of it. The design
# geometry below is written in a 300 x 400 unit frame and scaled; at 4 px/mm the
# canonical image is still 600 x 800 px, so the pinned PNG is unchanged.
CANVAS_MM: tuple[float, float] = (150.0, 200.0)  # width, height of the built-in canvas
PX_PER_MM = 4.0
DESIGN_MM: tuple[float, float] = (300.0, 400.0)  # frame the constants below are written in
_S = CANVAS_MM[0] / DESIGN_MM[0]
STROKE_PX = 3  # rendered line width in the reference
INK_THRESHOLD = 128  # gray below this counts as ink
REFERENCE_PNG = f"{DEFAULT_REFERENCE}.png"
RUBRIC_JSON = f"{DEFAULT_REFERENCE}.json"
SPEC_SUFFIX = ".spec.json"

Point = tuple[float, float]
Stroke = list[Point]


def user_reference_dir() -> Path:
    """Where ``sacpaint new`` writes specs and where extra references are discovered."""
    return Path(os.environ.get("SACPAINT_REFERENCES", "~/.sacpaint/references")).expanduser()


def _rect(x0: float, y0: float, x1: float, y1: float) -> Stroke:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def _arc(cx: float, cy: float, r: float, a0: float, a1: float, n: int = 24) -> Stroke:
    return [
        (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
        for a in np.linspace(a0, a1, n)
    ]


@dataclass
class ReferenceSpec:
    """One benchmark reference. Distances in canvas millimetres; boxes ``[x0, y0, x1, y1]`` mm, y up."""

    name: str
    strokes: dict[str, list[Stroke]]
    canvas_mm: tuple[float, float] = CANVAS_MM
    landmarks: dict[str, dict[str, Any]] = field(default_factory=dict)  # {"weight": n, "bbox_mm": [...]?}
    relations: list[dict[str, Any]] = field(default_factory=list)
    weights: dict[str, float] = field(
        default_factory=lambda: {"landmark_geometry": 0.45, "structure": 0.30, "discipline": 0.15, "efficiency": 0.10}
    )
    structure_tolerance_frac: float = 0.02
    landmark_tolerance_frac: float = 0.01
    discipline_band_frac: float = 0.025
    bbox_pad_mm: float = 6.0
    px_per_mm: float = PX_PER_MM
    stroke_px: int = STROKE_PX
    description: str = ""
    instruction: str | None = None

    # -- geometry -----------------------------------------------------------

    def canonical_size(self) -> tuple[int, int]:
        """Canonical image size as (width_px, height_px)."""
        return round(self.canvas_mm[0] * self.px_per_mm), round(self.canvas_mm[1] * self.px_per_mm)

    def mm_to_px(self, p: Point) -> tuple[int, int]:
        """Canvas-mm point (x right, y up) to image pixel (col, row)."""
        w, h = self.canonical_size()
        col = round(p[0] * self.px_per_mm)
        row = round(h - p[1] * self.px_per_mm)
        return min(max(col, 0), w - 1), min(max(row, 0), h - 1)

    def render(self, strokes_by_name: dict[str, list[Stroke]] | None = None) -> np.ndarray:
        """Render polylines onto a white canonical canvas (RGB uint8)."""
        w, h = self.canonical_size()
        img = np.full((h, w, 3), 255, dtype=np.uint8)
        for group in (strokes_by_name or self.strokes).values():
            for stroke in group:
                pts = np.array([self.mm_to_px(p) for p in stroke], dtype=np.int32).reshape(-1, 1, 2)
                cv2.polylines(img, [pts], isClosed=False, color=(0, 0, 0), thickness=self.stroke_px)
        return img

    def png_bytes(self) -> bytes:
        """Deterministic PNG encoding of the rendered reference."""
        ok, buf = cv2.imencode(".png", cv2.cvtColor(self.render(), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 9])
        if not ok:  # pragma: no cover - cv2 failure
            raise RuntimeError("PNG encoding failed")
        return buf.tobytes()

    def sha256(self) -> str:
        """Identity of the reference: SHA-256 of its PNG bytes."""
        return hashlib.sha256(self.png_bytes()).hexdigest()

    # -- rubric ---------------------------------------------------------------

    def _bbox_mm(self, name: str) -> list[float]:
        lm = self.landmarks.get(name, {})
        if "bbox_mm" in lm:
            return [float(v) for v in lm["bbox_mm"]]
        pts = [p for stroke in self.strokes[name] for p in stroke]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        pad = self.bbox_pad_mm
        return [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad]

    def _norm_bbox(self, box: list[float]) -> list[float]:
        w, h = self.canvas_mm
        x0, y0, x1, y1 = box
        x0, x1 = max(x0, 0.0), min(x1, w)
        y0, y1 = max(y0, 0.0), min(y1, h)
        return [round(x0 / w, 4), round(1 - y1 / h, 4), round(x1 / w, 4), round(1 - y0 / h, 4)]

    def rubric(self) -> dict[str, Any]:
        """The scoring rubric the scorers read: normalized boxes, relations, weights, tolerances."""
        landmarks = {}
        for name in self.strokes:
            lm = self.landmarks.get(name, {})
            if lm.get("score", True) is False:
                continue
            landmarks[name] = {"bbox": self._norm_bbox(self._bbox_mm(name)), "weight": lm.get("weight", 1)}
        return {
            "version": self.name,
            "canvas_mm": list(self.canvas_mm),
            "px_per_mm": self.px_per_mm,
            "ink_threshold": INK_THRESHOLD,
            "landmarks": landmarks,
            "relations": list(self.relations),
            "structure_tolerance_frac": self.structure_tolerance_frac,
            "landmark_tolerance_frac": self.landmark_tolerance_frac,
            "discipline_band_frac": self.discipline_band_frac,
            "weights": dict(self.weights),
        }

    # -- serialization ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-able form (the ``.spec.json`` file)."""
        d = asdict(self)
        d["canvas_mm"] = list(self.canvas_mm)
        d["strokes"] = {k: [[[float(x), float(y)] for x, y in s] for s in v] for k, v in self.strokes.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReferenceSpec:
        """Parse a ``.spec.json`` document, validating the parts the scorers depend on."""
        d = dict(d)
        strokes = {k: [[(float(x), float(y)) for x, y in s] for s in v] for k, v in d.pop("strokes").items()}
        if not strokes:
            raise ValueError("a reference needs at least one stroke group")
        canvas = tuple(float(v) for v in d.pop("canvas_mm", CANVAS_MM))
        if len(canvas) != 2 or min(canvas) <= 0:
            raise ValueError(f"canvas_mm must be [width, height] > 0, got {canvas}")
        spec = cls(strokes=strokes, canvas_mm=canvas, **d)  # type: ignore[arg-type]
        for rel in spec.relations:
            for key in ("a", "b"):
                if rel.get(key) not in strokes:
                    raise ValueError(f"relation refers to unknown landmark {rel.get(key)!r}")
        return spec

    def save(self, path: Path) -> None:
        """Write the ``.spec.json`` file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")


# --- the built-in Sacramento reference -----------------------------------------
# The tower sits on the canopy line at y=205; the dome is in the foreground at the
# bottom; the mall converges from behind the dome up to the bridge deck.

HORIZON_Y = 300.0
CANOPY_Y = 200.0
TOWER = {"x0": 125.0, "x1": 175.0, "y0": 205.0, "y1": 290.0, "cap_x0": 120.0, "cap_x1": 180.0, "cap_y1": 298.0}
DOME = {"cx": 150.0, "cy": 60.0, "r": 70.0}
CUPOLA = {"x0": 135.0, "x1": 165.0, "y0": 130.0, "y1": 165.0, "ball_cy": 178.0, "ball_r": 8.0}
ROAD = {"left": ((112.0, 140.0), (140.0, 205.0)), "right": ((188.0, 140.0), (160.0, 205.0))}
LEFT_BUILDING = {"x0": 10.0, "x1": 70.0, "y0": 100.0, "y1": 260.0}
RIGHT_BUILDING = {"x0": 230.0, "x1": 290.0, "y0": 100.0, "y1": 250.0}


def sacramento_spec() -> ReferenceSpec:
    """The V0 Sacramento composition: Tower Bridge over the Capitol dome, joined by the Mall."""
    t = TOWER
    mid = (t["y0"] + t["y1"]) / 2
    tower = [
        _rect(t["x0"], t["y0"], t["x1"], t["y1"]),
        _rect(t["cap_x0"], t["y1"], t["cap_x1"], t["cap_y1"]),
        [(t["x0"], mid), (t["x1"], mid)],
        [(t["x0"], t["y0"]), (t["x1"], mid)],
        [(t["x1"], t["y0"]), (t["x0"], mid)],
        _rect(140.0, t["y0"], 160.0, 225.0),  # deck opening
    ]
    d, c = DOME, CUPOLA
    dome = [_arc(d["cx"], d["cy"], d["r"], 0.0, 180.0), [(d["cx"] - d["r"], d["cy"]), (d["cx"] + d["r"], d["cy"])]]
    cupola = [
        _rect(c["x0"], c["y0"], c["x1"], c["y1"]),
        _arc(d["cx"], c["ball_cy"], c["ball_r"], 0.0, 360.0, n=20),
        [(d["cx"], c["y1"]), (d["cx"], c["ball_cy"] - c["ball_r"])],
    ]
    lb, rb = LEFT_BUILDING, RIGHT_BUILDING
    pad = 6.0
    design_strokes = {
        "horizon": [[(0.0, HORIZON_Y), (DESIGN_MM[0], HORIZON_Y)]],
        "tower_bridge": tower,
        "canopy": [[(lb["x1"] + 5, CANOPY_Y), (t["x0"], CANOPY_Y)], [(t["x1"], CANOPY_Y), (rb["x0"] - 5, CANOPY_Y)]],
        "road": [list(ROAD["left"]), list(ROAD["right"])],
        "cupola": cupola,
        "capitol_dome": dome,
        "buildings": [_rect(lb["x0"], lb["y0"], lb["x1"], lb["y1"]), _rect(rb["x0"], rb["y0"], rb["x1"], rb["y1"])],
    }
    design_boxes = {
        "tower_bridge": {"weight": 3, "bbox_mm": [t["cap_x0"] - pad, t["y0"] - pad, t["cap_x1"] + pad, t["cap_y1"] + pad]},
        "capitol_dome": {"weight": 3, "bbox_mm": [d["cx"] - d["r"] - pad, d["cy"] - pad, d["cx"] + d["r"] + pad, d["cy"] + d["r"] + pad]},
        "cupola": {"weight": 1, "bbox_mm": [c["x0"] - pad, c["y0"] - pad, c["x1"] + pad, c["ball_cy"] + c["ball_r"] + pad]},
        "road": {"weight": 2, "bbox_mm": [106.0, 134.0, 194.0, 211.0]},
        "buildings": {"weight": 1, "bbox_mm": [lb["x0"] - pad, lb["y0"] - pad, rb["x1"] + pad, lb["y1"] + pad]},
        "horizon": {"weight": 1, "bbox_mm": [0.0, HORIZON_Y - pad, DESIGN_MM[0], HORIZON_Y + pad]},
    }
    return ReferenceSpec(
        name=DEFAULT_REFERENCE,
        description="Sacramento: Tower Bridge above the Capitol dome and cupola, the Capitol Mall between them, two building masses, a horizon.",
        strokes={k: [[(x * _S, y * _S) for x, y in st] for st in v] for k, v in design_strokes.items()},
        landmarks={
            **{k: {"weight": v["weight"], "bbox_mm": [b * _S for b in v["bbox_mm"]]} for k, v in design_boxes.items()},
            "canopy": {"score": False},
        },
        bbox_pad_mm=pad * _S,
        relations=[
            {"kind": "same_x", "a": "tower_bridge", "b": "capitol_dome", "tolerance": 0.05},
            {"kind": "above", "a": "tower_bridge", "b": "capitol_dome"},
            {"kind": "above", "a": "cupola", "b": "capitol_dome"},
            {"kind": "above", "a": "horizon", "b": "tower_bridge"},
        ],
    )


# --- discovery -------------------------------------------------------------------


def _assets_dir() -> Path:
    return Path(str(resources.files("sacpaint").joinpath("assets")))


def spec_search_dirs() -> list[Path]:
    """Directories scanned for ``*.spec.json``, package assets first."""
    return [_assets_dir(), user_reference_dir()]


@lru_cache(maxsize=1)
def _discover() -> dict[str, ReferenceSpec]:
    specs: dict[str, ReferenceSpec] = {DEFAULT_REFERENCE: sacramento_spec()}
    for d in spec_search_dirs():
        if not d.is_dir():
            continue
        for path in sorted(d.glob(f"*{SPEC_SUFFIX}")):
            name = path.name[: -len(SPEC_SUFFIX)]
            if name == DEFAULT_REFERENCE:
                continue  # the built-in is defined in code; the file is a copy for humans
            try:
                spec = ReferenceSpec.from_dict(json.loads(path.read_text()))
            except Exception as exc:  # noqa: BLE001 - a broken user spec must not hide the others
                import warnings

                warnings.warn(f"ignoring reference spec {path}: {exc}", RuntimeWarning, stacklevel=2)
                continue
            spec.name = name
            specs[name] = spec
    return specs


def refresh() -> None:
    """Forget discovered specs (after ``sacpaint new`` writes one in-process)."""
    _discover.cache_clear()
    _image_cache.clear()


def available() -> list[str]:
    """Names of every discoverable reference, built-in first."""
    return list(_discover())


def get_spec(name: str = DEFAULT_REFERENCE) -> ReferenceSpec:
    """Look a reference up by name (``.png`` / ``.spec.json`` suffixes tolerated)."""
    for suffix in (".png", SPEC_SUFFIX, ".json"):
        name = name.removesuffix(suffix)
    try:
        return _discover()[name]
    except KeyError:
        raise KeyError(f"unknown reference {name!r}; known: {available()}") from None


_image_cache: dict[str, np.ndarray] = {}


def reference_image(name: str = DEFAULT_REFERENCE) -> np.ndarray:
    """The reference PNG as RGB uint8. The built-in reads its checked-in file; others render."""
    spec = get_spec(name)
    if spec.name not in _image_cache:
        if spec.name == DEFAULT_REFERENCE:
            data = resources.files("sacpaint").joinpath("assets", REFERENCE_PNG).read_bytes()
            arr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            _image_cache[spec.name] = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        else:
            _image_cache[spec.name] = spec.render()
    return _image_cache[spec.name].copy()


def reference_sha256(name: str = DEFAULT_REFERENCE) -> str:
    """SHA-256 of the reference PNG bytes: the benchmark's identity."""
    spec = get_spec(name)
    if spec.name == DEFAULT_REFERENCE:
        return hashlib.sha256(resources.files("sacpaint").joinpath("assets", REFERENCE_PNG).read_bytes()).hexdigest()
    return spec.sha256()


def load_rubric(name: str = DEFAULT_REFERENCE) -> dict[str, Any]:
    """The rubric for a reference (generated from its spec)."""
    return get_spec(name).rubric()


def strokes(name: str = DEFAULT_REFERENCE) -> dict[str, list[Stroke]]:
    """The reference polylines grouped by landmark (canvas mm)."""
    return get_spec(name).strokes


def canonical_size(name: str = DEFAULT_REFERENCE) -> tuple[int, int]:
    """Canonical image size (width_px, height_px) of a reference."""
    return get_spec(name).canonical_size()


def mm_to_px(p: Point, name: str = DEFAULT_REFERENCE) -> tuple[int, int]:
    """Canvas-mm point to image pixel for a reference's canvas."""
    return get_spec(name).mm_to_px(p)


def render(strokes_by_name: dict[str, list[Stroke]] | None = None, name: str = DEFAULT_REFERENCE) -> np.ndarray:
    """Render polylines (default: the reference's own) on that reference's canvas."""
    return get_spec(name).render(strokes_by_name)


def write_assets(out_dir: str) -> None:
    """Regenerate the built-in PNG, rubric, and spec copy. Maintainers only; a change re-versions the task."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = sacramento_spec()
    (out / REFERENCE_PNG).write_bytes(spec.png_bytes())
    (out / RUBRIC_JSON).write_text(json.dumps(spec.rubric(), indent=2, sort_keys=True) + "\n")
    spec.save(out / f"{DEFAULT_REFERENCE}{SPEC_SUFFIX}")


if __name__ == "__main__":  # pragma: no cover
    import sys

    write_assets(sys.argv[1] if len(sys.argv) > 1 else "src/sacpaint/assets")
