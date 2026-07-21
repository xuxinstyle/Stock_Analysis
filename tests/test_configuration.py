from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from stock_research.db import create_engine_at
from stock_research.domain.enums import Market
from stock_research.domain.models import StockConfig
from stock_research.repositories.stocks import StockRepository
from stock_research.services.configuration import ConfigurationService


TEST_DATA_DIR = Path(__file__).parent / "fixtures"


def test_a_share_symbol_requires_exchange_prefix() -> None:
    with pytest.raises(ValidationError, match=r"SH\.600000"):
        StockConfig(symbol="600000", name="浦发银行", market=Market.A_SHARE)


def test_yaml_import_persists_optional_holding(tmp_path: Path) -> None:
    service = ConfigurationService(StockRepository(create_engine_at(tmp_path / "app.sqlite3")))

    service.import_yaml(TEST_DATA_DIR / "stocks.yaml")

    saved = service.list_stocks()
    assert saved[0].symbol == "SH.600000"
    assert saved[0].holding is not None
    assert saved[0].holding.cost_basis == Decimal("10.50")


def test_yaml_import_validates_all_rows_before_persisting(tmp_path: Path) -> None:
    repository = StockRepository(create_engine_at(tmp_path / "app.sqlite3"))
    service = ConfigurationService(repository)
    invalid_file = tmp_path / "invalid-stocks.yaml"
    invalid_file.write_text(
        "stocks:\n"
        "  - symbol: SH.600000\n"
        "    name: 浦发银行\n"
        "    market: a_share\n"
        "  - symbol: 00700\n"
        "    name: 腾讯控股\n"
        "    market: hong_kong\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        service.import_yaml(invalid_file)

    assert service.list_stocks() == []


def test_upsert_replaces_stock_with_matching_symbol(tmp_path: Path) -> None:
    repository = StockRepository(create_engine_at(tmp_path / "app.sqlite3"))
    original = StockConfig(symbol="SZ.000001", name="平安银行", market=Market.A_SHARE)
    replacement = StockConfig(
        symbol="SZ.000001",
        name="平安银行（更新）",
        market=Market.A_SHARE,
        industry="银行",
    )

    repository.upsert(original)
    repository.upsert(replacement)

    assert repository.list_all() == [replacement]
