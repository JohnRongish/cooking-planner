from pathlib import Path

import pytest

from planner.config import AppConfig
from planner.web.app import prepare_data_dir


def test_from_env_defaults_and_overrides():
    cfg = AppConfig.from_env({})
    assert cfg.page_size == "Letter" and cfg.port == 8080 and cfg.password is None
    cfg = AppConfig.from_env(
        {
            "PLANNER_DATA_DIR": "/x",
            "PLANNER_PASSWORD": "pw",
            "PLANNER_PAGE_SIZE": "a4",
            "PORT": "9000",
            "PLANNER_BASE_URL": "https://p.example/",
        }
    )
    assert cfg.data_dir == Path("/x") and cfg.password == "pw" and cfg.page_size == "A4"
    assert cfg.port == 9000 and cfg.base_url == "https://p.example"
    assert cfg.db_url == "sqlite:////x/planner.db"
    assert cfg.export_dir == Path("/x/exports")
    assert AppConfig.from_env({"PLANNER_PASSWORD": ""}).password is None


def test_bad_page_size_is_rejected():
    with pytest.raises(ValueError):
        AppConfig.from_env({"PLANNER_PAGE_SIZE": "Tabloid"})


def test_unwritable_data_dir_gives_a_readable_error(tmp_path: Path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    with pytest.raises(SystemExit) as exc:
        prepare_data_dir(AppConfig(data_dir=blocker / "data"))
    assert "Cannot write to the data folder" in str(exc.value) and "ACL" in str(exc.value)
