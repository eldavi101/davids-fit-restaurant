"""Runtime settings: persisted overrides layered on the compiled-in strategy defaults.

Requirement 48 draws a hard line here. Parameters that change *how a stock is judged*
(scoring weights and BUY-gate thresholds) cannot be edited in place, because doing so
would silently make historical alerts incomparable with new ones. Changing them requires
``create_version=True``, which mints a new ``strategy_versions`` row; existing alerts keep
their original version and are never re-evaluated under the new logic.

Operational parameters (sync cadence, universe filters, portfolio limits) can be changed
freely — they affect what happens next, not how the past is interpreted.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_STRATEGY, StrategyConfig, get_settings
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.db.models import SettingRow, StrategyVersion

log = get_logger(__name__)

OVERRIDE_KEY = "strategy_overrides"

#: Sections whose edits change historical comparability.
VERSIONED_SECTIONS = frozenset({"weights", "buy_gate", "levels", "trailing", "sell", "probability"})

_cache: dict[str, Any] = {}


def _load_overrides(session: Session) -> dict:
    row = session.execute(
        select(SettingRow).where(SettingRow.key == OVERRIDE_KEY)
    ).scalar_one_or_none()
    return dict(row.value or {}) if row else {}


def effective_strategy(session: Session | None = None) -> StrategyConfig:
    """Defaults + persisted overrides. Falls back to defaults when no session is given."""
    base = StrategyConfig(version=get_settings().strategy_version)
    if session is None:
        cached = _cache.get("strategy")
        return cached if cached is not None else base
    overrides = _load_overrides(session)
    if not overrides:
        _cache["strategy"] = base
        return base
    try:
        merged = base.with_overrides(overrides)
    except (KeyError, ValueError) as exc:
        log.error("invalid_persisted_overrides", extra={"error": str(exc)})
        return base
    _cache["strategy"] = merged
    return merged


def describe_settings(cfg: StrategyConfig) -> dict:
    """Grouped, self-describing settings payload for the app's Settings screen."""
    defaults = DEFAULT_STRATEGY.model_dump()
    current = cfg.model_dump()

    def section(name: str, category: str) -> dict:
        return {
            "category": category,
            "versioned": name in VERSIONED_SECTIONS,
            "fields": {
                key: {
                    "value": value,
                    "default": defaults[name].get(key),
                    "type": type(value).__name__,
                }
                for key, value in current[name].items()
            },
        }

    return {
        "strategy_version": cfg.version,
        "description": cfg.description,
        "paper_trading": True,
        "sections": {
            "weights": section("weights", "scoring"),
            "universe": section("universe", "universe"),
            "buy_gate": section("buy_gate", "buy_gate"),
            "levels": section("levels", "buy_gate"),
            "trailing": section("trailing", "sell_engine"),
            "sell": section("sell", "sell_engine"),
            "probability": section("probability", "scoring"),
            "regime": section("regime", "scoring"),
            "portfolio": section("portfolio", "risk"),
            "costs": section("costs", "risk"),
        },
    }


def update_settings(
    session: Session,
    updates: dict,
    create_version: bool = False,
    new_version: str | None = None,
    updated_by: str | None = None,
) -> StrategyConfig:
    base = StrategyConfig(version=get_settings().strategy_version)
    existing = _load_overrides(session)
    merged_overrides = {**existing, **updates}

    try:
        candidate = base.with_overrides(merged_overrides)
    except KeyError as exc:
        raise ValidationError(f"unknown setting: {exc}") from exc
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    touches_versioned = _touches_versioned(base, updates)
    if touches_versioned and not create_version:
        raise ValidationError(
            "these parameters change how stocks are judged, so editing them in place would "
            "make historical alerts incomparable with new ones. Re-send with "
            "create_version=true to publish them as a new strategy version.",
            {"fields": sorted(updates), "current_version": base.version},
        )

    if create_version:
        version = new_version or _bump(base.version)
        candidate = candidate.model_copy(update={"version": version})
        session.add(
            StrategyVersion(
                version=version,
                description=candidate.description,
                parameters=candidate.model_dump(),
                weights=candidate.weights.as_dict(),
                is_active=True,
                notes=f"created via settings update by {updated_by or 'api'}",
            )
        )
        for row in session.execute(select(StrategyVersion)).scalars():
            if row.version != version:
                row.is_active = False

    row = session.execute(
        select(SettingRow).where(SettingRow.key == OVERRIDE_KEY)
    ).scalar_one_or_none()
    if row is None:
        row = SettingRow(key=OVERRIDE_KEY, category="strategy", value={})
        session.add(row)
    row.value = merged_overrides
    row.updated_by = updated_by
    session.flush()

    _cache["strategy"] = candidate
    log.info("settings_updated", extra={"fields": sorted(updates), "version": candidate.version})
    return candidate


def _touches_versioned(base: StrategyConfig, updates: dict) -> bool:
    data = base.model_dump()
    for key, value in updates.items():
        if key in VERSIONED_SECTIONS and isinstance(value, dict):
            return True
        for section in VERSIONED_SECTIONS:
            if key in data[section]:
                return True
    return False


def _bump(version: str) -> str:
    """``momentum_breakout_v1.0.0`` → ``momentum_breakout_v1.1.0``."""
    if "_v" not in version:
        return f"{version}_v1.0.1"
    name, _, numbers = version.rpartition("_v")
    parts = numbers.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[1] = str(int(parts[1]) + 1)
        parts[2] = "0"
    except ValueError:
        return f"{version}.1"
    return f"{name}_v{'.'.join(parts)}"


def ensure_strategy_version(session: Session, cfg: StrategyConfig) -> StrategyVersion:
    row = session.execute(
        select(StrategyVersion).where(StrategyVersion.version == cfg.version)
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = StrategyVersion(
        version=cfg.version,
        description=cfg.description,
        parameters=cfg.model_dump(),
        weights=cfg.weights.as_dict(),
        is_active=True,
    )
    session.add(row)
    session.flush()
    return row
