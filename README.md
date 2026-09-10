# Sacramento PaintBench moved into OpenCastor

This benchmark now lives inside the OpenCastor runtime as `castor bench sacpaint`
(import name `castor.bench.sacpaint`). The last standalone release was `sacpaint 0.3.1` on PyPI. From 0.4.0 the PyPI
package `sacpaint` is a pointer: it contains no code and only depends on
`opencastor[paintbench]`, so `pip install sacpaint` still installs the benchmark
(`import sacpaint` no longer works; use `castor.bench.sacpaint`). Everything lives in
[craigm26/OpenCastor](https://github.com/craigm26/OpenCastor).

```bash
pip install "opencastor[paintbench]"
castor bench sacpaint score photo-of-my-drawing.jpg
castor bench sacpaint run --policy sacpaint_trace --embodiment sacpaint_plotter --no-rerun --no-prompt
```

Docs: [docs/benchmarks/sacpaint.md](https://github.com/craigm26/OpenCastor/blob/main/docs/benchmarks/sacpaint.md).
The task names (`sacpaint/photo-v1`, `sacpaint/line-v0`), the reference hashes,
the scorers and the media categories are unchanged by the move.
