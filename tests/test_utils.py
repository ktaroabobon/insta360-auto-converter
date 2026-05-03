"""utils モジュールのユニットテスト。

特にログディレクトリ初期化の動作を検証する。プロダクションでは
`/insta360-auto-converter-data/logs` を作るが、コンテナ外 (テスト含む) では
書き込めないので、環境変数 INSTA360_LOGS_DIR で差し替えられる必要がある。
"""
from __future__ import annotations

import sys
from pathlib import Path


def _reload_utils():
    sys.modules.pop("utils", None)
    import utils  # noqa: F401  (副作用として LOG_DIR の作成が走る)
    import importlib
    return importlib.import_module("utils")


def test_log_dir_can_be_overridden_via_env(tmp_path: Path, monkeypatch):
    """INSTA360_LOGS_DIR が指す場所が `log_dir` として採用され、ディレクトリが作成される。"""
    target = tmp_path / "custom-logs"
    monkeypatch.setenv("INSTA360_LOGS_DIR", str(target))

    utils = _reload_utils()

    assert target.exists()
    assert utils.log_dir == str(target)


def test_log_dir_falls_back_to_temp_when_default_is_unwritable(tmp_path: Path, monkeypatch):
    """env が未設定 & デフォルトパスが書けない場合は、import が失敗せず一時ディレクトリにフォールバックする。"""
    monkeypatch.delenv("INSTA360_LOGS_DIR", raising=False)

    utils = _reload_utils()

    # フォールバック後の log_dir は実在し、書き込み可能であること
    assert Path(utils.log_dir).exists()
    test_file = Path(utils.log_dir) / "smoke.txt"
    test_file.write_text("ok")
    assert test_file.read_text() == "ok"
