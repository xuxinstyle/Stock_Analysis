from datetime import date

from stock_research.domain.models import DailyRunRequest, MarketOutlook
from stock_research.services.report_builder import ReportBuilder

from test_report_builder import FakeMarketData, make_request, make_research, make_stock


def test_builder_preserves_market_outlook_for_report_rendering() -> None:
    outlook = MarketOutlook(
        data_as_of=date(2026, 7, 21),
        current_analysis="沪深市场在成交放大后震荡，需同时观察港股与隔夜海外风险传导。",
        upside_conditions=["指数站稳关键均线且成交额持续放大。"],
        downside_conditions=["指数跌破关键支撑且北向与行业资金流出扩大。"],
        watch_items=["成交额、市场广度、海外风险资产与重要政策信息。"],
    )
    request_payload = make_request(make_research()).model_dump(mode="json")
    request_payload["market_outlook"] = outlook.model_dump(mode="json")
    request = DailyRunRequest.model_validate(request_payload)

    report = ReportBuilder().build(request, [make_stock()], FakeMarketData())

    assert report.market_outlook == outlook
