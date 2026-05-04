"""アプリケーション設定 (configs.yaml) のロード + 検証 + 型付き dataclass 化。

このモジュールは pure (副作用は YAML ファイルの read のみ)。
他の `apps/` 配下モジュールへ依存しない (テスト容易性のため)。

主な責務:

- `configs.yaml` を `yaml.safe_load` で読み、必須キーを検証する
- 不変な dataclass (`AppConfig` / `GdriveConfig` / `GmailConfig` / `UploadTargets`) を返す
- 型不一致 / 必須キー欠落 / 両 toggle false 等の不正設定はすべて `AppConfigError` で fail-fast
- `configs.txt` への fallback は **一切行わない** (Req 3.5)

詳細は `.kiro/specs/selective-upload-targets/design.md` の "AppConfigLoader" 節を参照。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


# ----------------------------------------------------------------------------
# Public Errors
# ----------------------------------------------------------------------------


class AppConfigError(RuntimeError):
    """設定ファイルの不在 / パース失敗 / 必須キー欠落 / 不正な組合せで raise される。"""


# ----------------------------------------------------------------------------
# Public Data Models (frozen dataclasses)
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class GdriveConfig:
    drive_id: str
    working_folder_id: str


@dataclass(frozen=True)
class GmailConfig:
    address: str
    password: str
    error_mail_to: str


@dataclass(frozen=True)
class UploadTargets:
    drive: bool
    photos: bool

    def has_any_enabled(self) -> bool:
        """少なくとも 1 つのアップロード先が有効か返す。"""
        return self.drive or self.photos


@dataclass(frozen=True)
class AppConfig:
    gdrive: GdriveConfig
    gmail: GmailConfig
    upload: UploadTargets


# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------


DEFAULT_CONFIG_PATH: Path = Path("/insta360-auto-converter-data/configs.yaml")
"""コンテナ運用前提の既定パス。env / 引数で上書き可能。"""

_ENV_PATH_KEY = "INSTA360_CONFIGS_PATH"


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def load_app_config(path: Path | None = None) -> AppConfig:
    """`configs.yaml` を読み、検証済みの `AppConfig` を返す。

    パスの解決優先順:
    1. `path` 引数 (明示渡し)
    2. 環境変数 `INSTA360_CONFIGS_PATH`
    3. `DEFAULT_CONFIG_PATH`

    エラー時は `AppConfigError` を送出する。
    """
    resolved_path = _resolve_path(path)

    if not resolved_path.is_file():
        raise AppConfigError(
            "configs.yaml not found at {}".format(resolved_path)
        )

    raw_text = _read_text(resolved_path)
    data = _parse_yaml(raw_text, resolved_path)

    if not isinstance(data, dict):
        raise AppConfigError(
            "configs.yaml at {} must be a YAML mapping at the top level".format(
                resolved_path
            )
        )

    gdrive = _build_gdrive(data)
    gmail = _build_gmail(data)
    upload = _build_upload_targets(data)

    return AppConfig(gdrive=gdrive, gmail=gmail, upload=upload)


def format_upload_targets(targets: UploadTargets) -> str:
    """起動時ログ用の表示文字列を返す (e.g. ``drive=true, photos=false``)。"""
    return "drive={}, photos={}".format(
        "true" if targets.drive else "false",
        "true" if targets.photos else "false",
    )


# ----------------------------------------------------------------------------
# Internal helpers (pure)
# ----------------------------------------------------------------------------


def _resolve_path(path: Path | None) -> Path:
    if path is not None:
        return Path(path)
    env_value = os.environ.get(_ENV_PATH_KEY)
    if env_value:
        return Path(env_value)
    return DEFAULT_CONFIG_PATH


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        # is_file() で先にハンドル済みだが念のため。
        raise AppConfigError(
            "failed to read configs.yaml at {}: {}".format(path, exc)
        ) from exc


def _parse_yaml(raw_text: str, path: Path) -> Any:
    try:
        return yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise AppConfigError(
            "failed to parse configs.yaml at {}: {}".format(path, exc)
        ) from exc


def _require_section(data: dict, section_key: str) -> dict:
    if section_key not in data or data[section_key] is None:
        raise AppConfigError(
            "required key '{}' is missing in configs.yaml".format(section_key)
        )
    section = data[section_key]
    if not isinstance(section, dict):
        raise AppConfigError(
            "required key '{}' in configs.yaml must be a mapping".format(section_key)
        )
    return section


def _require_non_empty_string(section: dict, section_key: str, field: str) -> str:
    full_key = "{}.{}".format(section_key, field)
    if field not in section or section[field] is None:
        raise AppConfigError(
            "required key '{}' is missing in configs.yaml".format(full_key)
        )
    value = section[field]
    if not isinstance(value, str):
        raise AppConfigError(
            "{} must be a string, got {}".format(full_key, type(value).__name__)
        )
    if value == "":
        raise AppConfigError(
            "required key '{}' is missing in configs.yaml (empty string is not allowed)".format(
                full_key
            )
        )
    return value


def _require_strict_bool(section: dict, section_key: str, field: str) -> bool:
    full_key = "{}.{}".format(section_key, field)
    if field not in section or section[field] is None:
        raise AppConfigError(
            "required key '{}' is missing in configs.yaml".format(full_key)
        )
    value = section[field]
    # YAML の `true`/`false` 以外 (文字列、int 等) はすべて型エラー扱い。
    # bool は int の subclass なので isinstance チェック順序に注意。
    if not isinstance(value, bool):
        raise AppConfigError(
            "{} must be a bool (boolean), got {}".format(full_key, type(value).__name__)
        )
    return value


def _build_gdrive(data: dict) -> GdriveConfig:
    section = _require_section(data, "gdrive")
    return GdriveConfig(
        drive_id=_require_non_empty_string(section, "gdrive", "drive_id"),
        working_folder_id=_require_non_empty_string(section, "gdrive", "working_folder_id"),
    )


def _build_gmail(data: dict) -> GmailConfig:
    section = _require_section(data, "gmail")
    return GmailConfig(
        address=_require_non_empty_string(section, "gmail", "address"),
        password=_require_non_empty_string(section, "gmail", "password"),
        error_mail_to=_require_non_empty_string(section, "gmail", "error_mail_to"),
    )


def _build_upload_targets(data: dict) -> UploadTargets:
    section = _require_section(data, "upload")
    drive = _require_strict_bool(section, "upload", "drive")
    photos = _require_strict_bool(section, "upload", "photos")
    if not drive and not photos:
        raise AppConfigError(
            "upload.drive and upload.photos are both false; "
            "at least one upload destination must be enabled"
        )
    return UploadTargets(drive=drive, photos=photos)
