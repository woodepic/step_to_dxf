# Nesting benchmarks

Run the harness against both engines:

```bash
./venv/bin/python bench/instances.py          # list the instances
./venv/bin/python bench/run.py 6 8            # per-instance, polygon vs rectangle
./venv/bin/python bench/population.py 16      # 16 random kitchen jobs
./venv/bin/python bench/population.py sweep 16   # does more effort buy anything?
```

## The instances

`exact-*` and `cut-*` are built by guillotine-cutting whole sheets into pieces,
so the optimum is known by construction. They are deliberately brutal: dropping
a sheet on any of them needs 98.5–99.3% density, essentially a perfect packing.
`exact-*` has zero slack, which no floating-point packer will rebuild — it is a
stress test, not a target.

`kitchen-*` are realistic jobs made of cabinet-sized panels. These are the ones
worth optimising for, and the population run is the honest measure: most jobs sit
far from the boundary where one extra point of density removes a sheet, so what
matters is how often a better packer crosses it.

## What to read

The area bound (`total part area / usable sheet area`, rounded up) is a *lower*
bound and often unreachable — the "needed density to drop a sheet" figure is the
number that tells you whether a gap is real or arithmetic.
