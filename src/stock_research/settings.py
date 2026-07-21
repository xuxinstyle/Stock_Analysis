from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    database_path: Path = Path("data/stock_research.sqlite3")
