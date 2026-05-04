"""DriveModeConfigConsumer (`apps/insta360_auto_converter.py`) のスモークテスト。

Drive モードのエントリポイントが、モジュールロード時に YAML 由来の `AppConfig`
を読み込むようになっていることを検証する回帰テスト。

検証ポイント:

- `INSTA360_CONFIGS_PATH` を tmp YAML に向けたうえで `insta360_auto_converter`
  を import し直しても import 自体が成功する (= モジュールロード時の YAML 読み込みが
  通るかどうかの smoke test)
- import 後にモジュール内のグローバル `_app_config` が `AppConfig`
  インスタンスを保持し、`gdrive.drive_id` / `gdrive.working_folder_id` が
  YAML 由来の値であること

このテストは `apps/insta360_auto_converter.py` が `ConfigParser`
ベースの読み込みから `load_app_config()` 経由に切り替わっていない場合、
`_app_config` が存在しない (AttributeError) または `AppConfig` インスタンス
ではないため、必ず赤になる。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from app_config import AppConfig


_DUMMY_YAML = """\
gdrive:
  drive_id: "drive-mode-yaml-drive-id"
  working_folder_id: "drive-mode-yaml-working-folder-id"
gmail:
  address: "drive-mode@example.com"
  password: "drive-mode-password"
  error_mail_to: "drive-mode-ops@example.com"
upload:
  drive: true
  photos: true
"""


def _reload_module(module_name: str):
    """`module_name` をリロードする (sys.modules から落としてから import)。"""
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_insta360_auto_converter_loads_app_config_via_yaml(
    tmp_path: Path, monkeypatch
) -> None:
    """`insta360_auto_converter` の import が YAML 経由で成功し、
    `_app_config` グローバルが `AppConfig` 実体で、Drive ID が
    YAML の値を保持していること。"""
    yaml_path = tmp_path / "configs.yaml"
    yaml_path.write_text(_DUMMY_YAML, encoding="utf-8")
    monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(yaml_path))

    # utils も `_app_config` を持つ可能性があるが、本テストは
    # insta360_auto_converter のグローバルだけを検査する。
    # 念のため utils も再読み込みして INSTA360_CONFIGS_PATH の差し替えが反映された
    # 状態にしておく。
    _reload_module("utils")
    module = _reload_module("insta360_auto_converter")

    # モジュールロード時の `_app_config` グローバルが存在し、AppConfig 型であること
    assert hasattr(module, "_app_config"), (
        "insta360_auto_converter must expose `_app_config` after migrating to "
        "load_app_config(); ConfigParser-based code does not produce this attribute."
    )
    assert isinstance(module._app_config, AppConfig)

    # YAML 由来の Drive ID / working_folder_id を保持していること
    assert module._app_config.gdrive.drive_id == "drive-mode-yaml-drive-id"
    assert (
        module._app_config.gdrive.working_folder_id
        == "drive-mode-yaml-working-folder-id"
    )

    # `ConfigParser` ベースのグローバルが残っていないこと (移行漏れ検知)
    assert not hasattr(module, "config"), (
        "module-level `config = ConfigParser()` must be removed; "
        "use `_app_config` (AppConfig) instead."
    )
