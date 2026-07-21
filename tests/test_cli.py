from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stock_research.cli import active_stock_context, app, build_services
from stock_research.domain.enums import RunStatus
from stock_research.domain.models import DailyReport
from stock_research.services.report_store import ReportStore

from test_report_builder import FakeMarketData


TEST_DATA_DIR = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_validate_input_prints_the_research_date() -> None:
    result = runner.invoke(
        app, ["validate-input", str(TEST_DATA_DIR / "daily_research_request.json")]
    )

    assert result.exit_code == 0
    assert "\u6bcf\u65e5\u7814\u7a76\u8bf7\u6c42\u6709\u6548" in result.stdout
    assert "2026-07-21" in result.stdout


def test_validate_input_rejects_an_invalid_outer_request(tmp_path: Path) -> None:
    invalid_request = tmp_path / "invalid-request.json"
    invalid_request.write_text('{"report_date": "2026-07-21"}', encoding="utf-8")

    result = runner.invoke(app, ["validate-input", str(invalid_request)])

    assert result.exit_code != 0


def test_generate_writes_three_formats_without_network_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    monkeypatch.setattr("stock_research.cli.AkShareMarketDataProvider", lambda: FakeMarketData())
    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0

    result = runner.invoke(
        app, ["generate", "--input", str(TEST_DATA_DIR / "daily_research_request.json")]
    )

    assert result.exit_code == 0
    assert "Markdown:" in result.stdout
    assert "HTML:" in result.stdout
    assert "JSON:" in result.stdout
    assert (tmp_path / "reports" / "2026-07-21" / "report.json").exists()
    assert (tmp_path / "reports" / "2026-07-21" / "report.md").exists()
    assert (tmp_path / "reports" / "2026-07-21" / "report.html").exists()


def test_generate_persists_the_report_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    monkeypatch.setattr("stock_research.cli.AkShareMarketDataProvider", lambda: FakeMarketData())
    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0
    original_save = ReportStore.save
    saves = 0

    def count_save(store: ReportStore, report):
        nonlocal saves
        saves += 1
        return original_save(store, report)

    monkeypatch.setattr(ReportStore, "save", count_save)

    result = runner.invoke(
        app, ["generate", "--input", str(TEST_DATA_DIR / "daily_research_request.json")]
    )

    assert result.exit_code == 0
    assert saves == 1


def test_init_does_not_overwrite_an_existing_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))

    first = runner.invoke(app, ["init"])
    configuration = tmp_path / "config" / "stocks.yaml"
    configuration.write_text("stocks: []\n", encoding="utf-8")
    second = runner.invoke(app, ["init"])

    assert first.exit_code == 0
    assert second.exit_code != 0
    assert configuration.read_text(encoding="utf-8") == "stocks: []\n"


def test_init_accepts_an_explicit_configuration_destination(tmp_path: Path) -> None:
    destination = tmp_path / "config" / "stocks.yaml"

    result = runner.invoke(app, ["init", str(destination)])

    assert result.exit_code == 0
    assert destination.read_text(encoding="utf-8").startswith("stocks:\n")


def test_import_config_replaces_the_stock_set_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    replacement = tmp_path / "replacement.yaml"
    replacement.write_text(
        "stocks:\n  - symbol: HK.00700\n    name: Tencent\n    market: hong_kong\n",
        encoding="utf-8",
    )

    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0
    result = runner.invoke(app, ["import-config", str(replacement)])

    assert result.exit_code == 0
    assert "1" in result.stdout
    listed = runner.invoke(app, ["reports"])
    assert listed.exit_code == 0

    assert [stock.symbol for stock in build_services().configuration.list_stocks()] == ["HK.00700"]


def test_active_stock_context_includes_industry_and_optional_holding_risk_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0

    context = active_stock_context()

    a_share = next(stock for stock in context if stock["symbol"] == "SH.600000")
    no_holding = next(stock for stock in context if stock["symbol"] == "SZ.000001")
    assert a_share["industry"]
    assert a_share["holding"]["risk_profile"] == "balanced"
    assert no_holding["industry"] is None
    assert no_holding["holding"] is None


def test_import_config_reports_malformed_yaml_without_replacing_prior_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("stocks: [\n", encoding="utf-8")

    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0
    result = runner.invoke(app, ["import-config", str(malformed)])

    assert result.exit_code != 0
    assert "configuration import failed" in result.stderr
    assert [stock.symbol for stock in build_services().configuration.list_stocks()] == [
        "SH.600000",
        "SZ.000001",
        "HK.00700",
    ]


def test_example_configuration_is_available_as_a_package_resource() -> None:
    resource = files("stock_research").joinpath("resources/stocks.example.yaml")

    assert resource.read_text(encoding="utf-8").startswith("stocks:\n")


def test_reports_prints_the_recorded_status_for_each_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    monkeypatch.setattr("stock_research.cli.AkShareMarketDataProvider", lambda: FakeMarketData())
    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0
    assert (
        runner.invoke(
            app, ["generate", "--input", str(TEST_DATA_DIR / "daily_research_request.json")]
        ).exit_code
        == 0
    )

    result = runner.invoke(app, ["reports"])

    assert result.exit_code == 0
    assert "2026-07-21" in result.stdout
    assert "success" in result.stdout


def test_report_displays_a_selected_saved_report_without_generating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    ReportStore(tmp_path / "reports").save(
        DailyReport(
            report_date=date(2026, 7, 21),
            generated_at=datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
            run_status=RunStatus.SUCCESS,
            analyses=[],
        )
    )

    result = runner.invoke(app, ["report", "2026-07-21"])

    assert result.exit_code == 0
    assert '"report_date": "2026-07-21"' in result.stdout
    assert '"run_status": "success"' in result.stdout


def test_report_returns_not_found_for_a_missing_saved_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))

    result = runner.invoke(app, ["report", "2026-07-21"])

    assert result.exit_code == 1
    assert "report not found for 2026-07-21" in result.stdout
    assert not (tmp_path / "reports" / "reports.sqlite3").exists()


def test_help_exposes_only_the_safe_research_and_configuration_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "init",
        "import-config",
        "validate-input",
        "generate",
        "reports",
        "report",
        "serve",
    ):
        assert command in result.stdout
    for prohibited in ("buy", "sell", "broker", "order", "credential"):
        assert prohibited not in result.stdout.lower()
