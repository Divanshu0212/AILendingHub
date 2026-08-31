"""Modelling — training-set construction, logistic scorecard, metrics.

Track P work (ADR-0004): fitted on public reference data, never on this bank's
portfolio. The CLI module :mod:`lending_hub.modeling.experiment` is not
re-exported so ``python -m`` does not double-import it.

Workstream: WS-0.2.3
"""

from .dataset import Design, align, build_design, write_csv
from .logistic import LogisticModel, Standardiser, train
from .metrics import auc, calibration, ks, log_loss, summary

__all__ = [
    "Design",
    "LogisticModel",
    "Standardiser",
    "align",
    "auc",
    "build_design",
    "calibration",
    "ks",
    "log_loss",
    "summary",
    "train",
    "write_csv",
]
