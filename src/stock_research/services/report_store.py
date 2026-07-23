from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from stock_research.db import create_engine_at
from stock_research.domain.enums import EvidenceCategory, Horizon
from stock_research.domain.models import (
    DATA_GAP_RATIONALE_PREFIX,
    LEGACY_DATA_GAP_RATIONALE_PREFIX,
    DailyReport,
    Evidence,
    Recommendation,
    StockAnalysis,
)
from stock_research.repositories.reports import ReportRepository


_FIELD_LABELS = {
    "report_date": "报告日期",
    "generated_at": "生成时间",
    "run_status": "运行状态",
    "market_statuses": "市场状态",
    "market_outlook": "大盘分析与后续展望",
    "current_analysis": "当前大盘分析",
    "upside_conditions": "上行情景条件",
    "downside_conditions": "下行情景条件",
    "watch_items": "后续观察项",
    "global_risks": "全局风险",
    "run_warnings": "运行警告",
    "analyses": "个股分析",
    "disclaimer": "免责声明",
    "symbol": "股票代码",
    "name": "股票名称",
    "market": "市场",
    "industry": "所属行业",
    "product_price_focus": "产品价格关注项",
    "holding": "持仓",
    "quantity": "持仓数量",
    "cost_basis": "持仓成本",
    "cash_available": "可用资金",
    "risk_profile": "风险偏好",
    "data_as_of": "数据截至",
    "latest_close": "最新收盘价",
    "sma_5": "5 日均线",
    "sma_20": "20 日均线",
    "sma_60": "60 日均线",
    "rsi_14": "RSI(14)",
    "macd": "MACD",
    "macd_signal": "MACD 信号线",
    "macd_histogram": "MACD 柱状图",
    "bollinger_lower": "布林带下轨",
    "bollinger_middle": "布林带中轨",
    "bollinger_upper": "布林带上轨",
    "realized_volatility_20": "20 日已实现波动率",
    "volume_ratio": "量比",
    "volume_ratio_20": "20 日量比",
    "trend": "趋势",
    "support": "支撑位",
    "resistance": "阻力位",
    "support_20": "20 日支撑位",
    "resistance_20": "20 日阻力位",
    "title": "标题",
    "occurred_at": "发生时间",
    "direction": "方向",
    "summary": "摘要",
    "symbols": "关联股票",
    "scope": "事件范围",
    "is_confirmed": "已确认",
    "citation_title": "引用标题",
    "citation_url": "引用链接",
    "url": "链接",
    "source_name": "来源名称",
    "published_at": "发布时间",
    "retrieved_at": "获取时间",
    "category": "证据类型",
    "credibility": "可信度",
    "horizon": "建议周期",
    "action": "操作",
    "confidence": "置信度",
    "risk_level": "风险等级",
    "rationale": "依据",
    "trigger": "触发条件",
    "observation_or_target": "观察/目标",
    "invalidation": "失效条件",
    "position_limit": "仓位上限",
    "holding_impact": "持仓影响",
    "evidence_titles": "依据标题",
    "citation_urls": "引用链接",
    "close": "收盘价",
    "previous_close": "前收盘价",
    "change": "涨跌额",
    "change_percent": "涨跌幅",
    "volume": "成交量",
    "previous_volume": "前一日成交量",
    "volume_change_percent": "成交量变化",
    "reason": "归因说明",
    "status": "状态",
    "message": "说明",
    "fundamental_summary": "基本面摘要",
    "industry_summary": "行业摘要",
    "policy_summary": "政策摘要",
    "news_summary": "消息摘要",
    "international_summary": "国际传导摘要",
    "product_price_summary": "产品价格摘要",
    "recent_price_move_summary": "近期股价涨跌原因",
    "events": "突发事件",
    "evidence": "证据",
}

_DISPLAY_VALUES = {
    "a_share": "A股",
    "beijing": "北交所",
    "hong_kong": "港股",
    "up": "上行",
    "down": "下行",
    "neutral": "中性",
    "short": "短线",
    "long": "长线",
    "watch": "观望",
    "buy_in_tranches": "分批买入",
    "hold": "持有",
    "reduce": "减持",
    "avoid": "回避",
    "low": "低",
    "high": "高",
    "success": "成功",
    "partial": "部分完成",
    "failed": "失败",
    "positive": "利好",
    "negative": "利空",
    "local": "本地",
    "international": "国际",
    "company": "公司",
    "industry": "行业",
    "policy": "政策",
    "news": "新闻",
    "product_price": "产品价格",
    "available": "可用",
    "closed": "休市",
    "unavailable": "不可用",
    "conservative": "保守型",
    "balanced": "均衡型",
    "aggressive": "进取型",
    "1": "低",
    "2": "二级",
    "3": "一级",
}

_FIELD_DISPLAY_VALUES = {
    "horizon": {"medium": "中线"},
    "risk_level": {"medium": "中等"},
    "confidence": {"medium": "中等"},
}

_ENUM_DISPLAY_FIELDS = {
    "market",
    "trend",
    "horizon",
    "action",
    "risk_level",
    "confidence",
    "run_status",
    "direction",
    "scope",
    "category",
    "credibility",
    "status",
    "risk_profile",
}

_LEGACY_SYSTEM_TEXT = {
    (
        "Research-only report; not personalized investment advice, a return guarantee, "
        "or an instruction to trade."
    ): "本报告仅供研究参考，不构成个性化投资建议、收益保证或交易指令。",
    "Completed session data is current for all configured stocks.": (
        "所有已配置股票的已完成交易日数据均为最新。"
    ),
    "Completed session data is current for only part of this market.": (
        "仅部分已配置股票的已完成交易日数据为最新。"
    ),
    "Completed session data is unavailable or stale for configured stocks.": (
        "已配置股票的已完成交易日数据不可用或已过期。"
    ),
    "Trigger: obtain and validate the missing local data before reassessment.": (
        "触发条件：补齐并核验缺失的本地数据后再评估。"
    ),
    "Observation only: no price target is produced for incomplete data.": (
        "仅观察：数据不完整时不提供价格目标。"
    ),
    "Invalidation: the missing data remains unavailable or cannot be verified.": (
        "失效条件：缺失数据仍不可获得或无法核验。"
    ),
}
_LEGACY_SYSTEM_TEXT_FIELDS = {
    "disclaimer",
    "message",
    "trigger",
    "observation_or_target",
    "invalidation",
}
_LEGACY_PRICE_DATA_FIELDS = {"data_gaps", "reason", "rationale", "run_warnings"}
_PUBLIC_EVIDENCE_CATEGORIES = {
    EvidenceCategory.POLICY,
    EvidenceCategory.INTERNATIONAL,
}
_LEGACY_CLOSED_STATUS = re.compile(
    r"Market was closed on report date (\d{4}-\d{2}-\d{2}); prior completed session "
    r"data is current for all configured stocks\."
)
_LEGACY_SYMBOL_PREFIX = re.compile(r"(?P<symbol>[A-Z]{2}\.\d{5,6}):")


@dataclass(frozen=True)
class ReportPaths:
    json: Path
    markdown: Path
    html: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "json": str(self.json),
            "markdown": str(self.markdown),
            "html": str(self.html),
        }


class ReportStore:
    def __init__(
        self,
        root: Path,
        repository: ReportRepository | None = None,
        template_directory: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.repository = repository or ReportRepository(
            create_engine_at(self.root / "reports.sqlite3")
        )
        templates = template_directory or Path(__file__).parents[1] / "web" / "templates"
        self._environment = Environment(
            loader=FileSystemLoader(templates),
            autoescape=select_autoescape(("html", "xml")),
        )

    def save(self, report: DailyReport) -> ReportPaths:
        paths = self.paths_for(report.report_date, report.run_slot)
        paths.json.parent.mkdir(parents=True, exist_ok=True)
        payloads = {
            paths.json: json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            paths.markdown: self._render_markdown(report),
            paths.html: self._render_html(report),
        }
        for path, content in payloads.items():
            self._atomic_write(path, content)
        self.repository.save(report)
        return paths

    def paths_for(
        self,
        report_date: date,
        run_slot: Literal["pre_market", "post_market"] | None = None,
    ) -> ReportPaths:
        destination = self.root / report_date.isoformat()
        slot_directories = {
            "pre_market": "pre-market",
            "post_market": "post-market",
        }
        if run_slot not in (None, *slot_directories):
            raise ValueError("运行时段仅可为 pre_market 或 post_market")
        if run_slot is not None:
            destination /= slot_directories[run_slot]
        return ReportPaths(
            json=destination / "report.json",
            markdown=destination / "report.md",
            html=destination / "report.html",
        )

    def load_latest(self) -> DailyReport | None:
        return self.repository.latest()

    def load(self, report_date: date) -> DailyReport | None:
        return self.repository.get(report_date)

    @staticmethod
    def load_read_only(root: Path, report_date: date) -> DailyReport | None:
        date_directory = Path(root) / report_date.isoformat()
        for directory in ("post-market", "pre-market", None):
            path = date_directory / "report.json"
            if directory is not None:
                path = date_directory / directory / "report.json"
            try:
                return DailyReport.model_validate_json(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
        return None

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _render_html(self, report: DailyReport) -> str:
        template = self._environment.get_template("report.html")
        return template.render(
            report=report,
            public_evidence_for=self._public_evidence,
            recommendation_for=self._recommendation_for,
            recommendation_summary=self._recommendation_summary,
            recommendation_overview=self._recommendation_overview,
            stock_configuration_summary=self._stock_configuration_summary,
            previous_day_summary=self._previous_day_summary,
            previous_day_metrics=self._previous_day_metrics,
            technical_summary=self._technical_summary,
            evidence_summary=self._evidence_summary,
            stock_evidence_for=self._stock_evidence_for_report,
            has_stock_international_evidence_for=self._has_stock_international_evidence_for_report,
            brief_text=self._brief_text,
            structured_fields=self._structured_fields,
            display_field=self._display_field,
            display_value=self._display_value,
            standalone=True,
        )

    @staticmethod
    def _render_markdown(report: DailyReport) -> str:
        public_evidence_urls = ReportStore._public_evidence_urls(report.analyses)
        sections = [
            "\n".join(ReportStore._markdown_overview(report)),
            *(
                "\n".join(ReportStore._markdown_analysis(analysis, public_evidence_urls))
                for analysis in report.analyses
            ),
            "\n".join(ReportStore._markdown_recommendation_summary(report.analyses)),
        ]
        return "\n".join(sections) + "\n"

    @staticmethod
    def notification_sections(report: DailyReport) -> list[tuple[str, str]]:
        """Render Feishu sections from trusted report structure, never from research Markdown."""

        title = "每日股票研究报告"
        public_evidence_urls = ReportStore._public_evidence_urls(report.analyses)
        return [
            (
                f"{title} — 市场概览",
                ReportStore._section_text(ReportStore._markdown_overview(report)),
            ),
            *[
                (
                    f"{title} — {analysis.stock.symbol} {analysis.stock.name}",
                    ReportStore._section_text(
                        ReportStore._markdown_analysis(analysis, public_evidence_urls)
                    ),
                )
                for analysis in report.analyses
            ],
            (
                f"{title} — 全部标的操作汇总",
                ReportStore._section_text(
                    ReportStore._markdown_recommendation_summary(report.analyses)
                ),
            ),
        ]

    @staticmethod
    def _section_text(lines: list[str]) -> str:
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _markdown_overview(report: DailyReport) -> list[str]:
        lines = [
            f"# 每日股票研究报告 — {report.report_date.isoformat()}",
            "",
            f"- {ReportStore._display_field('generated_at')}：{report.generated_at.isoformat()}",
            f"- {ReportStore._display_field('run_status')}："
            f"{ReportStore._display_value(report.run_status.value, 'run_status')}",
            f"- {ReportStore._display_field('disclaimer')}："
            f"{ReportStore._display_value(report.disclaimer, 'disclaimer')}",
            "",
            "## 市场状态",
        ]
        if report.market_statuses:
            for status in report.market_statuses:
                data_as_of = ReportStore._display_value(status.data_as_of)
                lines.append(
                    f"- {ReportStore._display_value(status.market.value, 'market')}："
                    f"{ReportStore._display_value(status.status, 'status')}；"
                    f"{ReportStore._display_field('data_as_of')}：{data_as_of}；"
                    f"{ReportStore._display_value(status.message, 'message')}"
                )
        else:
            lines.append("- 无已配置市场。")
        lines.extend(
            [
                "",
                "## 大盘分析与后续展望",
                (
                    f"- 数据截至：{report.market_outlook.data_as_of.isoformat()}"
                    if report.market_outlook.data_as_of
                    else "- 数据截至：不可用"
                ),
                f"- 当前大盘分析：{ReportStore._brief_text(report.market_outlook.current_analysis, 180)}",
                "- 上行情景条件："
                + ReportStore._brief_text("；".join(report.market_outlook.upside_conditions), 160),
                "- 下行情景条件："
                + ReportStore._brief_text(
                    "；".join(report.market_outlook.downside_conditions), 160
                ),
                "- 后续观察项："
                + ReportStore._brief_text("；".join(report.market_outlook.watch_items), 160),
            ]
        )
        lines.extend(["", "## 全局风险"])
        lines.extend(
            f"- {ReportStore._brief_text(ReportStore._display_value(risk, 'global_risks'), 160)}"
            for risk in report.global_risks or ["无已提供全局风险摘要。"]
        )
        public_evidence = ReportStore._public_evidence(report.analyses)
        if public_evidence:
            lines.extend(["", "## 公共参考来源"])
            lines.extend(
                f"- [{evidence.title}]({evidence.url}) — {ReportStore._evidence_summary(evidence)}"
                for evidence in public_evidence
            )
        lines.extend(["", "## 运行警告"])
        lines.extend(
            f"- {ReportStore._display_value(warning, 'run_warnings')}"
            for warning in report.run_warnings or ["无。"]
        )

        return lines

    @staticmethod
    def _compact_markdown_analysis(
        analysis: StockAnalysis,
        public_evidence_urls: set[str] | frozenset[str] = frozenset(),
    ) -> list[str]:
        research = analysis.research
        lines = [
            "",
            f"# {analysis.stock.symbol} {analysis.stock.name}",
            "",
            "## 股票配置",
            f"- {ReportStore._stock_configuration_summary(analysis)}",
            (
                f"- 研究数据截至：{research.data_as_of.isoformat()}"
                if research
                else "- 研究数据截至：不可用"
            ),
            "",
            "## 价格表现与归因",
            f"- {ReportStore._previous_day_summary(analysis)}",
            (
                f"- 近期走势与驱动：{ReportStore._brief_text(research.recent_price_move_summary, 180)}"
                if research
                else "- 数据缺口：缺少研究输入，无法说明近期股价涨跌原因。"
            ),
            "",
            "## 基本面分析",
            (
                ReportStore._brief_text(research.fundamental_summary, 160)
                if research
                else "数据缺口：缺少研究输入。"
            ),
            "",
            "## 行业分析",
            (
                ReportStore._brief_text(research.industry_summary, 140)
                if research
                else "数据缺口：缺少研究输入。"
            ),
        ]
        if research and analysis.stock.product_price_focus:
            lines.extend(
                [
                    f"产品价格：{ReportStore._brief_text(research.product_price_summary, 160)}",
                ]
            )
        lines.extend(
            [
                "",
                "## 技术面分析",
                f"- {ReportStore._technical_summary(analysis)}",
                "",
                "## 政策分析",
                (
                    ReportStore._brief_text(research.policy_summary, 140)
                    if research
                    else "数据缺口：缺少研究输入。"
                ),
                "",
                "## 消息面分析",
                (
                    ReportStore._brief_text(research.news_summary, 140)
                    if research
                    else "数据缺口：缺少研究输入。"
                ),
            ]
        )
        if research and ReportStore._has_stock_international_summary(analysis):
            lines.append(
                "国际传导：" + ReportStore._brief_text(research.international_summary, 120)
            )
        if research:
            lines.append(f"研究数据截至：{research.data_as_of.isoformat()}")
        if research and research.events:
            lines.extend(["", "## 突发事件"])
            for event in research.events:
                lines.append(
                    f"- {event.occurred_at.isoformat()} — {event.title}："
                    f"{ReportStore._brief_text(event.summary, 120)}"
                )
                if event.citation_title and event.citation_url:
                    lines.append(f"  - 事件来源：[{event.citation_title}]({event.citation_url})")
        lines.extend(["", "## 操作建议"])
        lines.extend(f"- {item}" for item in ReportStore._recommendation_overview(analysis))
        stock_evidence = ReportStore._stock_evidence(analysis, public_evidence_urls)
        if stock_evidence or analysis.data_gaps:
            lines.extend(["", "## 来源与数据缺口" if analysis.data_gaps else "## 来源"])
        if stock_evidence:
            lines.extend(
                f"- [{evidence.title}]({evidence.url}) — {ReportStore._evidence_summary(evidence)}"
                for evidence in stock_evidence
            )
        if analysis.data_gaps:
            lines.extend(
                f"- 数据缺口：{ReportStore._display_value(gap, 'data_gaps')}"
                for gap in analysis.data_gaps
            )
        return lines

    @staticmethod
    def _markdown_analysis(
        analysis: StockAnalysis,
        public_evidence_urls: set[str] | frozenset[str] = frozenset(),
    ) -> list[str]:
        return ReportStore._compact_markdown_analysis(analysis, public_evidence_urls)

    @staticmethod
    def _recommendation_for(
        analysis: StockAnalysis, horizon: Horizon | str
    ) -> Recommendation | None:
        expected = Horizon(horizon)
        return next((item for item in analysis.recommendations if item.horizon is expected), None)

    @staticmethod
    def _markdown_recommendation_summary(analyses: list[StockAnalysis]) -> list[str]:
        lines = [
            "",
            "## 全部标的操作汇总",
            "",
            "以下仅汇总本报告中的条件化研究建议，不构成交易指令。",
            "",
        ]
        for analysis in analyses:
            lines.append(
                f"- {analysis.stock.symbol} {analysis.stock.name}："
                + "；".join(ReportStore._recommendation_overview(analysis))
            )
        return lines

    @staticmethod
    def _canonical_evidence_url(evidence: Evidence) -> str:
        return str(evidence.url)

    @staticmethod
    def _public_evidence(analyses: list[StockAnalysis]) -> list[Evidence]:
        evidence_by_url: dict[str, list[tuple[str, Evidence]]] = {}
        for analysis in analyses:
            if analysis.research is None:
                continue
            for evidence in analysis.research.evidence:
                evidence_by_url.setdefault(
                    ReportStore._canonical_evidence_url(evidence), []
                ).append((analysis.stock.symbol, evidence))

        public_evidence: list[Evidence] = []
        for entries in evidence_by_url.values():
            symbols = {symbol for symbol, _ in entries}
            presentation = {
                (
                    evidence.title,
                    evidence.category,
                    evidence.source_name,
                    evidence.published_at,
                    evidence.retrieved_at,
                    evidence.direction,
                    evidence.credibility,
                    evidence.summary,
                )
                for _, evidence in entries
            }
            category = entries[0][1].category
            # Evidence.symbols describes the configured subject consuming a source,
            # so it can legitimately differ for a shared policy or international item.
            # Only wholly identical presentation data from inherently public categories
            # is moved to the overview; company and news material remains per stock.
            if (
                len(symbols) >= 2
                and category in _PUBLIC_EVIDENCE_CATEGORIES
                and len(presentation) == 1
            ):
                public_evidence.append(entries[0][1])
        return public_evidence

    @staticmethod
    def _public_evidence_urls(analyses: list[StockAnalysis]) -> set[str]:
        return {
            ReportStore._canonical_evidence_url(evidence)
            for evidence in ReportStore._public_evidence(analyses)
        }

    @staticmethod
    def _stock_evidence_for_report(
        analysis: StockAnalysis, analyses: list[StockAnalysis]
    ) -> list[Evidence]:
        return ReportStore._stock_evidence(analysis, ReportStore._public_evidence_urls(analyses))

    @staticmethod
    def _has_stock_international_evidence_for_report(
        analysis: StockAnalysis, analyses: list[StockAnalysis]
    ) -> bool:
        del analyses
        return ReportStore._has_stock_international_summary(analysis)

    @staticmethod
    def _stock_evidence(
        analysis: StockAnalysis, public_evidence_urls: set[str] | frozenset[str]
    ) -> list[Evidence]:
        if analysis.research is None:
            return []
        return [
            evidence
            for evidence in analysis.research.evidence
            if ReportStore._canonical_evidence_url(evidence) not in public_evidence_urls
        ]

    @staticmethod
    def _has_stock_international_summary(analysis: StockAnalysis) -> bool:
        return bool(analysis.research and analysis.research.international_summary.strip())

    @staticmethod
    def _recommendation_summary(recommendation: Recommendation | None) -> str:
        if recommendation is None:
            return "未生成"
        action = ReportStore._display_value(recommendation.action.value, "action")
        risk = ReportStore._display_value(recommendation.risk_level.value, "risk_level")
        confidence = ReportStore._display_value(recommendation.confidence.value, "confidence")
        return f"{action}（{risk}风险 / {confidence}置信度）"

    @staticmethod
    def _recommendation_overview(analysis: StockAnalysis) -> list[str]:
        horizons = (
            (Horizon.SHORT, "短线"),
            (Horizon.MEDIUM, "中线"),
            (Horizon.LONG, "长线"),
        )
        recommendations = [
            (heading, ReportStore._recommendation_for(analysis, horizon))
            for horizon, heading in horizons
        ]
        if not any(recommendation for _, recommendation in recommendations):
            return ["暂无可用建议。"]
        summaries = [
            ReportStore._recommendation_summary(recommendation)
            for _, recommendation in recommendations
        ]
        if len(set(summaries)) == 1:
            return [f"短、中、长线一致：{summaries[0]}"]
        return [
            f"{heading}：{summary}"
            for (heading, _), summary in zip(recommendations, summaries, strict=True)
        ]

    @staticmethod
    def _stock_configuration_summary(analysis: StockAnalysis) -> str:
        stock = analysis.stock
        parts = [
            f"市场：{ReportStore._display_value(stock.market.value, 'market')}",
            f"行业：{stock.industry or '未设置'}",
        ]
        if stock.product_price_focus:
            parts.append(f"关注项：{'、'.join(stock.product_price_focus)}")
        if stock.holding:
            parts.append(f"持仓：{stock.holding.quantity} 股，成本 {stock.holding.cost_basis}")
        return "；".join(parts)

    @staticmethod
    def _previous_day_summary(analysis: StockAnalysis) -> str:
        previous = analysis.previous_day
        if previous is None:
            return "数据缺口：无可验证的已完成行情。"
        reason = ReportStore._display_value(previous.reason, "reason")
        if reason.startswith("前日表现不作归因："):
            return ReportStore._previous_day_metrics(analysis)
        return (
            f"{ReportStore._previous_day_metrics(analysis)}；"
            f"主要归因：{ReportStore._brief_text(reason, 120)}"
        )

    @staticmethod
    def _previous_day_metrics(analysis: StockAnalysis) -> str:
        previous = analysis.previous_day
        if previous is None:
            return "数据缺口：无可验证的已完成行情。"
        change = (
            f"{previous.change_percent:+.2f}%"
            if previous.change_percent is not None
            else f"{previous.change:+.4f}"
        )
        return (
            f"数据截至 {previous.data_as_of.isoformat()}；收盘 {previous.close:.4f}；涨跌 {change}"
        )

    @staticmethod
    def _technical_summary(analysis: StockAnalysis) -> str:
        technical = analysis.technical
        if technical is None:
            return "数据缺口：技术指标不可用。"
        parts = [
            f"数据截至 {technical.data_as_of.isoformat()}",
            f"收盘 {technical.latest_close:.4f}",
            f"趋势 {ReportStore._display_value(technical.trend.value, 'trend')}",
        ]
        if technical.rsi_14 is not None:
            parts.append(f"RSI(14) {technical.rsi_14:.1f}")
        if technical.support_20 is not None:
            parts.append(f"20 日支撑 {technical.support_20:.2f}")
        if technical.resistance_20 is not None:
            parts.append(f"20 日阻力 {technical.resistance_20:.2f}")
        if technical.volume_ratio_20 is not None:
            parts.append(f"量比 {technical.volume_ratio_20:.2f}")
        return "；".join(parts)

    @staticmethod
    def _evidence_summary(evidence: object) -> str:
        published_at = getattr(evidence, "published_at", None)
        publication = published_at.date().isoformat() if published_at else "发布日期未提供"
        return f"{getattr(evidence, 'source_name')}，{publication}"

    @staticmethod
    def _brief_text(value: object, limit: int) -> str:
        text = " ".join(str(value).split())
        if len(text) <= limit:
            return text
        ending = max((text.rfind(mark, 0, limit) for mark in "。；！？"), default=-1)
        cutoff = ending + 1 if ending >= limit // 2 else limit
        return text[:cutoff].rstrip("，、；：") + "……"

    @staticmethod
    def _markdown_structured_fields(model: BaseModel | None) -> list[str]:
        if model is None:
            return []
        return [f"- {name}：{value}" for name, value in ReportStore._structured_fields(model)]

    @staticmethod
    def _structured_fields(model: BaseModel) -> list[tuple[str, str]]:
        return [
            (ReportStore._display_field(name), ReportStore._display_value(value, name))
            for name, value in model.model_dump(mode="json").items()
        ]

    @staticmethod
    def _display_field(name: str) -> str:
        return _FIELD_LABELS.get(name, name)

    @staticmethod
    def _display_value(value: object, field_name: str | None = None) -> str:
        if value is None:
            return "无"
        if isinstance(value, bool):
            return "是" if value else "否"
        if field_name in {"volume", "previous_volume"} and isinstance(value, (int, float)):
            return f"{value:,.0f} 股"
        if field_name == "volume_change_percent" and isinstance(value, (int, float)):
            return f"{value:+.2f}%"
        if isinstance(value, list):
            return ", ".join(ReportStore._display_value(item, field_name) for item in value)
        if isinstance(value, dict):
            return ", ".join(
                f"{ReportStore._display_field(str(key))}={ReportStore._display_value(item, str(key))}"
                for key, item in sorted(value.items())
            )
        if isinstance(value, str):
            if field_name in _LEGACY_SYSTEM_TEXT_FIELDS:
                legacy_text = _LEGACY_SYSTEM_TEXT.get(value)
                if legacy_text is not None:
                    return legacy_text
                closed_status = _LEGACY_CLOSED_STATUS.fullmatch(value)
                if field_name == "message" and closed_status is not None:
                    return (
                        f"报告日 {closed_status.group(1)} 市场休市；"
                        "所有已配置股票均使用前一已完成交易日的最新数据。"
                    )
            legacy_gap = ReportStore._legacy_price_data_gap(value, field_name)
            if legacy_gap is not None:
                return legacy_gap
        if field_name == "rationale" and isinstance(value, str):
            if value.startswith(LEGACY_DATA_GAP_RATIONALE_PREFIX):
                return f"{DATA_GAP_RATIONALE_PREFIX}{value.removeprefix(LEGACY_DATA_GAP_RATIONALE_PREFIX)}"
        if field_name is not None:
            contextual_display = _FIELD_DISPLAY_VALUES.get(field_name, {}).get(str(value))
            if contextual_display is not None:
                return contextual_display
        if field_name in _ENUM_DISPLAY_FIELDS:
            return _DISPLAY_VALUES.get(str(value), str(value))
        return str(value)

    @staticmethod
    def _legacy_price_data_gap(value: str, field_name: str | None) -> str | None:
        if field_name not in _LEGACY_PRICE_DATA_FIELDS:
            return None
        candidate = value
        if field_name == "rationale" and candidate.startswith(LEGACY_DATA_GAP_RATIONALE_PREFIX):
            candidate = candidate.removeprefix(LEGACY_DATA_GAP_RATIONALE_PREFIX)
        if field_name == "reason" and candidate.startswith("No causal attribution: "):
            candidate = candidate.removeprefix("No causal attribution: ")
        if "price data unavailable (" not in candidate.lower():
            return None
        symbol_match = _LEGACY_SYMBOL_PREFIX.match(candidate)
        if symbol_match is None:
            return None
        safe_gap = f"{symbol_match.group('symbol')}：未能取得完整的日行情数据，已暂缓技术分析。"
        if field_name == "rationale":
            return f"{DATA_GAP_RATIONALE_PREFIX}{safe_gap}"
        if field_name == "reason":
            return f"前日表现不作归因：{safe_gap}"
        return safe_gap
