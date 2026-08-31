"""Load and cross-validate the source registry in ``config/sources/``.

Workstream: WS-0.1.1
"""

from __future__ import annotations

import pathlib

from .schema import SourceRecord, ValidationError, validate_document

DEFAULT_REGISTRY_DIR = pathlib.Path("config/sources")


class RegistryUnavailable(RuntimeError):
    pass


def _load_yaml(path: pathlib.Path) -> object:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise RegistryUnavailable(
            "PyYAML is needed to read the source registry: "
            "pip install -r requirements-dev.txt"
        ) from exc
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_registry(
    directory: pathlib.Path | str = DEFAULT_REGISTRY_DIR,
) -> tuple[list[SourceRecord], list[ValidationError]]:
    """Load every ``*.yaml`` in ``directory`` and validate it.

    Returns the valid records and every error found. Errors are collected rather
    than raised on the first failure so one CI run reports the whole picture.
    """
    directory = pathlib.Path(directory)
    if not directory.is_dir():
        raise RegistryUnavailable(f"registry directory not found: {directory}")

    records: list[SourceRecord] = []
    errors: list[ValidationError] = []

    for path in sorted(directory.glob("*.yaml")):
        rel = str(path)
        try:
            doc = _load_yaml(path)
        except Exception as exc:  # noqa: BLE001 - report parse failure as an error
            errors.append(ValidationError(rel, "<parse>", str(exc)))
            continue
        record, doc_errors = validate_document(doc, rel)
        errors.extend(doc_errors)
        if record is not None:
            records.append(record)

    errors.extend(_cross_validate(records))
    return records, errors


def _cross_validate(records: list[SourceRecord]) -> list[ValidationError]:
    """Rules that only make sense across the whole registry."""
    errors: list[ValidationError] = []

    seen: dict[str, str] = {}
    for record in records:
        if record.id in seen:
            errors.append(
                ValidationError(
                    record.path, "id", f"duplicate id {record.id!r}, first seen in {seen[record.id]}"
                )
            )
        else:
            seen[record.id] = record.path

        if record.raw.get("filename_id_must_match", True):
            stem = pathlib.Path(record.path).stem
            if stem != record.id:
                errors.append(
                    ValidationError(
                        record.path,
                        "id",
                        f"id {record.id!r} does not match filename stem {stem!r}",
                    )
                )

    # The identity spine (WS-0.1.3) joins CBS, LOS and collections. If any of the
    # three stops declaring the keys it contributes, the join audit silently
    # narrows instead of failing, so the registry asserts it here.
    spine_sources = {"cbs", "los", "collections"}
    present = {r.id for r in records}
    for missing in sorted(spine_sources - present):
        errors.append(
            ValidationError(
                "config/sources/", missing,
                "identity spine requires this source to be registered (WS-0.1.3)",
            )
        )

    for record in records:
        if record.id in spine_sources and not record.entities:
            errors.append(
                ValidationError(
                    record.path, "entities",
                    "identity-spine sources must declare the entity keys they supply",
                )
            )

    return errors


def unresolved_policy_fields(records: list[SourceRecord]) -> list[tuple[str, str]]:
    """``(source id, dotted field)`` for every `[POLICY]` value still a placeholder."""
    return [(r.id, f) for r in records for f in r.unresolved]
