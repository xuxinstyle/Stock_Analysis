import json
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

import stock_research.cli as cli
from stock_research.cli import active_stock_context, app, build_services
from stock_research.db import create_engine_at
from stock_research.domain.enums import Market, RunStatus
from stock_research.domain.models import DailyReport, DailyRunRequest, StockConfig
from stock_research.repositories.stocks import StockRepository
from stock_research.services.feishu_notifications import FeishuNotificationError
from stock_research.services.report_store import ReportStore

from test_report_builder import FakeMarketData


TEST_DATA_DIR = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def suppress_feishu_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_notify_generated_report", lambda paths, report_date: 1)


def test_validate_input_prints_the_research_date() -> None:
    result = runner.invoke(
        app, ["validate-input", str(TEST_DATA_DIR / "daily_research_request.json")]
    )

    assert result.exit_code == 0
    assert "\u6bcf\u65e5\u7814\u7a76\u8bf7\u6c42\u6709\u6548" in result.stdout
    assert "2026-07-21" in result.stdout


def test_daily_request_fixture_declares_open_market_session_metadata() -> None:
    request = DailyRunRequest.model_validate_json(
        (TEST_DATA_DIR / "daily_research_request.json").read_text(encoding="utf-8")
    )

    assert {
        (session.market.value, session.completed_session, session.is_closed)
        for session in request.market_sessions
    } == {
        ("a_share", date(2026, 7, 20), False),
        ("hong_kong", date(2026, 7, 20), False),
    }


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


def test_generate_saves_report_then_notifies_for_manual_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    monkeypatch.setattr("stock_research.cli.AkShareMarketDataProvider", lambda: FakeMarketData())
    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0
    sent_markdown: list[str] = []

    def notify(paths, report_date: date) -> int:
        assert report_date == date(2026, 7, 21)
        sent_markdown.append(paths.markdown.read_text(encoding="utf-8"))
        return 1

    monkeypatch.setattr(cli, "_notify_generated_report", notify, raising=False)

    result = runner.invoke(
        app, ["generate", "--input", str(TEST_DATA_DIR / "daily_research_request.json")]
    )

    assert result.exit_code == 0
    assert sent_markdown == [
        (tmp_path / "reports" / "2026-07-21" / "report.md").read_text(encoding="utf-8")
    ]
    assert "Feishu: 1 segment(s) sent" in result.stdout


def test_generate_notifies_from_post_market_report_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    monkeypatch.setattr("stock_research.cli.AkShareMarketDataProvider", lambda: FakeMarketData())
    payload = json.loads(
        (TEST_DATA_DIR / "daily_research_request.json").read_text(encoding="utf-8")
    )
    payload["run_slot"] = "post_market"
    request_path = tmp_path / "post-market-request.json"
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0
    notified_paths = []

    def notify(paths, report_date: date) -> int:
        assert report_date == date(2026, 7, 21)
        notified_paths.append(paths)
        assert paths.markdown.read_text(encoding="utf-8")
        return 1

    monkeypatch.setattr(cli, "_notify_generated_report", notify, raising=False)

    result = runner.invoke(app, ["generate", "--input", str(request_path)])

    assert result.exit_code == 0
    assert (
        notified_paths[0].markdown
        == tmp_path / "reports" / "2026-07-21" / "post-market" / "report.md"
    )
    assert "post-market" in result.stdout


def test_generate_keeps_saved_report_when_feishu_notification_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    monkeypatch.setattr("stock_research.cli.AkShareMarketDataProvider", lambda: FakeMarketData())
    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0

    def fail_notification(paths, report_date: date) -> int:
        raise FeishuNotificationError("STOCK_RESEARCH_FEISHU_WEBHOOK_URL must be configured")

    monkeypatch.setattr(cli, "_notify_generated_report", fail_notification, raising=False)

    result = runner.invoke(
        app, ["generate", "--input", str(TEST_DATA_DIR / "daily_research_request.json")]
    )

    assert result.exit_code == 1
    assert (tmp_path / "reports" / "2026-07-21" / "report.md").exists()
    assert "notification failed" in result.stderr
    assert "STOCK_RESEARCH_FEISHU_WEBHOOK_URL" in result.stderr


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


def test_generate_uses_request_market_sessions_for_divergent_closed_markets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    monkeypatch.setattr(
        "stock_research.cli.AkShareMarketDataProvider",
        lambda: FakeMarketData(
            bars_ends={
                "SH.600000": date(2026, 7, 17),
                "SZ.000001": date(2026, 7, 17),
                "HK.00700": date(2026, 7, 20),
            }
        ),
    )
    payload = json.loads(
        (TEST_DATA_DIR / "daily_research_request.json").read_text(encoding="utf-8")
    )
    payload["market_sessions"] = [
        {"market": "a_share", "completed_session": "2026-07-17", "is_closed": True},
        {"market": "hong_kong", "completed_session": "2026-07-20", "is_closed": False},
    ]
    for research in payload["research_inputs"]:
        if research["symbol"].startswith(("SH.", "SZ.")):
            research["data_as_of"] = "2026-07-17"
            for event in research["events"]:
                event["occurred_at"] = "2026-07-17T16:00:00+08:00"
            for source in research["evidence"]:
                source["published_at"] = "2026-07-17T16:00:00+08:00"
    request_path = tmp_path / "divergent-market-sessions.json"
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0

    result = runner.invoke(app, ["generate", "--input", str(request_path)])

    report = ReportStore(tmp_path / "reports").load(date(2026, 7, 21))
    assert result.exit_code == 0
    assert report is not None
    assert report.run_status is RunStatus.SUCCESS
    statuses = {status.market.value: status for status in report.market_statuses}
    assert statuses["a_share"].status == "closed"
    assert statuses["a_share"].data_as_of == date(2026, 7, 17)
    assert statuses["hong_kong"].status == "available"
    assert statuses["hong_kong"].data_as_of == date(2026, 7, 20)
    json_report = (tmp_path / "reports" / "2026-07-21" / "report.json").read_text(encoding="utf-8")
    rendered_reports = [
        (tmp_path / "reports" / "2026-07-21" / filename).read_text(encoding="utf-8")
        for filename in ("report.md", "report.html")
    ]
    assert "closed" in json_report
    assert all("休市" in content for content in rendered_reports)


def test_daily_request_rejects_duplicate_market_session_metadata() -> None:
    payload = json.loads(
        (TEST_DATA_DIR / "daily_research_request.json").read_text(encoding="utf-8")
    )
    payload["market_sessions"] = [
        {"market": "a_share", "completed_session": "2026-07-20", "is_closed": False},
        {"market": "a_share", "completed_session": "2026-07-20", "is_closed": False},
    ]

    with pytest.raises(ValidationError, match="market session"):
        DailyRunRequest.model_validate(payload)


def test_daily_request_accepts_beijing_market_session_metadata() -> None:
    request = DailyRunRequest.model_validate(
        {
            "report_date": "2026-07-21",
            "generated_at": "2026-07-21T09:00:00+08:00",
            "research_inputs": [],
            "market_sessions": [
                {"market": "beijing", "completed_session": "2026-07-20", "is_closed": False}
            ],
        }
    )

    assert request.market_sessions[0].market is Market.BEIJING


def test_post_market_request_accepts_same_day_completed_session() -> None:
    request = DailyRunRequest.model_validate(
        {
            "report_date": "2026-07-22",
            "run_slot": "post_market",
            "generated_at": "2026-07-22T23:00:00+08:00",
            "research_inputs": [],
            "market_sessions": [
                {"market": "a_share", "completed_session": "2026-07-22", "is_closed": False}
            ],
        }
    )

    assert request.market_sessions[0].completed_session == request.report_date


def test_post_market_request_rejects_same_day_closed_session() -> None:
    payload = {
        "report_date": "2026-07-22",
        "run_slot": "post_market",
        "generated_at": "2026-07-22T23:00:00+08:00",
        "research_inputs": [],
        "market_sessions": [
            {"market": "a_share", "completed_session": "2026-07-22", "is_closed": True}
        ],
    }

    with pytest.raises(ValidationError, match="休市市场交易日"):
        DailyRunRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("completed_session", "is_closed"),
    [
        ("2026-07-21", False),
        ("2026-07-22", True),
    ],
)
def test_daily_request_rejects_non_prior_market_session_metadata(
    completed_session: str, is_closed: bool
) -> None:
    payload = json.loads(
        (TEST_DATA_DIR / "daily_research_request.json").read_text(encoding="utf-8")
    )
    payload["market_sessions"] = [
        {
            "market": "a_share",
            "completed_session": completed_session,
            "is_closed": is_closed,
        }
    ]

    with pytest.raises(ValidationError, match="completed_session must precede report_date"):
        DailyRunRequest.model_validate(payload)


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
    assert a_share["product_price_focus"] == ["氦气"]
    assert a_share["holding"]["risk_profile"] == "balanced"
    assert no_holding["industry"] is None
    assert no_holding["holding"] is None


def test_active_stock_context_reads_existing_configuration_without_creating_artifacts(
    tmp_path: Path,
) -> None:
    home = tmp_path / "existing-app-home"
    repository = StockRepository(create_engine_at(home / "data" / "stock_research.sqlite3"))
    repository.create(
        StockConfig(
            symbol="SH.600000",
            name="Example A Share",
            market=Market.A_SHARE,
            industry="Banking",
        )
    )
    before = {path.relative_to(home) for path in home.rglob("*")}

    context = active_stock_context(home)

    assert context == [
        {
            "symbol": "SH.600000",
            "name": "Example A Share",
            "market": "a_share",
            "industry": "Banking",
            "product_price_focus": [],
            "holding": None,
        }
    ]
    assert {path.relative_to(home) for path in home.rglob("*")} == before
    assert not (home / "reports").exists()
    assert not (home / "data" / "runs.sqlite3").exists()


def test_active_stock_context_reads_legacy_configuration_without_migrating_it(
    tmp_path: Path,
) -> None:
    home = tmp_path / "legacy-app-home"
    engine = create_engine_at(home / "data" / "stock_research.sqlite3")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE stocks (symbol VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, "
            "market VARCHAR NOT NULL, industry VARCHAR, holding TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO stocks (symbol, name, market, industry, holding) VALUES "
            "('SH.688268', '华特气体', 'a_share', '电子特种气体', NULL)"
        )

    context = active_stock_context(home)

    assert context == [
        {
            "symbol": "SH.688268",
            "name": "华特气体",
            "market": "a_share",
            "industry": "电子特种气体",
            "product_price_focus": [],
            "holding": None,
        }
    ]
    with engine.connect() as connection:
        column_names = {
            row["name"]
            for row in connection.exec_driver_sql("PRAGMA table_info(stocks)").mappings().all()
        }
    assert "product_price_focus" not in column_names


@pytest.mark.parametrize("create_empty_home", [False, True])
def test_active_stock_context_blocks_empty_configuration_without_creating_artifacts(
    tmp_path: Path, create_empty_home: bool
) -> None:
    home = tmp_path / "empty-app-home"
    if create_empty_home:
        home.mkdir()

    with pytest.raises(RuntimeError, match="no persisted configuration database"):
        active_stock_context(home)

    assert home.exists() is create_empty_home
    if create_empty_home:
        assert not list(home.iterdir())


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


def test_report_reads_a_post_market_report_without_creating_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    report_root = tmp_path / "reports"
    slot_directory = report_root / "2026-07-21" / "post-market"
    slot_directory.mkdir(parents=True)
    (slot_directory / "report.json").write_text(
        DailyReport(
            report_date=date(2026, 7, 21),
            run_slot="post_market",
            generated_at=datetime(2026, 7, 21, 15, 0, tzinfo=UTC),
            run_status=RunStatus.SUCCESS,
            analyses=[],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    files_before = {
        path.relative_to(report_root) for path in report_root.rglob("*") if path.is_file()
    }

    result = runner.invoke(app, ["report", "2026-07-21"])

    assert result.exit_code == 0
    assert '"run_slot": "post_market"' in result.stdout
    assert files_before == {
        path.relative_to(report_root) for path in report_root.rglob("*") if path.is_file()
    }
    assert not (report_root / "reports.sqlite3").exists()


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
