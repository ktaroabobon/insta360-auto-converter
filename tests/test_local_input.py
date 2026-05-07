"""ローカル入力モードの責務を担う `local_input` モジュールのユニットテスト。

このモジュールは「ローカルディレクトリからどの raw を次に処理すべきか」を決め、
ペアリング、出力ファイル名の導出、完了マーカーの扱いを担当する pure な関数群。
副作用 (SDK 呼び出し / Drive API / Photos API) はここに置かない。
"""
from __future__ import annotations

from pathlib import Path

import pytest

import local_input as li


class TestIsImage:
    def test_insp_is_image(self):
        assert li.is_image("VID_20260101_120000_00_001.insp") is True

    def test_insv_is_video(self):
        assert li.is_image("VID_20260101_120000_00_001.insv") is False


class TestPairRightName:
    def test_replaces_00_with_10(self):
        assert li.pair_right_name("VID_20260101_120000_00_001.insv") == "VID_20260101_120000_10_001.insv"

    def test_returns_none_for_image(self):
        # 写真は片目のみで右目ファイルは存在しない
        assert li.pair_right_name("IMG_20260101_120000_00_001.insp") is None


class TestDeriveOutputNames:
    def test_video(self):
        convert_name, output_name = li.derive_output_names("VID_20260101_120000_00_001.insv")
        assert convert_name == "VID_20260101_120000_00_001_convert.mp4"
        assert output_name == "VID_20260101_120000_00_001.mp4"

    def test_image(self):
        convert_name, output_name = li.derive_output_names("IMG_20260101_120000_00_001.insp")
        assert convert_name == "IMG_20260101_120000_00_001_convert.jpg"
        assert output_name == "IMG_20260101_120000_00_001.jpg"


class TestFindPending:
    def test_returns_none_for_empty_album(self, tmp_path: Path):
        assert li.find_pending(tmp_path) is None

    def test_returns_video_pair_when_both_eyes_present(self, tmp_path: Path):
        left = tmp_path / "VID_20260101_120000_00_001.insv"
        right = tmp_path / "VID_20260101_120000_10_001.insv"
        left.touch()
        right.touch()

        result = li.find_pending(tmp_path)

        assert result is not None
        assert result["left"] == left
        assert result["right"] == right
        assert result["is_image"] is False

    def test_returns_photo_with_no_right(self, tmp_path: Path):
        photo = tmp_path / "IMG_20260101_120000_00_001.insp"
        photo.touch()

        result = li.find_pending(tmp_path)

        assert result is not None
        assert result["left"] == photo
        assert result["right"] is None
        assert result["is_image"] is True

    def test_skips_already_done_pair(self, tmp_path: Path):
        left = tmp_path / "VID_20260101_120000_00_001.insv"
        right = tmp_path / "VID_20260101_120000_10_001.insv"
        left.touch()
        right.touch()
        # 完了マーカー (左目に対して 1 つ)
        (tmp_path / "VID_20260101_120000_00_001.insv.done").touch()

        assert li.find_pending(tmp_path) is None

    def test_skips_done_photo(self, tmp_path: Path):
        photo = tmp_path / "IMG_20260101_120000_00_001.insp"
        photo.touch()
        (tmp_path / "IMG_20260101_120000_00_001.insp.done").touch()

        assert li.find_pending(tmp_path) is None

    def test_video_pair_takes_priority_over_photo(self, tmp_path: Path):
        # 既存実装と同じく、動画ペアを写真より優先して返す
        left = tmp_path / "VID_a_00_001.insv"
        right = tmp_path / "VID_a_10_001.insv"
        left.touch()
        right.touch()
        photo = tmp_path / "IMG_b_00_001.insp"
        photo.touch()

        result = li.find_pending(tmp_path)

        assert result["is_image"] is False
        assert result["left"] == left

    def test_x5_single_eye_video_is_returned_as_pending(self, tmp_path: Path):
        """Insta360 X5 形式: `_00_` 単独 (右目 `_10_` 無し) も動画 pending として返す。

        ONE X (~2018) は dual-fisheye で `_00_*.insv` + `_10_*.insv` のペアを吐くが、
        X5 (2024-) は dual-lens を 1 ファイルに統合するため `_10_` を生成しない。
        旧実装はペア無しを skip していたため X5 動画が永遠に処理されない問題があり、
        ペア無しでも `right=None` の動画 pending を返すようにする (Issue #9)。
        """
        left = tmp_path / "VID_20260506_114009_00_161.insv"
        left.touch()

        result = li.find_pending(tmp_path)

        assert result is not None
        assert result["left"] == left
        assert result["right"] is None
        assert result["is_image"] is False
        assert result["album_name"] == tmp_path.name

    def test_x5_single_eye_video_with_done_marker_is_skipped(self, tmp_path: Path):
        """X5 単独動画も完了マーカー付きなら skip する (再処理しない)。"""
        left = tmp_path / "VID_x_00_001.insv"
        left.touch()
        (tmp_path / "VID_x_00_001.insv.done").touch()

        assert li.find_pending(tmp_path) is None

    def test_one_x_paired_video_still_returns_with_right(self, tmp_path: Path):
        """既存 ONE X 形式の `_00_` + `_10_` ペアが回帰なく従来どおり動くこと。"""
        left = tmp_path / "VID_a_00_001.insv"
        right = tmp_path / "VID_a_10_001.insv"
        left.touch()
        right.touch()

        result = li.find_pending(tmp_path)

        assert result["left"] == left
        assert result["right"] == right  # X5 と違いペアが解決される
        assert result["is_image"] is False

    def test_orphan_right_eye_video_is_ignored(self, tmp_path: Path):
        """`_10_` 単独 (左目無しで右目だけ) は処理対象にしない。

        `_10_` は ONE X 系の右目で、対応する `_00_` 無しに置かれることは仕様上想定外。
        万一あっても無視 (X5 単独サポートが `_10_` 単独ファイルにまで広がらないことを保証)。
        """
        (tmp_path / "VID_x_10_001.insv").touch()
        assert li.find_pending(tmp_path) is None

    def test_ignores_macos_metadata_files(self, tmp_path: Path):
        # macOS が作る `._foo.insv` のような AppleDouble は無視
        (tmp_path / "._VID_x_00_001.insv").touch()
        assert li.find_pending(tmp_path) is None

    def test_ignores_dot_processed_subdir(self, tmp_path: Path):
        # アーカイブ用の隠しサブディレクトリの中の raw は対象外
        processed = tmp_path / ".processed"
        processed.mkdir()
        (processed / "VID_x_00_001.insv").touch()
        (processed / "VID_x_10_001.insv").touch()

        assert li.find_pending(tmp_path) is None


class TestMarkDone:
    def test_creates_marker_next_to_left_file(self, tmp_path: Path):
        left = tmp_path / "VID_a_00_001.insv"
        left.touch()

        li.mark_done(left)

        assert (tmp_path / "VID_a_00_001.insv.done").exists()

    def test_idempotent_when_marker_already_exists(self, tmp_path: Path):
        left = tmp_path / "VID_a_00_001.insv"
        left.touch()
        (tmp_path / "VID_a_00_001.insv.done").touch()

        # 例外を投げず黙って返ること
        li.mark_done(left)
        assert (tmp_path / "VID_a_00_001.insv.done").exists()


class TestListAlbumDirs:
    def test_returns_only_immediate_subdirs(self, tmp_path: Path):
        (tmp_path / "trip-A").mkdir()
        (tmp_path / "trip-B").mkdir()
        (tmp_path / "loose-file.txt").touch()

        result = li.list_album_dirs(tmp_path)

        names = sorted(p.name for p in result)
        assert names == ["trip-A", "trip-B"]

    def test_skips_dotfiles_and_dot_processed(self, tmp_path: Path):
        (tmp_path / "trip-A").mkdir()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".processed").mkdir()

        result = li.list_album_dirs(tmp_path)

        names = sorted(p.name for p in result)
        assert names == ["trip-A"]

    def test_returns_empty_list_when_root_missing(self, tmp_path: Path):
        missing = tmp_path / "does-not-exist"
        assert li.list_album_dirs(missing) == []
