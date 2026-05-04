"""ローカル入力モードのオーケストレータ (`local_auto_converter.process_pending`) のテスト。

実 SDK / 実 Google API は呼ばず、injected な runner / uploader を MagicMock で差し替えて
「呼び出される順番と引数」を検証する。

このモジュールが守るべき不変条件:

- 動画 / 写真ともに、最終出力を **Drive と Photos の両方** にアップロードする
- Drive は working folder 配下の **アルバム名サブフォルダ** に置く (なければ作る)
- Photos のアルバム名 = ローカルディレクトリ名
- `mark_done` は **すべてのアップロードが終わった後** に呼ぶ (失敗時は再試行できる状態を保つ)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import local_auto_converter as lac


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
                photos_uploader=photos_uploader,
            )

        # 失敗時はマーカーを作らない (= 次の周回で再試行可能)
        assert not (album_dir / "IMG_a_00_001.insp.done").exists()
        # Photos / Drive にも上がらない
        gs.upload_file_to_folder.assert_not_called()
        photos_uploader.assert_not_called()
