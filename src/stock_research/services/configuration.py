from pathlib import Path

import yaml

from stock_research.domain.models import StockConfig
from stock_research.repositories.stocks import StockRepository


class ConfigurationService:
    def __init__(self, repository: StockRepository) -> None:
        self.repository = repository

    def import_yaml(self, path: Path) -> list[StockConfig]:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"stocks"}:
            raise ValueError("configuration must contain only a top-level stocks list")
        rows = payload["stocks"]
        if not isinstance(rows, list):
            raise ValueError("configuration stocks must be a list")

        validated = [StockConfig.model_validate(row) for row in rows]
        for stock in validated:
            self.repository.upsert(stock)
        return validated

    def list_stocks(self) -> list[StockConfig]:
        return self.repository.list_all()
