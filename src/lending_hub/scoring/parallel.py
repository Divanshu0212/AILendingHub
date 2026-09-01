"""Process-level parallelism for the embarrassingly-parallel parts of a fit.

ADR-0003 keeps the core packages stdlib-only, which rules out numpy and with it
the vectorised inner loops a numeric library would provide. It does **not** rule
out :mod:`concurrent.futures`, which is also stdlib — and on a sixteen-core
machine a single-threaded fit leaves fifteen cores idle for the whole run.

What is parallel here and what is not
-------------------------------------
Two phases are independent per item and parallelise cleanly:

* **Binning.** Every feature is binned against the same labels with no reference
  to any other feature.
* **The hyperparameter search.** Every configuration is fitted independently.

Boosting itself is **not** parallelisable across trees, and no amount of hardware
changes that: tree *m* is fitted to the residuals left by trees 1..m−1. Within a
tree the per-feature histograms could in principle be split, but each node would
have to ship its gradients and hessians to every worker, and at several thousand
nodes per fit the transfer cost exceeds the arithmetic it saves. So the final fit
stays sequential, and the honest thing is to say so rather than to add a pool that
makes it slower.

Determinism is preserved. Results are returned in input order regardless of
completion order, so a parallel run and a serial run of the same seed produce the
same model — which matters more here than the speed does, because WS-0.2.3 makes
reproducibility a gate.

Workstream: WS-1.1 Steps 2-4 · ADR-0003
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")

#: Leave one core for the operating system and whatever else the machine is
#: doing. A pool sized to every core makes a laptop unusable during a fit and
#: buys almost nothing, because the last worker is competing with the parent.
RESERVED_CORES = 1


def worker_count(requested: int | None = None) -> int:
    """How many workers to use. ``None`` means "as many as sensible"."""
    if requested is not None:
        return max(1, requested)
    available = os.cpu_count() or 1
    return max(1, available - RESERVED_CORES)


def pmap(
    function: Callable[[T], R],
    items: Sequence[T],
    *,
    workers: int | None = None,
    chunksize: int = 1,
) -> list[R]:
    """Map ``function`` over ``items``, in parallel where that helps.

    Falls back to a serial map whenever parallelism would not pay or cannot work:
    a single worker, fewer items than workers, or an environment where a process
    pool cannot start (a restricted sandbox, a frozen interpreter, a platform
    without fork). The fallback is silent because it is not a failure — the
    result is identical, only slower — but it is also why ``function`` must be a
    module-level callable: a closure or a lambda pickles in neither case, and
    finding that out only on the machine with many cores is the worst place to
    find it out.
    """
    items = list(items)
    n = worker_count(workers)
    if n <= 1 or len(items) <= 1:
        return [function(item) for item in items]

    try:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=min(n, len(items))) as pool:
            # executor.map yields in input order, not completion order, so the
            # result does not depend on which worker finished first.
            return list(pool.map(function, items, chunksize=chunksize))
    except Exception:  # noqa: BLE001 - any pool failure falls back to serial
        return [function(item) for item in items]


def imap(
    function: Callable[[T], R], items: Iterable[T], *, workers: int | None = None
) -> list[R]:
    """:func:`pmap` over an iterable of unknown length."""
    return pmap(function, list(items), workers=workers)
