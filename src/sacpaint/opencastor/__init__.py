"""The OpenCastor body: sacpaint on a real SO-ARM101 behind the robot-md-gateway.

Four pieces, each usable on its own:

* :mod:`~sacpaint.opencastor.client` — invoke gateway tools and keep the
  Ed25519-signed receipt of every one;
* :mod:`~sacpaint.opencastor.calibration` — the canvas-to-arm-base transform,
  taught once from the sheet corners;
* :mod:`~sacpaint.opencastor.cameras` — fetch the latest overhead frame, and the
  tapped canvas corners, over plain HTTP;
* :mod:`~sacpaint.opencastor.embodiment` — the Inspect Robots ``Embodiment`` that
  puts them together.

Install the extra and register the entry point, then::

    inspect-robots run --task sacpaint/line-v0 --policy agent --embodiment opencastor \\
        -E pair_payload=/path/to/pair-payload.json -E calibration=canvas.json

See ``docs/opencastor.md`` for the ten-minute setup.
"""

from sacpaint.opencastor.calibration import CalibrationError, CanvasCalibration, fit, load, save
from sacpaint.opencastor.cameras import (
    CornerFetchError,
    FrameFetchError,
    HttpCornerSource,
    HttpFrameSource,
    StaticCornerSource,
    StaticFrameSource,
)
from sacpaint.opencastor.client import GatewayClient, GatewayDenied, GatewayFault, InvokeResult
from sacpaint.opencastor.embodiment import OpenCastorEmbodiment, opencastor_embodiment

__all__ = [
    "CalibrationError",
    "CanvasCalibration",
    "CornerFetchError",
    "FrameFetchError",
    "GatewayClient",
    "GatewayDenied",
    "GatewayFault",
    "HttpCornerSource",
    "HttpFrameSource",
    "InvokeResult",
    "OpenCastorEmbodiment",
    "StaticCornerSource",
    "StaticFrameSource",
    "fit",
    "load",
    "opencastor_embodiment",
    "save",
]
