"""共有 fixture とテスト全体で必要な前処理。

apps/ 配下のモジュール (特に utils) はロード時に
`/insta360-auto-converter-data/logs` を `os.makedirs` で作りに行く。
コンテナ外 (テスト) ではこのパスは書けないので、conftest の **モジュールロード時**
に `INSTA360_LOGS_DIR` を tmp ディレクトリに向けておく。
こうしておくと、その後どのテストが utils をどう import しても落ちない。

同様に、`apps.utils` を含む各モジュールはロード時に YAML 設定ファイル
(`/insta360-auto-converter-data/configs.yaml`) を要求するようになる予定。
コンテナ外で読み書きできないため、ここでも **モジュールロード時** に
`INSTA360_CONFIGS_PATH` を tmp ディレクトリ配下のダミー YAML に向ける。
ダミー YAML は loader が要求するすべての必須キーをプレースホルダ値で含み、
副作用なく import できる構造にする。
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# テストプロセス内で共有する書き込み可能なログ置き場
_TEST_LOGS_DIR = tempfile.mkdtemp(prefix="insta360-test-logs-")
os.environ.setdefault("INSTA360_LOGS_DIR", _TEST_LOGS_DIR)


# テストプロセス内で共有するダミー設定ファイルの置き場。
# 1 度だけ作成して `INSTA360_CONFIGS_PATH` を向ける。プロセス終了時に cleanup する。
_TEST_CONFIGS_DIR = tempfile.mkdtemp(prefix="insta360-test-configs-")
_TEST_CONFIGS_PATH = Path(_TEST_CONFIGS_DIR) / "configs.yaml"

# `apps/app_config.py` の loader が要求するすべての必須キーをプレースホルダ値で記載。
# YAML として安全に書ければよく、実値は本番のものと衝突しないテスト固有の値にする。
_DUMMY_CONFIG_YAML = """\
gdrive:
  drive_id: "test-drive-id"
  working_folder_id: "test-working-folder-id"
gmail:
  address: "test@example.com"
  password: "test-password"
  error_mail_to: "ops@example.com"
upload:
  drive: true
  photos: true
"""

_TEST_CONFIGS_PATH.write_text(_DUMMY_CONFIG_YAML, encoding="utf-8")
os.environ.setdefault("INSTA360_CONFIGS_PATH", str(_TEST_CONFIGS_PATH))


def _cleanup_test_configs_dir() -> None:
    """テストプロセス終了時にダミー設定ディレクトリを削除する。"""
    shutil.rmtree(_TEST_CONFIGS_DIR, ignore_errors=True)


atexit.register(_cleanup_test_configs_dir)


@pytest.fixture(autouse=True)
def _ensure_apps_on_path() -> None:
    """pyproject.toml の `[tool.pytest.ini_options].pythonpath` で apps/ は通っているが、
    念のため明示的に sys.path 先頭へ追加し、テスト同士の独立性を担保する。"""
    apps_dir = str(Path(__file__).resolve().parent.parent / "apps")
    if apps_dir not in sys.path:
        sys.path.insert(0, apps_dir)
