"""conftest.py が用意する共有 fixture の挙動を検証するテスト。

`INSTA360_CONFIGS_PATH` がテストプロセス全体で設定されており、
そのパスにすべての必須キーを含む YAML が用意されていることを保証する。
これにより、後続タスク (`apps.utils` のモジュールロード時 YAML 化) でも
副作用なく import できる前提を担保する。
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml


REQUIRED_KEYS = [
    ("gdrive", "drive_id"),
    ("gdrive", "working_folder_id"),
    ("gmail", "address"),
    ("gmail", "password"),
    ("gmail", "error_mail_to"),
    ("upload", "drive"),
    ("upload", "photos"),
]


def test_insta360_configs_path_env_is_set():
    """conftest が `INSTA360_CONFIGS_PATH` 環境変数を設定している。"""
    assert "INSTA360_CONFIGS_PATH" in os.environ, (
        "conftest.py の autouse fixture が INSTA360_CONFIGS_PATH を設定していない"
    )

    configs_path = Path(os.environ["INSTA360_CONFIGS_PATH"])
    assert configs_path.exists(), (
        "INSTA360_CONFIGS_PATH ({}) のファイルが実在しない".format(configs_path)
    )
    assert configs_path.is_file(), (
        "INSTA360_CONFIGS_PATH ({}) はファイルでなければならない".format(configs_path)
    )


def test_insta360_configs_yaml_is_parseable_and_has_all_required_keys():
    """conftest が用意する YAML はパース可能で、必須キーをすべて含む。"""
    configs_path = Path(os.environ["INSTA360_CONFIGS_PATH"])
    data = yaml.safe_load(configs_path.read_text(encoding="utf-8"))

    assert isinstance(data, dict), "YAML のトップレベルは dict であること"

    for top, leaf in REQUIRED_KEYS:
        assert top in data, "必須トップレベルキー '{}' が欠落".format(top)
        assert leaf in data[top], (
            "必須キー '{}.{}' が欠落".format(top, leaf)
        )

    # upload.* は bool であること (後続の loader で型検証されるため)
    assert isinstance(data["upload"]["drive"], bool)
    assert isinstance(data["upload"]["photos"], bool)
