"""`apps/app_config.py` の AppConfigLoader に対するユニットテスト (Tier 1)。

このテストは TDD の **Red フェーズ** として作られている。
本実装 (`apps/app_config.py`) は task 2.2 で書く予定なので、
このファイルは現状すべて import error で fail する想定。

検証対象 (design.md "AppConfigLoader" 節 / requirements 1.1, 1.6, 3.1-3.5 由来):

- 正常な YAML をロードして `AppConfig` を返すこと (gdrive/gmail/upload 全フィールド保持)
- ファイル不在で `AppConfigError`、メッセージにファイルパスを含む
- YAML パース失敗で `AppConfigError`、メッセージにパースエラー要因またはパスを含む
- 必須キー欠落 (gdrive.drive_id 等) で `AppConfigError`、メッセージに欠落キー名を含む
- 型不一致 (`upload.drive` が文字列等) で `AppConfigError`、メッセージにキー名と期待型を含む
- `upload.drive` と `upload.photos` の両 false で `AppConfigError`、メッセージで両キーを名指す
- `INSTA360_CONFIGS_PATH` 環境変数によるパス上書き
- `configs.yaml` 不在で同じディレクトリに `configs.txt` が存在しても **fallback しない**
"""
from __future__ import annotations

from pathlib import Path

import pytest

# 注: 本実装が無い段階では import 自体が失敗する。
# TDD Red フェーズの観測可能な失敗として、これは想定どおり。
from app_config import (  # noqa: E402  (test-time import)
    AppConfig,
    AppConfigError,
    GdriveConfig,
    GmailConfig,
    UploadTargets,
    load_app_config,
)


# テスト用に使い回す、すべての必須キーを含む正常な YAML 文字列。
_VALID_YAML = """\
gdrive:
  drive_id: "drive-id-xyz"
  working_folder_id: "working-folder-abc"
gmail:
  address: "alerts@example.com"
  password: "app-password"
  error_mail_to: "ops@example.com"
upload:
  drive: true
  photos: true
"""


def _write_yaml(path: Path, content: str) -> Path:
    """テストで使う YAML ファイルを書き出すヘルパ。"""
    path.write_text(content, encoding="utf-8")
    return path


# -- 正常系 -------------------------------------------------------------------


class TestLoadAppConfigValidYaml:
    """正常な YAML を渡したときの AppConfig 構築を検証する (Req 3.1, 3.4)。"""

    def test_returns_app_config_with_all_fields(self, tmp_path: Path, monkeypatch):
        configs_path = _write_yaml(tmp_path / "configs.yaml", _VALID_YAML)
        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(configs_path))

        cfg = load_app_config()

        assert isinstance(cfg, AppConfig)

        # gdrive
        assert isinstance(cfg.gdrive, GdriveConfig)
        assert cfg.gdrive.drive_id == "drive-id-xyz"
        assert cfg.gdrive.working_folder_id == "working-folder-abc"

        # gmail
        assert isinstance(cfg.gmail, GmailConfig)
        assert cfg.gmail.address == "alerts@example.com"
        assert cfg.gmail.password == "app-password"
        assert cfg.gmail.error_mail_to == "ops@example.com"

        # upload
        assert isinstance(cfg.upload, UploadTargets)
        assert cfg.upload.drive is True
        assert cfg.upload.photos is True

    def test_explicit_path_argument_takes_priority_over_env(self, tmp_path: Path, monkeypatch):
        """path 引数を明示渡しした場合は env を無視してそのパスから読む。"""
        explicit = _write_yaml(tmp_path / "explicit.yaml", _VALID_YAML)

        # env は別の存在しないパスに向けても、明示パスが優先される
        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(tmp_path / "non-existent.yaml"))

        cfg = load_app_config(explicit)

        assert cfg.gdrive.drive_id == "drive-id-xyz"


# -- 異常系: ファイル不在 ----------------------------------------------------


class TestLoadAppConfigMissingFile:
    """ファイル不在で AppConfigError、メッセージに path を含む (Req 3.2, 3.5)。"""

    def test_raises_app_config_error_when_file_missing(self, tmp_path: Path, monkeypatch):
        missing_path = tmp_path / "does-not-exist.yaml"
        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(missing_path))

        with pytest.raises(AppConfigError) as excinfo:
            load_app_config()

        # メッセージにパスを含む (どのファイルが見つからなかったか追跡できるように)
        assert str(missing_path) in str(excinfo.value)


# -- 異常系: YAML パース失敗 -------------------------------------------------


class TestLoadAppConfigMalformedYaml:
    """YAML パース失敗で AppConfigError、原因 or パスを含む (Req 3.2)。"""

    def test_raises_app_config_error_on_invalid_yaml(self, tmp_path: Path, monkeypatch):
        # 意図的に壊れた YAML (タブ + 不一致インデント)
        broken = "gdrive:\n  drive_id: 'unclosed\nupload: [::::"
        configs_path = _write_yaml(tmp_path / "configs.yaml", broken)
        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(configs_path))

        with pytest.raises(AppConfigError) as excinfo:
            load_app_config()

        msg = str(excinfo.value)
        # パスまたはパースエラー要因のいずれかを含むこと (運用者がどこで失敗したか追える)
        assert (str(configs_path) in msg) or ("parse" in msg.lower()) or ("yaml" in msg.lower())


# -- 異常系: 必須キー欠落 ----------------------------------------------------


class TestLoadAppConfigMissingRequiredKey:
    """必須キーが欠けると AppConfigError、メッセージに欠落キー名を含む (Req 3.3)。"""

    @pytest.mark.parametrize(
        "yaml_text, missing_key",
        [
            # gdrive.drive_id 欠落
            (
                """\
gdrive:
  working_folder_id: "wf-id"
gmail:
  address: "a@example.com"
  password: "p"
  error_mail_to: "o@example.com"
upload:
  drive: true
  photos: true
""",
                "drive_id",
            ),
            # gdrive.working_folder_id 欠落
            (
                """\
gdrive:
  drive_id: "d-id"
gmail:
  address: "a@example.com"
  password: "p"
  error_mail_to: "o@example.com"
upload:
  drive: true
  photos: true
""",
                "working_folder_id",
            ),
            # gmail.address 欠落
            (
                """\
gdrive:
  drive_id: "d-id"
  working_folder_id: "wf-id"
gmail:
  password: "p"
  error_mail_to: "o@example.com"
upload:
  drive: true
  photos: true
""",
                "address",
            ),
            # gmail.password 欠落
            (
                """\
gdrive:
  drive_id: "d-id"
  working_folder_id: "wf-id"
gmail:
  address: "a@example.com"
  error_mail_to: "o@example.com"
upload:
  drive: true
  photos: true
""",
                "password",
            ),
            # gmail.error_mail_to 欠落
            (
                """\
gdrive:
  drive_id: "d-id"
  working_folder_id: "wf-id"
gmail:
  address: "a@example.com"
  password: "p"
upload:
  drive: true
  photos: true
""",
                "error_mail_to",
            ),
            # upload.drive 欠落
            (
                """\
gdrive:
  drive_id: "d-id"
  working_folder_id: "wf-id"
gmail:
  address: "a@example.com"
  password: "p"
  error_mail_to: "o@example.com"
upload:
  photos: true
""",
                "drive",
            ),
            # upload.photos 欠落
            (
                """\
gdrive:
  drive_id: "d-id"
  working_folder_id: "wf-id"
gmail:
  address: "a@example.com"
  password: "p"
  error_mail_to: "o@example.com"
upload:
  drive: true
""",
                "photos",
            ),
        ],
        ids=[
            "gdrive.drive_id",
            "gdrive.working_folder_id",
            "gmail.address",
            "gmail.password",
            "gmail.error_mail_to",
            "upload.drive",
            "upload.photos",
        ],
    )
    def test_raises_with_missing_key_name(
        self, tmp_path: Path, monkeypatch, yaml_text: str, missing_key: str
    ):
        configs_path = _write_yaml(tmp_path / "configs.yaml", yaml_text)
        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(configs_path))

        with pytest.raises(AppConfigError) as excinfo:
            load_app_config()

        # 欠落キー名がエラーメッセージに含まれていること (運用者がどのキーを足せばよいか分かる)
        assert missing_key in str(excinfo.value)


# -- 異常系: 型不一致 --------------------------------------------------------


class TestLoadAppConfigTypeMismatch:
    """型不一致 (例: upload.drive が文字列) で AppConfigError、キー名と期待型を含む。

    design.md "Errors" 節:
        "upload.drive must be a boolean, got str"
    """

    def test_upload_drive_as_string_raises(self, tmp_path: Path, monkeypatch):
        bad_yaml = """\
gdrive:
  drive_id: "d-id"
  working_folder_id: "wf-id"
gmail:
  address: "a@example.com"
  password: "p"
  error_mail_to: "o@example.com"
upload:
  drive: "true"
  photos: true
"""
        configs_path = _write_yaml(tmp_path / "configs.yaml", bad_yaml)
        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(configs_path))

        with pytest.raises(AppConfigError) as excinfo:
            load_app_config()

        msg = str(excinfo.value)
        # キー名 (upload.drive のいずれか) が含まれること
        assert "drive" in msg
        # 期待型 (bool / boolean) が含まれること
        assert ("bool" in msg.lower())

    def test_upload_photos_as_int_raises(self, tmp_path: Path, monkeypatch):
        # YAML 上で photos: 1 (int) は bool ではないので拒否されるべき
        bad_yaml = """\
gdrive:
  drive_id: "d-id"
  working_folder_id: "wf-id"
gmail:
  address: "a@example.com"
  password: "p"
  error_mail_to: "o@example.com"
upload:
  drive: true
  photos: 1
"""
        configs_path = _write_yaml(tmp_path / "configs.yaml", bad_yaml)
        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(configs_path))

        with pytest.raises(AppConfigError) as excinfo:
            load_app_config()

        msg = str(excinfo.value)
        assert "photos" in msg
        assert "bool" in msg.lower()


# -- 異常系: 両 toggle false --------------------------------------------------


class TestLoadAppConfigBothUploadsFalse:
    """`upload.drive` と `upload.photos` の両方が false なら AppConfigError (Req 1.6)。"""

    def test_both_false_raises_with_both_keys_in_message(self, tmp_path: Path, monkeypatch):
        both_false_yaml = """\
gdrive:
  drive_id: "d-id"
  working_folder_id: "wf-id"
gmail:
  address: "a@example.com"
  password: "p"
  error_mail_to: "o@example.com"
upload:
  drive: false
  photos: false
"""
        configs_path = _write_yaml(tmp_path / "configs.yaml", both_false_yaml)
        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(configs_path))

        with pytest.raises(AppConfigError) as excinfo:
            load_app_config()

        msg = str(excinfo.value)
        # design.md の Errors 節に従い、両キーをメッセージで明示する
        assert "drive" in msg
        assert "photos" in msg


# -- env による上書き --------------------------------------------------------


class TestLoadAppConfigEnvPathOverride:
    """`INSTA360_CONFIGS_PATH` 環境変数による設定パス上書きが有効。"""

    def test_env_var_path_is_used(self, tmp_path: Path, monkeypatch):
        # env が指す側だけに valid yaml を置く。デフォルトパス (/insta360-auto-converter-data/configs.yaml)
        # はテスト環境で書けないので、env が読まれていることが確認できる。
        env_path = _write_yaml(tmp_path / "via-env.yaml", _VALID_YAML)
        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(env_path))

        cfg = load_app_config()

        # env 側の YAML が読めていること = env が反映された証拠
        assert cfg.gdrive.drive_id == "drive-id-xyz"
        assert cfg.upload.drive is True
        assert cfg.upload.photos is True


# -- INI fallback しないこと -------------------------------------------------


class TestLoadAppConfigNoFallbackToIni:
    """`configs.yaml` が無いとき、同じディレクトリに `configs.txt` があっても
    fallback してはならない (Req 3.5)。"""

    def test_does_not_fallback_to_configs_txt(self, tmp_path: Path, monkeypatch):
        # configs.yaml は意図的に作らない
        yaml_path = tmp_path / "configs.yaml"

        # 同じディレクトリに configs.txt (旧 INI) を置く
        configs_txt = tmp_path / "configs.txt"
        configs_txt.write_text(
            "[GDRIVE_INFO]\n"
            "drive_id = legacy-drive-id\n"
            "working_folder_id = legacy-wf-id\n"
            "[GMAIL_INFO]\n"
            "id = legacy@example.com\n"
            "pass = legacy-password\n"
            "error_mail_to = legacy-ops@example.com\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("INSTA360_CONFIGS_PATH", str(yaml_path))

        # configs.yaml が無いので AppConfigError が出るのが正しい挙動。
        # configs.txt にフォールバックして成功してはならない。
        with pytest.raises(AppConfigError):
            load_app_config()
