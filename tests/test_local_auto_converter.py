"""ローカル入力モードのオーケストレータ (`local_auto_converter.process_pending`) のテスト。

実 SDK / 実 Google API は呼ばず、injected な runner / uploader を MagicMock で差し替えて
「呼び出される順番と引数」を検証する。

このモジュールが守るべき不変条件:

- `upload_targets.drive` が True のときのみ Drive (working folder 配下のアルバム名サブフォルダ)
  にアップロードする
- `upload_targets.photos` が True のときのみ Google Photos (アルバム名 = ローカルディレクトリ名)
  にアップロードする
- `mark_done` は **すべての有効なアップロード先が成功した後** に呼ぶ (失敗時は再試行できる状態を保つ)
- toggle off によるスキップはエラー扱いしない (= `mail_out=True` ログを出さない)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import local_auto_converter as lac
from app_config import AppConfig, AppConfigError, GdriveConfig, GmailConfig, UploadTargets


@pytest.fixture
def working_folder(tmp_path: Path) -> Path:
    """SDK 出力 / メタデータ注入の作業ディレクトリ。"""
    wf = tmp_path / "work"
    wf.mkdir()
    return wf


@pytest.fixture
def album_dir(tmp_path: Path) -> Path:
    """raw を置くアルバムディレクトリ。"""
    a = tmp_path / "trip-2026-04"
    a.mkdir()
    return a


def _stub_pending_video(album_dir: Path) -> dict:
    left = album_dir / "VID_a_00_001.insv"
    right = album_dir / "VID_a_10_001.insv"
    left.touch()
    right.touch()
    return {
        "left": left,
        "right": right,
        "is_image": False,
        "album_name": album_dir.name,
    }


def _stub_pending_video_x5(album_dir: Path) -> dict:
    """Insta360 X5 形式: `_00_` 単独動画 (右目 `_10_` 無し、Issue #9)。"""
    left = album_dir / "VID_20260506_114009_00_161.insv"
    left.touch()
    return {
        "left": left,
        "right": None,
        "is_image": False,
        "album_name": album_dir.name,
    }


def _stub_pending_photo(album_dir: Path) -> dict:
    left = album_dir / "IMG_a_00_001.insp"
    left.touch()
    return {
        "left": left,
        "right": None,
        "is_image": True,
        "album_name": album_dir.name,
    }


def _make_drive_subfolder():
    return {"id": "drive-subfolder-id", "name": "trip-2026-04",
            "mimeType": "application/vnd.google-apps.folder"}


# ---------------------------------------------------------------------------
# 既存挙動のリグレッション (両 toggle = True)
# ---------------------------------------------------------------------------


class TestProcessPendingPhoto:
    def test_uploads_jpg_to_both_drive_and_photos_then_marks_done(self, album_dir, working_folder):
        pending = _stub_pending_photo(album_dir)
        # SDK 実行を模してメタデータ注入後の最終出力を作る
        output_path = working_folder / "IMG_a_00_001.jpg"

        def fake_sdk_runner(pending_arg, convert_name, output_name, working):
            (working / output_name).write_bytes(b"fake-jpg")
        sdk_runner = MagicMock(side_effect=fake_sdk_runner)

        gs = MagicMock(name="GDriveService")
        gs.get_or_create_subfolder.return_value = _make_drive_subfolder()

        photos_uploader = MagicMock(name="upload_to_album")

        lac.process_pending(
            pending=pending,
            working_folder=str(working_folder),
            drive_parent_id="working-folder-id",
            gs=gs,
            sdk_runner=sdk_runner,
            upload_targets=UploadTargets(drive=True, photos=True),
            photos_uploader=photos_uploader,
        )

        # SDK runner が呼ばれた
        sdk_runner.assert_called_once()
        # Drive: アルバム名のサブフォルダを取得 → アップロード
        gs.get_or_create_subfolder.assert_called_once_with("working-folder-id", "trip-2026-04")
        gs.upload_file_to_folder.assert_called_once()
        upload_args = gs.upload_file_to_folder.call_args
        # 1st arg: ローカル出力パス, 2nd arg: subfolder dict, 3rd arg: mimetype
        assert upload_args.args[0] == str(output_path)
        assert upload_args.args[1] == _make_drive_subfolder()
        assert upload_args.args[2] == "image/jpeg"
        # Photos: album=ディレクトリ名 で 1 回呼ばれる
        photos_uploader.assert_called_once_with(str(output_path), "trip-2026-04")
        # done マーカー
        assert (album_dir / "IMG_a_00_001.insp.done").exists()


class TestProcessPendingVideo:
    def test_uploads_each_split_part_to_both_destinations(self, album_dir, working_folder):
        pending = _stub_pending_video(album_dir)

        # SDK runner は分割後の動画ファイル群を作る (split 済み 2 本想定)
        def fake_sdk_runner(pending_arg, convert_name, output_name, working):
            (working / "VID_a_00_001-1.mp4").write_bytes(b"part1")
            (working / "VID_a_00_001-2.mp4").write_bytes(b"part2")
        sdk_runner = MagicMock(side_effect=fake_sdk_runner)

        gs = MagicMock(name="GDriveService")
        gs.get_or_create_subfolder.return_value = _make_drive_subfolder()
        photos_uploader = MagicMock()

        lac.process_pending(
            pending=pending,
            working_folder=str(working_folder),
            drive_parent_id="working-folder-id",
            gs=gs,
            sdk_runner=sdk_runner,
            upload_targets=UploadTargets(drive=True, photos=True),
            photos_uploader=photos_uploader,
            split_outputs=["VID_a_00_001-1.mp4", "VID_a_00_001-2.mp4"],
        )

        # 両方の split 部分が Drive と Photos に上がる
        assert gs.upload_file_to_folder.call_count == 2
        assert photos_uploader.call_count == 2
        # mimetype は video/mp4
        for call in gs.upload_file_to_folder.call_args_list:
            assert call.args[2] == "video/mp4"
        # Photos の album は揃って "trip-2026-04"
        for call in photos_uploader.call_args_list:
            assert call.args[1] == "trip-2026-04"
        # done マーカーは左目に対して 1 つだけ
        assert (album_dir / "VID_a_00_001.insv.done").exists()


class TestProcessPendingVideoX5:
    """Insta360 X5 単独動画 (`right=None`) でも orchestrator が完走すること (Issue #9)。

    `process_pending` 自体は `pending["right"]` を直接参照しない (右目は SDK runner 内部でのみ使う)
    が、X5 ケースが来たときの不変条件を回帰検査として明示する:
      - SDK runner は 1 回呼ばれる
      - 出力は Drive / Photos 両方に上がる (split 後の 1 本)
      - `.done` マーカーが左目に対して付く
    """

    def test_x5_single_eye_video_uploads_and_marks_done(self, album_dir, working_folder):
        pending = _stub_pending_video_x5(album_dir)

        # SDK runner は分割後 1 本の動画ファイルを作る (X5 短尺想定)
        def fake_sdk_runner(pending_arg, convert_name, output_name, working):
            (working / "VID_20260506_114009_00_161-1.mp4").write_bytes(b"part1")
        sdk_runner = MagicMock(side_effect=fake_sdk_runner)

        gs = MagicMock(name="GDriveService")
        gs.get_or_create_subfolder.return_value = _make_drive_subfolder()
        photos_uploader = MagicMock()

        lac.process_pending(
            pending=pending,
            working_folder=str(working_folder),
            drive_parent_id="working-folder-id",
            gs=gs,
            sdk_runner=sdk_runner,
            upload_targets=UploadTargets(drive=True, photos=True),
            photos_uploader=photos_uploader,
            split_outputs=["VID_20260506_114009_00_161-1.mp4"],
        )

        # SDK runner は 1 回呼ばれた
        sdk_runner.assert_called_once()
        # 動画なので mimetype は video/mp4
        gs.upload_file_to_folder.assert_called_once()
        assert gs.upload_file_to_folder.call_args.args[2] == "video/mp4"
        # Photos も 1 回
        photos_uploader.assert_called_once()
        # 左目に対して .done マーカー
        assert (album_dir / "VID_20260506_114009_00_161.insv.done").exists()


class TestProcessPendingFailure:
    def test_does_not_mark_done_when_sdk_runner_fails(self, album_dir, working_folder):
        pending = _stub_pending_photo(album_dir)
        sdk_runner = MagicMock(side_effect=RuntimeError("SDK exploded"))
        gs = MagicMock()
        photos_uploader = MagicMock()

        with pytest.raises(RuntimeError):
            lac.process_pending(
                pending=pending,
                working_folder=str(working_folder),
                drive_parent_id="wf",
                gs=gs,
                sdk_runner=sdk_runner,
                upload_targets=UploadTargets(drive=True, photos=True),
                photos_uploader=photos_uploader,
            )

        # 失敗時はマーカーを作らない (= 次の周回で再試行可能)
        assert not (album_dir / "IMG_a_00_001.insp.done").exists()
        # Photos / Drive にも上がらない
        gs.upload_file_to_folder.assert_not_called()
        photos_uploader.assert_not_called()


# ---------------------------------------------------------------------------
# UploadTargets ゲート (Task 3.1 の対象テスト群)
# ---------------------------------------------------------------------------


class TestProcessPendingDriveOnly:
    """`UploadTargets(drive=True, photos=False)`: Drive のみアップロード。"""

    def test_drive_only_skips_photos_and_marks_done(self, album_dir, working_folder):
        pending = _stub_pending_photo(album_dir)
        output_path = working_folder / "IMG_a_00_001.jpg"

        def fake_sdk_runner(pending_arg, convert_name, output_name, working):
            (working / output_name).write_bytes(b"fake-jpg")
        sdk_runner = MagicMock(side_effect=fake_sdk_runner)

        gs = MagicMock(name="GDriveService")
        gs.get_or_create_subfolder.return_value = _make_drive_subfolder()

        photos_uploader = MagicMock(name="upload_to_album")

        lac.process_pending(
            pending=pending,
            working_folder=str(working_folder),
            drive_parent_id="working-folder-id",
            gs=gs,
            sdk_runner=sdk_runner,
            upload_targets=UploadTargets(drive=True, photos=False),
            photos_uploader=photos_uploader,
        )

        # Drive のみ呼ばれる
        gs.get_or_create_subfolder.assert_called_once_with("working-folder-id", "trip-2026-04")
        gs.upload_file_to_folder.assert_called_once()
        upload_args = gs.upload_file_to_folder.call_args
        assert upload_args.args[0] == str(output_path)
        assert upload_args.args[1] == _make_drive_subfolder()
        assert upload_args.args[2] == "image/jpeg"

        # Photos uploader は呼ばれない
        photos_uploader.assert_not_called()

        # 有効先 (Drive) が成功したので .done マーカーが作られる
        assert (album_dir / "IMG_a_00_001.insp.done").exists()


class TestProcessPendingPhotosOnly:
    """`UploadTargets(drive=False, photos=True)`: Photos のみアップロード。"""

    def test_photos_only_skips_drive_and_marks_done(self, album_dir, working_folder):
        pending = _stub_pending_photo(album_dir)
        output_path = working_folder / "IMG_a_00_001.jpg"

        def fake_sdk_runner(pending_arg, convert_name, output_name, working):
            (working / output_name).write_bytes(b"fake-jpg")
        sdk_runner = MagicMock(side_effect=fake_sdk_runner)

        gs = MagicMock(name="GDriveService")
        photos_uploader = MagicMock(name="upload_to_album")

        lac.process_pending(
            pending=pending,
            working_folder=str(working_folder),
            drive_parent_id="working-folder-id",
            gs=gs,
            sdk_runner=sdk_runner,
            upload_targets=UploadTargets(drive=False, photos=True),
            photos_uploader=photos_uploader,
        )

        # Drive 関連は一切呼ばれない (subfolder 解決もアップロードも)
        gs.get_or_create_subfolder.assert_not_called()
        gs.upload_file_to_folder.assert_not_called()

        # Photos uploader のみ呼ばれる
        photos_uploader.assert_called_once_with(str(output_path), "trip-2026-04")

        # 有効先 (Photos) が成功したので .done マーカーが作られる
        assert (album_dir / "IMG_a_00_001.insp.done").exists()


class TestProcessPendingPartialFailure:
    """片方のみ有効な構成で、その有効先が例外を上げた場合 → `.done` 未作成。"""

    def test_drive_only_drive_failure_leaves_no_done_marker(self, album_dir, working_folder):
        pending = _stub_pending_photo(album_dir)

        def fake_sdk_runner(pending_arg, convert_name, output_name, working):
            (working / output_name).write_bytes(b"fake-jpg")
        sdk_runner = MagicMock(side_effect=fake_sdk_runner)

        gs = MagicMock(name="GDriveService")
        gs.get_or_create_subfolder.return_value = _make_drive_subfolder()
        # Drive 側がアップロード失敗
        gs.upload_file_to_folder.side_effect = RuntimeError("drive upload failed")

        photos_uploader = MagicMock(name="upload_to_album")

        with pytest.raises(RuntimeError):
            lac.process_pending(
                pending=pending,
                working_folder=str(working_folder),
                drive_parent_id="working-folder-id",
                gs=gs,
                sdk_runner=sdk_runner,
                upload_targets=UploadTargets(drive=True, photos=False),
                photos_uploader=photos_uploader,
            )

        # 有効先が失敗したので .done マーカーは作られない (次の周回で再試行)
        assert not (album_dir / "IMG_a_00_001.insp.done").exists()
        # Photos は無効なので呼ばれていない
        photos_uploader.assert_not_called()

    def test_photos_only_photos_failure_leaves_no_done_marker(self, album_dir, working_folder):
        pending = _stub_pending_photo(album_dir)

        def fake_sdk_runner(pending_arg, convert_name, output_name, working):
            (working / output_name).write_bytes(b"fake-jpg")
        sdk_runner = MagicMock(side_effect=fake_sdk_runner)

        gs = MagicMock(name="GDriveService")
        # Photos 側がアップロード失敗
        photos_uploader = MagicMock(
            name="upload_to_album",
            side_effect=RuntimeError("photos upload failed"),
        )

        with pytest.raises(RuntimeError):
            lac.process_pending(
                pending=pending,
                working_folder=str(working_folder),
                drive_parent_id="working-folder-id",
                gs=gs,
                sdk_runner=sdk_runner,
                upload_targets=UploadTargets(drive=False, photos=True),
                photos_uploader=photos_uploader,
            )

        # 有効先が失敗したので .done マーカーは作られない (次の周回で再試行)
        assert not (album_dir / "IMG_a_00_001.insp.done").exists()
        # Drive は無効なので一切呼ばれていない
        gs.get_or_create_subfolder.assert_not_called()
        gs.upload_file_to_folder.assert_not_called()


class TestProcessPendingSkipDoesNotAlertOperator:
    """toggle off による skip では `mail_out=True` ログ (= operator alert email) を出さない (Req 4.2)。"""

    def test_drive_only_skip_does_not_call_log_with_mail_out(
        self, album_dir, working_folder, monkeypatch
    ):
        pending = _stub_pending_photo(album_dir)

        def fake_sdk_runner(pending_arg, convert_name, output_name, working):
            (working / output_name).write_bytes(b"fake-jpg")
        sdk_runner = MagicMock(side_effect=fake_sdk_runner)

        gs = MagicMock(name="GDriveService")
        gs.get_or_create_subfolder.return_value = _make_drive_subfolder()

        photos_uploader = MagicMock(name="upload_to_album")

        # `local_auto_converter` モジュール内で参照される `log` 関数を観測する。
        # `from utils import log` でバインドされているので、モジュール属性として差し替える。
        mock_log = MagicMock(name="log")
        monkeypatch.setattr("local_auto_converter.log", mock_log)

        lac.process_pending(
            pending=pending,
            working_folder=str(working_folder),
            drive_parent_id="working-folder-id",
            gs=gs,
            sdk_runner=sdk_runner,
            upload_targets=UploadTargets(drive=True, photos=False),
            photos_uploader=photos_uploader,
        )

        # toggle off のスキップでは mail_out=True を伴うログは絶対に呼ばない。
        # (info ログとしての log() 自体は許容するが、operator alert email を発火しないこと)
        for call in mock_log.call_args_list:
            # mail_out は 2 つ目の positional または keyword 引数で渡される。
            # 2 引数版: log(msg, mail_out=True) または log(msg, True)
            args = call.args
            kwargs = call.kwargs
            mail_out_pos = args[1] if len(args) >= 2 else False
            mail_out_kw = kwargs.get("mail_out", False)
            assert mail_out_pos is not True, (
                "log() called with mail_out=True (positional) on skip: {}".format(call)
            )
            assert mail_out_kw is not True, (
                "log() called with mail_out=True (keyword) on skip: {}".format(call)
            )

    def test_photos_only_skip_does_not_call_log_with_mail_out(
        self, album_dir, working_folder, monkeypatch
    ):
        pending = _stub_pending_photo(album_dir)

        def fake_sdk_runner(pending_arg, convert_name, output_name, working):
            (working / output_name).write_bytes(b"fake-jpg")
        sdk_runner = MagicMock(side_effect=fake_sdk_runner)

        gs = MagicMock(name="GDriveService")
        photos_uploader = MagicMock(name="upload_to_album")

        mock_log = MagicMock(name="log")
        monkeypatch.setattr("local_auto_converter.log", mock_log)

        lac.process_pending(
            pending=pending,
            working_folder=str(working_folder),
            drive_parent_id="working-folder-id",
            gs=gs,
            sdk_runner=sdk_runner,
            upload_targets=UploadTargets(drive=False, photos=True),
            photos_uploader=photos_uploader,
        )

        for call in mock_log.call_args_list:
            args = call.args
            kwargs = call.kwargs
            mail_out_pos = args[1] if len(args) >= 2 else False
            mail_out_kw = kwargs.get("mail_out", False)
            assert mail_out_pos is not True, (
                "log() called with mail_out=True (positional) on skip: {}".format(call)
            )
            assert mail_out_kw is not True, (
                "log() called with mail_out=True (keyword) on skip: {}".format(call)
            )


# ---------------------------------------------------------------------------
# main() の起動時検証 + UploadTargets ログ + AppConfigError 時の運用者通知
# (Task 4.3 = LocalStartupValidator)
# ---------------------------------------------------------------------------


def _fake_app_config(*, drive: bool = True, photos: bool = True) -> AppConfig:
    """テスト用の `AppConfig` を組む。toggle 値だけ自由に差し替えられる。"""
    return AppConfig(
        gdrive=GdriveConfig(
            drive_id="test-drive-id",
            working_folder_id="test-working-folder-id",
        ),
        gmail=GmailConfig(
            address="test@example.com",
            password="test-password",
            error_mail_to="ops@example.com",
        ),
        upload=UploadTargets(drive=drive, photos=photos),
    )


class _SleepCalledOnce(BaseException):
    """`time.sleep` を 1 度呼んだ時点で main() の `while True` を強制離脱させるためのセンチネル。

    `BaseException` を継承するのは、main() の broad `except Exception` で
    握りつぶされないため。
    """


class TestMainStartupLog:
    """Req 4.1: main() がループ突入直前に `uploads enabled: drive=..., photos=...` を 1 回出す。"""

    def test_logs_resolved_targets_at_startup_once(self, monkeypatch):
        # AppConfig は load_app_config を差し替えて返却 (drive=true, photos=false で確認)
        cfg = _fake_app_config(drive=True, photos=False)
        monkeypatch.setattr("local_auto_converter.load_app_config", lambda: cfg)

        # GDriveService は import 副作用を避けるため MagicMock 化 (init は通る)
        monkeypatch.setattr(
            "local_auto_converter.GDriveService",
            MagicMock(return_value=MagicMock(name="gs-instance")),
        )

        # 空アルバム → process_pending を呼ばずに `time.sleep` まで到達させる
        monkeypatch.setattr("local_auto_converter.list_album_dirs", lambda root: [])

        # `time.sleep` を 1 回呼んだら例外で `while True` を抜ける
        sleep_calls: list[int] = []

        def _abort_sleep(_secs):
            sleep_calls.append(_secs)
            raise _SleepCalledOnce()

        monkeypatch.setattr("local_auto_converter.time.sleep", _abort_sleep)

        # ログを観測
        mock_log = MagicMock(name="log")
        monkeypatch.setattr("local_auto_converter.log", mock_log)

        # main() を実行: _SleepCalledOnce で離脱 (broad except を BaseException で貫通)
        with pytest.raises(_SleepCalledOnce):
            lac.main()

        # `uploads enabled: drive=true, photos=false` を含む info ログ行が **1 回だけ** 出る
        startup_log_calls = [
            call
            for call in mock_log.call_args_list
            if call.args
            and isinstance(call.args[0], str)
            and "uploads enabled:" in call.args[0]
        ]
        assert len(startup_log_calls) == 1, (
            "expected exactly 1 startup log line containing 'uploads enabled:', "
            "got {}: {}".format(len(startup_log_calls), startup_log_calls)
        )
        startup_msg = startup_log_calls[0].args[0]
        assert "drive=true" in startup_msg
        assert "photos=false" in startup_msg
        # 起動ログは info (= mail_out=True を伴わない)
        startup_kwargs = startup_log_calls[0].kwargs
        startup_args = startup_log_calls[0].args
        mail_out_pos = startup_args[1] if len(startup_args) >= 2 else False
        mail_out_kw = startup_kwargs.get("mail_out", False)
        assert mail_out_pos is not True
        assert mail_out_kw is not True


class TestMainAppConfigErrorAlertsAndExits:
    """Req 1.6 / 4.3: AppConfigError 発生時に operator alert email + SystemExit(1)。"""

    def test_app_config_error_logs_with_mail_out_true_and_exits_1(self, monkeypatch):
        def _broken_loader():
            raise AppConfigError(
                "upload.drive and upload.photos are both false; "
                "at least one upload destination must be enabled"
            )

        monkeypatch.setattr("local_auto_converter.load_app_config", _broken_loader)

        # ログを観測
        mock_log = MagicMock(name="log")
        monkeypatch.setattr("local_auto_converter.log", mock_log)

        with pytest.raises(SystemExit) as exc_info:
            lac.main()

        # exit code = 1
        assert exc_info.value.code == 1

        # mail_out=True を伴う log() 呼出が少なくとも 1 回ある
        mail_out_calls = []
        for call in mock_log.call_args_list:
            args = call.args
            kwargs = call.kwargs
            mail_out_pos = args[1] if len(args) >= 2 else False
            mail_out_kw = kwargs.get("mail_out", False)
            if mail_out_pos is True or mail_out_kw is True:
                mail_out_calls.append(call)

        assert len(mail_out_calls) >= 1, (
            "expected at least one log() call with mail_out=True on AppConfigError, "
            "got log calls: {}".format(mock_log.call_args_list)
        )
