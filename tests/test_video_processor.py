"""apps/video_processor.py の VideoProcessor.split_video テスト。

Docker E2E (PR #12 / Issue #9 X5 動画動作確認) で発覚した path 不整合バグの回帰検査:

旧実装は「分割不要 (size < SIZE_LIMIT)」のときに **入力をそのまま返し**、
「分割必要」のときは **basename にしてから返す** という不整合があった。
呼び出し側 (`local_auto_converter._run_sdk_and_inject_metadata`) が
`f"{working_folder}/{out_name}"` で working_folder と再結合するため、
full path が入力されると path が二重結合されて `[Errno 2] No such file` で
upload が失敗していた。

修正後は **入力 path 形式によらず常に basename を返す** ことを保証する。
分割パス (>5GB) は moviepy/ffmpeg と巨大な実ファイルが必要で CI では検証不可なため、
ここでは分割不要パスの不変条件だけを TDD で固める。
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def vp():
    """VideoProcessor 単独 import (utils 経由の env 依存は conftest が処理)。"""
    from video_processor import VideoProcessor
    return VideoProcessor()


class TestSplitVideoNoSplitNeeded:
    """SIZE_LIMIT (7GB) 未満なら分割せず元ファイル名 (basename) を 1 件のリストで返す。"""

    def test_full_path_input_returns_basename_only(self, vp, tmp_path: Path):
        """full path を渡しても戻り値は basename のリスト (Issue #9 fix の核心)。"""
        video = tmp_path / "VID_20260309_180040_00_039_convert.mp4"
        video.write_bytes(b"fake mp4 content")  # 7GB 未満なら何でも OK

        result = vp.split_video(str(video))

        assert result == ["VID_20260309_180040_00_039_convert.mp4"]
        # 旧実装が返していた full path 形式は絶対に返らない
        assert all("/" not in r for r in result), \
            "split_video must return basename, not full path (regression for Issue #9)"

    def test_basename_input_returns_same_basename(self, vp, tmp_path: Path, monkeypatch):
        """basename を渡したケース (insta360_auto_converter.py:195 の Drive モード) も同 basename を返す。"""
        # video_processor は os.path.getsize を呼ぶため cwd 配下に実ファイルが必要
        monkeypatch.chdir(tmp_path)
        (tmp_path / "VID_a_00_001_convert.mp4").write_bytes(b"fake")

        result = vp.split_video("VID_a_00_001_convert.mp4")

        assert result == ["VID_a_00_001_convert.mp4"]

    def test_returns_single_element_list(self, vp, tmp_path: Path):
        """戻り値はリスト (空でも 1 件でも複数でもリスト)。後続の for ループで安全に扱えること。"""
        video = tmp_path / "VID_x.mp4"
        video.write_bytes(b"fake")

        result = vp.split_video(str(video))

        assert isinstance(result, list)
        assert len(result) == 1
