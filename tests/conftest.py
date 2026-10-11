from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session

from planner.storage.db import make_engine, run_migrations
from planner.storage.repo import Repository


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    run_migrations(url)
    return url


@pytest.fixture()
def session(db_url: str) -> Iterator[Session]:
    engine = make_engine(db_url)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture()
def repo(session: Session) -> Repository:
    return Repository(session)
