"""The operator CLI — the difference between a deployed backend and a *configured* one.

``check`` is the command an operator runs when the app shows nothing, so its job is to
turn a silent misconfiguration into a specific sentence. These tests pin the cases that
must be reported as failures rather than warnings, and prove ``bootstrap`` stops at the
first broken step instead of running the rest against an empty database.
"""

from __future__ import annotations

import pytest

from app.cli import EXIT_FAILED, EXIT_OK, build_parser, cmd_bootstrap, cmd_check
from app.core.config import Settings


@pytest.fixture
def sqlite_engine(tmp_path):
    from app.data.providers.registry import set_provider
    from app.db.session import reset_engine

    reset_engine(f"sqlite:///{tmp_path/'cli.db'}")
    yield
    reset_engine()
    # cmd_check rebuilds the provider registry; clear it so it cannot leak into other tests.
    set_provider(None)


def settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        api_keys="a-real-looking-key",
        database_url="sqlite:///:memory:",
        market_data_provider="synthetic",
        enable_scheduler=True,
    )
    base.update(overrides)
    return Settings(**base)


def test_check_passes_on_a_working_synthetic_deployment(sqlite_engine, capsys):
    assert cmd_check(settings()) == EXIT_OK
    out = capsys.readouterr().out
    # Synthetic data is legal but must never pass silently as real market data.
    assert "synthetic" in out.lower()
    assert "WARN" in out


def test_check_fails_when_the_selected_provider_has_no_key(sqlite_engine, capsys):
    result = cmd_check(settings(market_data_provider="polygon", polygon_api_key=None))

    assert result == EXIT_FAILED
    assert "API key is unset" in capsys.readouterr().out


def test_check_fails_when_no_app_api_key_is_configured(sqlite_engine, capsys):
    # An empty API_KEYS is fail-closed at the API, so the app would be locked out.
    result = cmd_check(settings(api_keys=""))

    assert result == EXIT_FAILED
    assert "API_KEYS is empty" in capsys.readouterr().out


def test_check_warns_about_a_placeholder_key(sqlite_engine, capsys):
    result = cmd_check(settings(api_keys="dev-local-key"))

    assert result == EXIT_OK  # a warning, not a failure: local development is legitimate
    assert "placeholder" in capsys.readouterr().out


def test_check_warns_when_nothing_will_ever_scan(sqlite_engine, capsys):
    cmd_check(settings(enable_scheduler=False))
    assert "ENABLE_SCHEDULER=false" in capsys.readouterr().out


def test_check_never_prints_a_key(sqlite_engine, capsys, monkeypatch):
    from app.core.clock import utc_now
    from app.data.providers import registry
    from app.data.providers.base import ProviderHealth

    class StubRegistry:
        def health_all(self):
            return [ProviderHealth("polygon", True, "reachable", utc_now())]

    # The health probe would otherwise call the vendor for real.
    monkeypatch.setattr(registry, "get_provider", lambda *a, **k: StubRegistry())

    secret = "polygon-secret-value-1234"
    cmd_check(settings(market_data_provider="polygon", polygon_api_key=secret))

    out = capsys.readouterr().out
    assert secret not in out
    assert "ends …1234" in out  # enough to identify it, not enough to use it


def test_bootstrap_stops_at_the_first_failing_step(sqlite_engine, capsys):
    """A broken provider must not leave later steps running against an empty database."""
    result = cmd_bootstrap(settings(market_data_provider="polygon", polygon_api_key=None))

    out = capsys.readouterr().out
    assert result == EXIT_FAILED
    assert "bootstrap stopped at 'check'" in out
    assert "universe" not in out.split("bootstrap stopped")[1]


def test_bootstrap_runs_the_pipeline_in_dependency_order(sqlite_engine, capsys):
    assert cmd_bootstrap(settings()) == EXIT_OK

    out = capsys.readouterr().out
    order = [out.index(f"--- {step} ") for step in ("check", "init-db", "universe", "scan", "monitor")]
    assert order == sorted(order)
    assert "bootstrap complete" in out


def test_parser_exposes_every_documented_command():
    parser = build_parser()
    for command in ("check", "init-db", "universe", "scan", "monitor", "bootstrap"):
        assert parser.parse_args([command]).command == command
    assert parser.parse_args(["scan", "--tickers", "NVDA,AMD"]).tickers == "NVDA,AMD"
    assert parser.parse_args(["universe", "--max-symbols", "500"]).max_symbols == 500
