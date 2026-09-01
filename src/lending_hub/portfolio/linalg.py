"""Small dense linear algebra for the Phase 3 estimators.

Cox partial likelihood and beta regression are both fitted by Newton-Raphson,
which needs a symmetric solve and an inverse for the standard errors. Feature
counts here are tens, not thousands, so Gauss-Jordan with partial pivoting is
the right tool: it is exact arithmetic on the scale involved, it is twenty
lines, and it keeps the core packages stdlib-only (ADR-0003).

What this does not port
-----------------------
No Cholesky, no QR, no conditioning estimate beyond a pivot check. A caller
that hits :class:`SingularMatrix` has collinear features and needs to drop one,
not a better solver — reporting that plainly is more useful than a
pseudo-inverse that returns coefficients nobody can interpret.

Workstream: WS-3.1 (SRS §7.3.2, §7.3.3)
"""

from __future__ import annotations

from typing import Sequence


class SingularMatrix(Exception):
    """The system has no unique solution — almost always collinear features."""


def solve(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> list[float]:
    """Solve ``A x = b`` by Gauss-Jordan elimination with partial pivoting."""
    n = len(rhs)
    if any(len(row) != n for row in matrix) or len(matrix) != n:
        raise SingularMatrix(f"matrix is not {n}x{n}")

    a = [list(row) + [rhs[i]] for i, row in enumerate(matrix)]

    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise SingularMatrix(
                f"column {col} has no usable pivot; two or more inputs are "
                "collinear. Drop one rather than regularising silently — a "
                "coefficient split across duplicated columns is not interpretable."
            )
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [v / scale for v in a[col]]
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if factor:
                a[row] = [v - factor * w for v, w in zip(a[row], a[col])]
    return [a[i][n] for i in range(n)]


def invert(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    """Inverse of a square matrix, for Newton-Raphson standard errors."""
    n = len(matrix)
    columns = []
    for j in range(n):
        basis = [1.0 if i == j else 0.0 for i in range(n)]
        columns.append(solve(matrix, basis))
    return [[columns[j][i] for j in range(n)] for i in range(n)]


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
