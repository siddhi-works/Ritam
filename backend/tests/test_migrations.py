from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migrations_form_a_single_line():
    # Two heads make `alembic upgrade head` fail when the server boots, so a deploy would crash.
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, heads
