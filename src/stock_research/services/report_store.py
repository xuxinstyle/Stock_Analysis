from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from stock_research.db import create_engine_at
from stock_research.domain.enums import Horizon
from stock_research.domain.models import DailyReport, Recommendation, StockAnalysis
from stock_research.repositories.reports import ReportRepository


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
        paths = self.paths_for(report.report_date)
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

    def paths_for(self, report_date: date) -> ReportPaths:
        destination = self.root / report_date.isoformat()
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
            recommendation_for=self._recommendation_for,
            structured_fields=self._structured_fields,
            standalone=True,
        )

    @staticmethod
    def _render_markdown(report: DailyReport) -> str:
        lines = [
            f"# 每日股票研究报告 — {report.report_date.isoformat()}",
            "",
            f"- 生成时间：{report.generated_at.isoformat()}",
            f"- 运行状态：{report.run_status.value}",
            f"- 免责声明：{report.disclaimer}",
            "",
            "## 市场状态",
        ]
        if report.market_statuses:
            for status in report.market_statuses:
                data_as_of = status.data_as_of.isoformat() if status.data_as_of else "无可用日期"
                lines.append(
                    f"- {status.market.value}: {status.status}; {data_as_of}; {status.message}"
                )
        else:
            lines.append("- 无已配置市场。")
        lines.extend(["", "## 全局风险"])
        lines.extend(f"- {risk}" for risk in report.global_risks or ["无已提供全局风险摘要。"])
        lines.extend(["", "## 运行警告"])
        lines.extend(f"- {warning}" for warning in report.run_warnings or ["无。"])

        for analysis in report.analyses:
            lines.extend(ReportStore._markdown_analysis(analysis))
        return "\n".join(lines) + "\n"

    @staticmethod
    def _markdown_analysis(analysis: StockAnalysis) -> list[str]:
        research = analysis.research
        previous = analysis.previous_day
        technical = analysis.technical
        lines = [
            "",
            f"# {analysis.stock.symbol} {analysis.stock.name}",
            "",
            "## 股票配置",
            *ReportStore._markdown_structured_fields(analysis.stock),
            *(
                [
                    "",
                    "### 持仓配置",
                    *ReportStore._markdown_structured_fields(analysis.stock.holding),
                ]
                if analysis.stock.holding
                else []
            ),
            (
                f"- 研究数据截至：{research.data_as_of.isoformat()}"
                if research
                else "- 研究数据截至：不可用"
            ),
            "",
            "## 前日表现与原因",
            (
                f"数据截至 {previous.data_as_of.isoformat()}，收盘 {previous.close:.4f}，"
                f"变动 {previous.change:+.4f}；{previous.reason}"
                if previous
                else "数据缺口：无可验证的已完成行情。"
            ),
            *ReportStore._markdown_structured_fields(previous),
            "",
            "## 基本面分析",
            research.fundamental_summary if research else "数据缺口：缺少研究输入。",
            "",
            "## 行业分析",
            (
                f"{research.industry_summary}\n\n产品价格：{research.product_price_summary}"
                if research
                else "数据缺口：缺少研究输入。"
            ),
            "",
            "## 技术面分析",
            (
                f"数据截至 {technical.data_as_of.isoformat()}，收盘 {technical.latest_close:.4f}，"
                f"趋势 {technical.trend.value}，RSI(14) {technical.rsi_14}."
                if technical
                else "数据缺口：技术指标不可用。"
            ),
            *ReportStore._markdown_structured_fields(technical),
            "",
            "## 政策分析",
            research.policy_summary if research else "数据缺口：缺少研究输入。",
            "",
            "## 消息面分析",
            (
                f"{research.news_summary}\n\n国际传导：{research.international_summary}"
                if research
                else "数据缺口：缺少研究输入。"
            ),
            "",
            "## 突发事件",
        ]
        if research and research.events:
            for event in research.events:
                lines.append(f"- {event.occurred_at.isoformat()} — {event.title}: {event.summary}")
                if event.citation_title and event.citation_url:
                    lines.append(f"  - 事件来源：[{event.citation_title}]({event.citation_url})")
                lines.extend(
                    f"  - {name}: {value}" for name, value in ReportStore._structured_fields(event)
                )
        else:
            lines.append("- 无已提供的可验证突发事件。")
        for horizon, heading in (
            (Horizon.SHORT, "短线建议"),
            (Horizon.MEDIUM, "中线建议"),
            (Horizon.LONG, "长线建议"),
        ):
            recommendation = ReportStore._recommendation_for(analysis, horizon)
            lines.extend(["", f"## {heading}"])
            if recommendation:
                lines.extend(
                    [
                        f"- 动作：{recommendation.action.value}",
                        f"- 风险/信心：{recommendation.risk_level.value}/{recommendation.confidence.value}",
                        f"- 依据：{' '.join(recommendation.rationale)}",
                        f"- {recommendation.trigger}",
                        f"- {recommendation.observation_or_target}",
                        f"- {recommendation.invalidation}",
                        f"- 仓位上限：{recommendation.position_limit}",
                    ]
                )
                if recommendation.holding_impact:
                    lines.append(f"- 持仓影响：{recommendation.holding_impact}")
                lines.extend(f"- 建议依据标题：{title}" for title in recommendation.evidence_titles)
                lines.extend(f"- 建议引用：{url}" for url in recommendation.citation_urls)
        lines.extend(["", "## 来源与数据缺口"])
        if research and research.evidence:
            for evidence in research.evidence:
                lines.append(
                    f"- [{evidence.title}]({evidence.url}) — {evidence.source_name}; "
                    f"可信度 {evidence.credibility.value}"
                )
                lines.extend(
                    f"  - {name}: {value}"
                    for name, value in ReportStore._structured_fields(evidence)
                )
        else:
            lines.append("- 无已验证的引用来源。")
        lines.extend(f"- 数据缺口：{gap}" for gap in analysis.data_gaps)
        return lines

    @staticmethod
    def _recommendation_for(
        analysis: StockAnalysis, horizon: Horizon | str
    ) -> Recommendation | None:
        expected = Horizon(horizon)
        return next((item for item in analysis.recommendations if item.horizon is expected), None)

    @staticmethod
    def _markdown_structured_fields(model: BaseModel | None) -> list[str]:
        if model is None:
            return []
        return [f"- {name}: {value}" for name, value in ReportStore._structured_fields(model)]

    @staticmethod
    def _structured_fields(model: BaseModel) -> list[tuple[str, str]]:
        return [
            (name, ReportStore._display_value(value))
            for name, value in model.model_dump(mode="json").items()
        ]

    @staticmethod
    def _display_value(value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, list):
            return ", ".join(ReportStore._display_value(item) for item in value)
        if isinstance(value, dict):
            return ", ".join(
                f"{key}={ReportStore._display_value(item)}" for key, item in sorted(value.items())
            )
        return str(value)
