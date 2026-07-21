from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, get_args, get_origin

from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError, field_validator

from stock_research.cli import app_home
from stock_research.db import create_engine_at
from stock_research.domain.enums import Horizon, Market
from stock_research.domain.models import Holding, StockConfig
from stock_research.repositories.reports import ReportRepository
from stock_research.repositories.stocks import DuplicateStockError, StockRepository
from stock_research.services.report_store import ReportStore


@dataclass(frozen=True)
class ServiceContainer:
    """Persistence dependencies used by the read-only report and configuration UI."""

    stocks: StockRepository
    reports: ReportRepository


class StockForm(BaseModel):
    symbol: str
    name: str
    market: str
    industry: str | None = None
    quantity: str | None = None
    cost_basis: str | None = None
    cash_available: str | None = None
    risk_profile: str | None = None

    @field_validator("symbol", "name", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "industry",
        "quantity",
        "cost_basis",
        "cash_available",
        "risk_profile",
        mode="before",
    )
    @classmethod
    def blank_optional_value_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    def to_stock(self) -> StockConfig:
        holding_values = {
            "quantity": self.quantity,
            "cost_basis": self.cost_basis,
            "cash_available": self.cash_available,
            "risk_profile": self.risk_profile,
        }
        holding = None
        if any(value is not None for value in holding_values.values()):
            holding = Holding.model_validate(holding_values)
        return StockConfig.model_validate(
            {
                "symbol": self.symbol,
                "name": self.name,
                "market": self.market,
                "industry": self.industry,
                "holding": holding,
            }
        )


WEB_ROOT = Path(__file__).parent
TEMPLATE_DIRECTORY = WEB_ROOT / "templates"
STATIC_DIRECTORY = WEB_ROOT / "static"


def _risk_profile_choices() -> list[str]:
    annotation = Holding.model_fields["risk_profile"].annotation
    literal = next(
        (candidate for candidate in get_args(annotation) if get_origin(candidate) is Literal),
        None,
    )
    if literal is None:
        raise RuntimeError("Holding.risk_profile must expose literal choices")
    return list(get_args(literal))


def build_services(home: Path | None = None) -> ServiceContainer:
    root = (home or app_home()).resolve()
    stocks = StockRepository(create_engine_at(root / "data" / "stock_research.sqlite3"))
    reports = ReportRepository(create_engine_at(root / "reports" / "reports.sqlite3"))
    return ServiceContainer(stocks=stocks, reports=reports)


def create_app(services: ServiceContainer | None = None) -> FastAPI:
    app = FastAPI(title="Stock Research")
    app.state.services = services or build_services()
    app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
    templates = Jinja2Templates(directory=TEMPLATE_DIRECTORY)
    templates.env.globals.update(
        recommendation_for=ReportStore._recommendation_for,
        structured_fields=ReportStore._structured_fields,
    )
    app.include_router(_dashboard_router(app.state.services, templates))
    app.include_router(_report_router(app.state.services, templates))
    app.include_router(_stock_router(app.state.services, templates))
    return app


def _dashboard_router(services: ServiceContainer, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "report": services.reports.latest(),
                "report_dates": services.reports.list_dates(),
                "short_horizon": Horizon.SHORT,
            },
        )

    return router


def _report_router(services: ServiceContainer, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/reports/{report_date}", response_class=HTMLResponse)
    def report_detail(request: Request, report_date: date) -> HTMLResponse:
        report = services.reports.get(report_date)
        if report is None:
            raise HTTPException(status_code=404, detail="未找到该日期的研究报告。")
        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context={"report": report, "standalone": False},
        )

    return router


def _stock_router(services: ServiceContainer, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/stocks", response_class=HTMLResponse)
    def stock_list(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="stocks.html",
            context={"stocks": services.stocks.list_all()},
        )

    @router.post("/stocks")
    async def stock_create_from_list(request: Request) -> HTMLResponse:
        return await _save_stock(request, services, templates, create_only=True)

    @router.get("/stocks/new", response_class=HTMLResponse)
    def stock_new(request: Request) -> HTMLResponse:
        return _stock_form_response(request, templates)

    @router.post("/stocks/new")
    async def stock_create(request: Request) -> HTMLResponse:
        return await _save_stock(request, services, templates, create_only=True)

    @router.get("/stocks/{symbol}/edit", response_class=HTMLResponse)
    def stock_edit(request: Request, symbol: str) -> HTMLResponse:
        stock = services.stocks.get(symbol)
        if stock is None:
            raise HTTPException(status_code=404, detail="未找到该股票配置。")
        return _stock_form_response(
            request,
            templates,
            values=_stock_form_values(stock),
            editing_symbol=symbol,
        )

    @router.post("/stocks/{symbol}/edit")
    async def stock_update(request: Request, symbol: str) -> HTMLResponse:
        if services.stocks.get(symbol) is None:
            raise HTTPException(status_code=404, detail="未找到该股票配置。")
        return await _save_stock(request, services, templates, editing_symbol=symbol)

    @router.post("/stocks/{symbol}/delete")
    def stock_delete(symbol: str) -> RedirectResponse:
        if not services.stocks.delete(symbol):
            raise HTTPException(status_code=404, detail="未找到该股票配置。")
        return RedirectResponse("/stocks", status_code=status.HTTP_303_SEE_OTHER)

    return router


async def _save_stock(
    request: Request,
    services: ServiceContainer,
    templates: Jinja2Templates,
    editing_symbol: str | None = None,
    create_only: bool = False,
) -> HTMLResponse:
    submitted = {key: str(value) for key, value in (await request.form()).items()}
    if editing_symbol is not None and submitted.get("symbol") != editing_symbol:
        return _stock_form_response(
            request,
            templates,
            values=submitted,
            errors={"symbol": "股票代码：必须与地址中的股票代码一致。"},
            editing_symbol=editing_symbol,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    try:
        stock = StockForm.model_validate(submitted).to_stock()
    except ValidationError as error:
        return _stock_form_response(
            request,
            templates,
            values=submitted,
            errors=_localized_errors(error),
            editing_symbol=editing_symbol,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    try:
        if create_only:
            services.stocks.create(stock)
        else:
            services.stocks.upsert(stock)
    except DuplicateStockError:
        return _stock_form_response(
            request,
            templates,
            values=submitted,
            errors={"symbol": "股票代码：该股票代码已存在。"},
            editing_symbol=editing_symbol,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return RedirectResponse("/stocks", status_code=status.HTTP_303_SEE_OTHER)


def _stock_form_response(
    request: Request,
    templates: Jinja2Templates,
    *,
    values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
    editing_symbol: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="stock_form.html",
        context={
            "values": values or {},
            "errors": errors or {},
            "editing_symbol": editing_symbol,
            "form_action": (f"/stocks/{editing_symbol}/edit" if editing_symbol else "/stocks/new"),
            "markets": list(Market),
            "risk_profiles": _risk_profile_choices(),
        },
        status_code=status_code,
    )


def _stock_form_values(stock: StockConfig) -> dict[str, str]:
    holding = stock.holding
    return {
        "symbol": stock.symbol,
        "name": stock.name,
        "market": stock.market.value,
        "industry": stock.industry or "",
        "quantity": str(holding.quantity) if holding else "",
        "cost_basis": str(holding.cost_basis) if holding else "",
        "cash_available": (
            str(holding.cash_available) if holding and holding.cash_available is not None else ""
        ),
        "risk_profile": holding.risk_profile if holding and holding.risk_profile else "",
    }


def _localized_errors(error: ValidationError) -> dict[str, str]:
    labels = {
        "symbol": "股票代码",
        "name": "股票名称",
        "market": "市场",
        "industry": "行业",
        "quantity": "持仓数量",
        "cost_basis": "持仓成本",
        "cash_available": "可用资金",
        "risk_profile": "风险偏好",
    }
    messages = {
        "missing": "必填。",
        "decimal_parsing": "必须是有效数字。",
        "decimal_type": "必须是有效数字。",
        "greater_than": "必须大于 0。",
        "greater_than_equal": "不能小于 0。",
        "enum": "选项无效。",
        "literal_error": "选项无效。",
        "string_too_short": "不能为空。",
    }
    localized: dict[str, str] = {}
    for item in error.errors():
        location = str(item["loc"][-1]) if item["loc"] else "symbol"
        field = location if location in labels else "symbol"
        message = messages.get(str(item["type"]), "格式无效。")
        localized.setdefault(field, f"{labels[field]}：{message}")
    return localized
