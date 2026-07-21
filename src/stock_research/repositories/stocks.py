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
    Column("holding", Text, nullable=True),
)


class DuplicateStockError(ValueError):
    """Raised when a create operation targets an existing stock symbol."""


class StockRepository:
    def __init__(self, engine: Engine, *, initialize: bool = True) -> None:
        self.engine = engine
        if initialize:
            metadata.create_all(engine)

    def upsert(self, stock: StockConfig) -> StockConfig:
        values = {
            "symbol": stock.symbol,
            "name": stock.name,
            "market": stock.market.value,
            "industry": stock.industry,
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
            rows = connection.execute(select(stocks).order_by(text("rowid"))).mappings().all()
        return [self._deserialize_stock(dict(row)) for row in rows]

    def get(self, symbol: str) -> StockConfig | None:
        statement = select(stocks).where(stocks.c.symbol == symbol)
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
    def _deserialize_stock(row: dict[str, str | None]) -> StockConfig:
        holding = row.pop("holding")
        if holding is not None:
            row["holding"] = json.loads(holding)
        return StockConfig.model_validate(row)
