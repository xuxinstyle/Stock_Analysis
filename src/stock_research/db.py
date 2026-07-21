from pathlib import Path

from sqlalchemy import Engine, create_engine


def create_engine_at(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path.resolve().as_posix()}")


def create_read_only_engine_at(path: Path) -> Engine:
    if not path.is_file():
        raise FileNotFoundError(path)
    return create_engine(f"sqlite:///file:{path.resolve().as_posix()}?mode=ro&uri=true")
