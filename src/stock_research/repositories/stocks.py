import json

from sqlalchemy import Column, Engine, MetaData, String, Table, Text, select, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError

from stock_research.domain.models import StockConfig


metadata = MetaData()
stocks = Table(
    "stocks",
    metadata,
    Column("symbol", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("market", String, nullable=False),
    Column("industry", String, nullable=True),
    Column("product_price_focus", Text, nullable=True),
    Column("holding", Text, nullable=True),
)


class DuplicateStockError(ValueError):
    """Raised when a create operation targets an existing stock symbol."""


class StockRepository:
    def __init__(self, engine: Engine, *, initialize: bool = True) -> None:
        self.engine = engine
        if initialize:
            metadata.create_all(engine)
            self._migrate_product_price_focus_column()
        self._has_product_price_focus = self._table_has_product_price_focus_column()

    def upsert(self, stock: StockConfig) -> StockConfig:
        values = {
            "symbol": stock.symbol,
            "name": stock.name,
            "market": stock.market.value,
            "industry": stock.industry,
            "product_price_focus": self._serialize_product_price_focus(stock),
            "holding": self._serialize_holding(stock),
        }
        statement = insert(stocks).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[stocks.c.symbol],
            set_={key: value for key, value in values.items() if key != "symbol"},
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
        return stock

    def create(self, stock: StockConfig) -> StockConfig:
        values = {
            "symbol": stock.symbol,
            "name": stock.name,
            "market": stock.market.value,
            "industry": stock.industry,
            "product_price_focus": self._serialize_product_price_focus(stock),
            "holding": self._serialize_holding(stock),
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(stocks.insert().values(**values))
        except IntegrityError as error:
            raise DuplicateStockError(stock.symbol) from error
        return stock

    def list_all(self) -> list[StockConfig]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(self._select_stocks().order_by(text("rowid"))).mappings().all()
            )
        return [self._deserialize_stock(dict(row)) for row in rows]

    def get(self, symbol: str) -> StockConfig | None:
        statement = self._select_stocks().where(stocks.c.symbol == symbol)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else self._deserialize_stock(dict(row))

    def delete(self, symbol: str) -> bool:
        statement = stocks.delete().where(stocks.c.symbol == symbol)
        with self.engine.begin() as connection:
            result = connection.execute(statement)
        return result.rowcount == 1

    def replace_all(self, values: list[StockConfig]) -> list[StockConfig]:
        rows = [
            {
                "symbol": stock.symbol,
                "name": stock.name,
                "market": stock.market.value,
                "industry": stock.industry,
                "product_price_focus": self._serialize_product_price_focus(stock),
                "holding": self._serialize_holding(stock),
            }
            for stock in values
        ]
        with self.engine.begin() as connection:
            connection.execute(stocks.delete())
            if rows:
                connection.execute(stocks.insert(), rows)
        return values

    @staticmethod
    def _serialize_holding(stock: StockConfig) -> str | None:
        if stock.holding is None:
            return None
        return json.dumps(stock.holding.model_dump(mode="json"))

    @staticmethod
    def _serialize_product_price_focus(stock: StockConfig) -> str | None:
        return json.dumps(stock.product_price_focus, ensure_ascii=False) or None

    def _migrate_product_price_focus_column(self) -> None:
        if self._table_has_product_price_focus_column():
            return
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE stocks ADD COLUMN product_price_focus TEXT"))

    def _table_has_product_price_focus_column(self) -> bool:
        with self.engine.connect() as connection:
            columns = connection.execute(text("PRAGMA table_info(stocks)")).mappings().all()
        return any(column["name"] == "product_price_focus" for column in columns)

    def _select_stocks(self):
        if self._has_product_price_focus:
            return select(stocks)
        return select(
            stocks.c.symbol,
            stocks.c.name,
            stocks.c.market,
            stocks.c.industry,
            stocks.c.holding,
        )

    @staticmethod
    def _deserialize_stock(row: dict[str, str | None]) -> StockConfig:
        holding = row.pop("holding")
        if holding is not None:
            row["holding"] = json.loads(holding)
        product_price_focus = row.pop("product_price_focus", None)
        if product_price_focus is not None:
            row["product_price_focus"] = json.loads(product_price_focus)
        return StockConfig.model_validate(row)
