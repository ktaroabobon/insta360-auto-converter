"""utils モジュールのユニットテスト。

特にログディレクトリ初期化の動作を検証する。プロダクションでは
`/insta360-auto-converter-data/logs` を作るが、コンテナ外 (テスト含む) では
書き込めないので、環境変数 INSTA360_LOGS_DIR で差し替えられる必要がある。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock


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


def test_send_mail_uses_app_config_yaml_credentials(monkeypatch):
    """`send_mail` の SMTP 認証取得が `AppConfig.gmail` (YAML 経由) になっていること。

    conftest.py で `INSTA360_CONFIGS_PATH` がプレースホルダ値の YAML
    (address="test@example.com", password="test-password",
     error_mail_to="ops@example.com") を指している前提。

    本テストは utils.py が `ConfigParser` から `load_app_config()` 経由に
    切り替わったことを検知する回帰テスト。
    """
    utils = _reload_utils()

    # smtplib.SMTP_SSL をモック化して、login() に渡される認証情報を捕捉する
    mock_server = MagicMock()
    mock_smtp_ssl = MagicMock(return_value=mock_server)
    monkeypatch.setattr(utils.smtplib, "SMTP_SSL", mock_smtp_ssl)

    utils.send_mail("recipient@example.com", "subject", "body")

    # SMTP_SSL は smtp.gmail.com:465 で開かれる (この呼出はモック越しで実 SMTP に到達しない)
    mock_smtp_ssl.assert_called_once_with("smtp.gmail.com", 465)

    # login は YAML の gmail.address / gmail.password で呼ばれること
    mock_server.login.assert_called_once_with("test@example.com", "test-password")

    # sendmail の差出人も YAML の gmail.address であること
    assert mock_server.sendmail.call_count == 1
    sendmail_args = mock_server.sendmail.call_args
    sent_from, sent_to, _body = sendmail_args[0]
    assert sent_from == "test@example.com"
    assert sent_to == "recipient@example.com"


def test_log_with_mail_out_routes_to_error_mail_to(monkeypatch):
    """`log("...", mail_out=True)` 経由で `send_mail` に渡る宛先が
    `AppConfig.gmail.error_mail_to` (= conftest プレースホルダの "ops@example.com")
    になっていること。

    これは utils モジュール内のハードコード or `ConfigParser` 参照が
    YAML 経由に置換されたことを保証する回帰テスト。
    """
    utils = _reload_utils()

    captured: dict = {}

    def fake_send_mail(to: str, subject: str, body: str) -> None:
        captured["to"] = to
        captured["subject"] = subject
        captured["body"] = body

    monkeypatch.setattr(utils, "send_mail", fake_send_mail)

    utils.log("something failed", mail_out=True)

    assert captured["to"] == "ops@example.com"
    # subject は固定文言、body は元のメッセージそのまま
    assert "insta360-auto-converter" in captured["subject"]
    assert captured["body"] == "something failed"
