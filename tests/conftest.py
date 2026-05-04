"""共有 fixture とテスト全体で必要な前処理。

apps/ 配下のモジュール (特に utils) はロード時に
`/insta360-auto-converter-data/logs` を `os.makedirs` で作りに行く。
コンテナ外 (テスト) ではこのパスは書けないので、conftest の **モジュールロード時**
に `INSTA360_LOGS_DIR` を tmp ディレクトリに向けておく。
こうしておくと、その後どのテストが utils をどう import しても落ちない。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# テストプロセス内で共有する書き込み可能なログ置き場
_TEST_LOGS_DIR = tempfile.mkdtemp(prefix="insta360-test-logs-")
os.environ.setdefault("INSTA360_LOGS_DIR", _TEST_LOGS_DIR)


@pytest.fixture(autouse=True)
def _ensure_apps_on_path() -> None:
    """pyproject.toml の `[tool.pytest.ini_options].pythonpath` で apps/ は通っているが、
    念のため明示的に sys.path 先頭へ追加し、テスト同士の独立性を担保する。"""
    apps_dir = str(Path(__file__).resolve().parent.parent / "apps")
    if apps_dir not in sys.path:
        sys.path.insert(0, apps_dir)
