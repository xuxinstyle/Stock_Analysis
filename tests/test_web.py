from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from stock_research.db import create_engine_at
from stock_research.repositories.reports import ReportRepository
from stock_research.repositories.stocks import StockRepository
from stock_research.services.report_store import ReportStore
from stock_research.web.app import ServiceContainer, StockForm, create_app

from test_report_store import make_complete_report


@pytest.fixture
def services(tmp_path: Path) -> ServiceContainer:
    return ServiceContainer(
        stocks=StockRepository(create_engine_at(tmp_path / "stocks.sqlite3")),
        reports=ReportRepository(create_engine_at(tmp_path / "reports.sqlite3")),
    )


@pytest.fixture
def client(services: ServiceContainer) -> TestClient:
    with TestClient(create_app(services)) as test_client:
        yield test_client


def test_dashboard_shows_latest_report_summary(client: TestClient) -> None:
    report = make_complete_report().model_copy(
        update={"global_risks": ["全球风险样例"], "run_warnings": ["数据缺口样例"]}
    )
    client.app.state.services.reports.save(report)

    response = client.get("/")

    assert response.status_code == 200
    assert "每日股票研究" in response.text
    assert "2026-07-21" in response.text
    assert "SH.600000" in response.text
    assert "全球风险样例" in response.text
    assert "数据缺口样例" in response.text
    assert "short" in response.text
    assert 'href="/reports/2026-07-21#SH.600000"' in response.text


def test_report_page_preserves_report_facts_disclaimer_gaps_and_source_links(
    client: TestClient,
) -> None:
    report = make_complete_report()
    gap_report = report.model_copy(
        update={
            "run_warnings": ["仅使用截至收盘时可得的数据。"],
            "analyses": [
                report.analyses[0].model_copy(update={"data_gaps": ["公告尚未交叉验证。"]})
            ],
        }
    )
    client.app.state.services.reports.save(gap_report)

    response = client.get("/reports/2026-07-21")

    assert response.status_code == 200
    assert report.disclaimer in response.text
    assert "仅使用截至收盘时可得的数据。" in response.text
    assert "公告尚未交叉验证。" in response.text
    assert report.analyses[0].research is not None
    source = report.analyses[0].research.evidence[0]
    assert f'href="{source.url}"' in response.text
    assert source.title in response.text
    assert report.analyses[0].recommendations[0].rationale[0] in response.text


def test_missing_report_returns_404(client: TestClient) -> None:
    response = client.get("/reports/2026-07-20")

    assert response.status_code == 404
    assert "未找到" in response.text


def test_invalid_stock_form_returns_422_without_persisting(client: TestClient) -> None:
    response = client.post(
        "/stocks/new",
        data={"symbol": "600000", "name": "测试", "market": "a_share"},
    )

    assert response.status_code == 422
    assert "股票代码" in response.text
    assert client.app.state.services.stocks.list_all() == []


def test_create_stock_converts_blank_optional_holding_fields_to_none(
    client: TestClient,
) -> None:
    response = client.post(
        "/stocks",
        data={
            "symbol": "SH.600000",
            "name": "浦发银行",
            "market": "a_share",
            "industry": "",
            "quantity": "",
            "cost_basis": "",
            "cash_available": "",
            "risk_profile": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/stocks"
    saved = client.app.state.services.stocks.list_all()
    assert len(saved) == 1
    assert saved[0].industry is None
    assert saved[0].holding is None


def test_create_beijing_stock_persists_the_beijing_market(client: TestClient) -> None:
    response = client.post(
        "/stocks/new",
        data={"symbol": "BJ.920808", "name": "曙光数创", "market": "beijing"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    saved = client.app.state.services.stocks.list_all()
    assert [(stock.symbol, stock.market.value) for stock in saved] == [("BJ.920808", "beijing")]


@pytest.mark.parametrize("endpoint", ["/stocks", "/stocks/new"])
def test_create_stock_rejects_duplicate_without_overwriting_existing_row(
    client: TestClient, endpoint: str
) -> None:
    client.post(
        "/stocks/new",
        data={
            "symbol": "SH.600000",
            "name": "原始名称",
            "market": "a_share",
            "industry": "银行",
        },
    )

    response = client.post(
        endpoint,
        data={
            "symbol": "SH.600000",
            "name": "不应覆盖",
            "market": "a_share",
            "industry": "错误行业",
        },
    )

    assert response.status_code == 422
    assert "股票代码" in response.text
    assert "已存在" in response.text
    saved = client.app.state.services.stocks.list_all()
    assert len(saved) == 1
    assert saved[0].name == "原始名称"
    assert saved[0].industry == "银行"


def test_domain_models_are_the_canonical_market_holding_and_risk_validators() -> None:
    form = StockForm.model_validate(
        {
            "symbol": "SH.600000",
            "name": "测试",
            "market": "not_a_market",
            "quantity": "-1",
            "cost_basis": "10",
            "risk_profile": "not_a_profile",
        }
    )

    with pytest.raises(ValidationError):
        form.to_stock()


def test_edit_stock_persists_validated_holding_and_blank_holding_options(
    client: TestClient,
) -> None:
    client.post(
        "/stocks/new",
        data={"symbol": "HK.00700", "name": "腾讯控股", "market": "hong_kong"},
    )

    response = client.post(
        "/stocks/HK.00700/edit",
        data={
            "symbol": "HK.00700",
            "name": "腾讯控股",
            "market": "hong_kong",
            "industry": "互联网",
            "quantity": "10",
            "cost_basis": "300.50",
            "cash_available": "",
            "risk_profile": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    saved = client.app.state.services.stocks.list_all()[0]
    assert saved.industry == "互联网"
    assert saved.holding is not None
    assert str(saved.holding.cost_basis) == "300.50"
    assert saved.holding.cash_available is None
    assert saved.holding.risk_profile is None


def test_edit_rejects_a_symbol_different_from_the_path(client: TestClient) -> None:
    client.post(
        "/stocks/new",
        data={"symbol": "HK.00700", "name": "腾讯控股", "market": "hong_kong"},
    )

    response = client.post(
        "/stocks/HK.00700/edit",
        data={"symbol": "SH.600000", "name": "浦发银行", "market": "a_share"},
    )

    assert response.status_code == 422
    assert "必须与地址中的股票代码一致" in response.text
    assert [stock.symbol for stock in client.app.state.services.stocks.list_all()] == ["HK.00700"]


def test_delete_removes_only_the_exact_path_symbol(client: TestClient) -> None:
    for symbol, name, market in (
        ("SH.600000", "浦发银行", "a_share"),
        ("HK.00700", "腾讯控股", "hong_kong"),
    ):
        client.post(
            "/stocks/new",
            data={"symbol": symbol, "name": name, "market": market},
        )

    response = client.post("/stocks/HK.00700/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/stocks"
    assert [stock.symbol for stock in client.app.state.services.stocks.list_all()] == ["SH.600000"]


def test_stock_list_and_forms_are_server_rendered(client: TestClient) -> None:
    assert client.get("/stocks").status_code == 200
    assert client.get("/stocks/new").status_code == 200
    assert "股票配置" in client.get("/stocks").text
    assert client.get("/stocks/SH.600000/edit").status_code == 404


def test_app_starts_without_fetching_data_when_repositories_are_empty(
    services: ServiceContainer,
) -> None:
    app = create_app(services)

    assert app.state.services.reports.latest() is None
    assert app.state.services.stocks.list_all() == []
    assert date(2026, 7, 21) not in app.state.services.reports.list_dates()


def test_report_rendering_is_standalone_safe_for_artifacts_and_live_for_web(
    client: TestClient, tmp_path: Path
) -> None:
    report = make_complete_report()
    client.app.state.services.reports.save(report)

    live_html = client.get(f"/reports/{report.report_date}").text
    artifact_html = ReportStore(tmp_path).save(report).html.read_text(encoding="utf-8")

    assert 'href="/static/app.css"' in live_html
    assert 'href="/"' in live_html
    assert 'href="/static/app.css"' not in artifact_html
    assert 'href="/"' not in artifact_html
    assert "<style>" in artifact_html
