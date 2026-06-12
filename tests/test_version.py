from typer.testing import CliRunner

import render
from render.cli import app


def test_version_import():
    assert render.__version__ == "0.1.0"


def test_version_flag():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
