"""Insta360 MediaSDK の `stitcherSDKDemo` 起動コマンド組み立てロジックのテスト。

実バイナリは NDA 配布で CI に置けないため、コマンド配列の組み立てだけを pure 関数に切り出して
ここで検証する。実際の subprocess 起動は別の thin wrapper に閉じ込め、ユニットテストでは触らない。
"""
from __future__ import annotations

from pathlib import Path

import stitcher


SDK = "/insta360-auto-converter/MediaSDK"
WORK = "/insta360-auto-converter/apps"
MODELS = "/insta360-auto-converter/MediaSDK/models"


class TestBuildCommandVideo:
    def test_video_pair_includes_both_eyes_and_5760x2880(self):
        cmd = stitcher.build_command(
            sdk_path=SDK,
            working_folder=WORK,
            left_name="VID_00.insv",
            right_name="VID_10.insv",
            convert_name="VID_00_convert.mp4",
            is_image=False,
            stabilize=True,
        )
        # 入力ファイルが両目とも引数として渡る
        assert f"{WORK}/VID_00.insv" in cmd
        assert f"{WORK}/VID_10.insv" in cmd
        # 動画は 5760x2880, bitrate 200_000_000
        assert "5760x2880" in cmd
        assert "200000000" in cmd
        # stabilize=True なら -enable_flowstate あり
        assert "-enable_flowstate" in cmd
        # 出力先
        assert f"{WORK}/VID_00_convert.mp4" in cmd
        # SDK バイナリパス
        assert cmd[0] == f"{SDK}/stitcherSDKDemo"

    def test_video_includes_model_root_dir(self):
        """SDK の AI モデル参照 root を渡しておく (Issue #9 / 将来 aistitch 切替の準備)。

        現状は dynamicstitch を使うため model_root_dir 指定は厳密には不要だが、
        将来本番 Linux + NVIDIA GPU 環境で aistitch + ai_stitcher_v2.ins (X5 推奨)
        に切り替える余地を残すため、`-model_root_dir` を常に渡しておく
        (dynamicstitch 経路では SDK が無視するので副作用なし)。
        """
        cmd = stitcher.build_command(
            sdk_path=SDK,
            working_folder=WORK,
            left_name="VID_00.insv",
            right_name="LRV_01.lrv",
            convert_name="VID_00_convert.mp4",
            is_image=False,
            stabilize=True,
        )
        assert "-model_root_dir" in cmd
        idx = cmd.index("-model_root_dir")
        assert cmd[idx + 1].endswith("/MediaSDK/models")

    def test_video_without_stabilize_omits_flowstate(self):
        cmd = stitcher.build_command(
            sdk_path=SDK,
            working_folder=WORK,
            left_name="VID_00.insv",
            right_name="VID_10.insv",
            convert_name="VID_00_convert.mp4",
            is_image=False,
            stabilize=False,
        )
        assert "-enable_flowstate" not in cmd


class TestBuildCommandVideoSingleEye:
    """Insta360 X5 形式: `_00_` 単独動画 (`right_name=None`) を許可する (Issue #9)。

    旧実装は `is_image=False` かつ `right_name=None` で `ValueError` を投げていたため、
    X5 動画の場合に SDK ランナーまで到達できなかった。MediaSDK example の
    `VideoStitcher::SetInputPath(input_paths)` は input vector のサイズを問わない
    (1 でも 2 でも有効) ため、Python 側の guard を外して単一入力動画コマンドを許可する。
    """

    def test_x5_single_eye_video_uses_left_only_with_video_settings(self):
        cmd = stitcher.build_command(
            sdk_path=SDK,
            working_folder=WORK,
            left_name="VID_20260506_114009_00_161.insv",
            right_name=None,
            convert_name="VID_20260506_114009_00_161_convert.mp4",
            is_image=False,
            stabilize=True,
        )
        # 左目のみが入力に渡る
        assert f"{WORK}/VID_20260506_114009_00_161.insv" in cmd
        # `_10_` 入力は一切登場しない
        assert not any("_10_" in arg for arg in cmd)
        # 動画扱い: 5760x2880 + bitrate 200000000 + dynamicstitch
        assert "5760x2880" in cmd
        assert "200000000" in cmd
        assert "dynamicstitch" in cmd
        # stabilize=True なら flowstate 有効
        assert "-enable_flowstate" in cmd
        # 出力先
        assert f"{WORK}/VID_20260506_114009_00_161_convert.mp4" in cmd

    def test_x5_single_eye_video_does_not_raise(self):
        """旧実装は `ValueError` を投げていた。新実装は単一入力でも組み立てて返す。"""
        # 例外が出ないこと自体が回帰検査の主目的
        cmd = stitcher.build_command(
            sdk_path=SDK,
            working_folder=WORK,
            left_name="VID_x_00.insv",
            right_name=None,
            convert_name="VID_x_00_convert.mp4",
            is_image=False,
            stabilize=False,
        )
        # 帰ってきた cmd が list[str] であること (smoke)
        assert isinstance(cmd, list)
        assert all(isinstance(s, str) for s in cmd)


class TestBuildCommandImage:
    def test_image_uses_6080x3040_and_no_right_eye(self):
        cmd = stitcher.build_command(
            sdk_path=SDK,
            working_folder=WORK,
            left_name="IMG_00.insp",
            right_name=None,
            convert_name="IMG_00_convert.jpg",
            is_image=True,
            stabilize=True,
        )
        assert f"{WORK}/IMG_00.insp" in cmd
        # 写真は片目のみで右目は渡さない
        assert not any("_10_" in arg for arg in cmd)
        # 写真は 6080x3040
        assert "6080x3040" in cmd
        # 写真 / 動画共通: dynamicstitch
        assert "dynamicstitch" in cmd
        assert f"{WORK}/IMG_00_convert.jpg" in cmd

    def test_image_does_not_include_bitrate(self):
        cmd = stitcher.build_command(
            sdk_path=SDK,
            working_folder=WORK,
            left_name="IMG_00.insp",
            right_name=None,
            convert_name="IMG_00_convert.jpg",
            is_image=True,
            stabilize=True,
        )
        assert "-bitrate" not in cmd

    def test_image_keeps_dynamicstitch(self):
        """写真 (`.insp`) は既存 dynamicstitch で正常動作 (PR #10 / PR #12 で実機確認済) のため変更しない。

        動画だけが X5 dual-lens の都合で aistitch を要する。写真の SDK 経路は
        ImageStitcher で別ロジックなので影響なし。
        """
        cmd = stitcher.build_command(
            sdk_path=SDK,
            working_folder=WORK,
            left_name="IMG_00.insp",
            right_name=None,
            convert_name="IMG_00_convert.jpg",
            is_image=True,
            stabilize=True,
        )
        assert "dynamicstitch" in cmd
        assert "aistitch" not in cmd


class TestBuildExifToolCommand:
    def test_inserts_xmp_gpano_metadata(self):
        cmd = stitcher.build_exiftool_command("IMG_00_convert.jpg")
        # ExifTool バイナリは Image-ExifTool-12.10/exiftool で固定
        assert cmd[0].endswith("exiftool")
        # 4 種の XMP-GPano タグが入る
        joined = " ".join(cmd)
        assert "FullPanoHeightPixels" in joined
        assert "FullPanoWidthPixels" in joined
        assert "ProjectionType" in joined
        assert "UsePanoramaViewer" in joined
        # 対象ファイルが末尾
        assert cmd[-1] == "IMG_00_convert.jpg"


class TestBuildSpatialMediaCommand:
    def test_uses_python3_and_stereo_none(self):
        cmd = stitcher.build_spatial_media_command(
            convert_name="VID_00_convert-1.mp4",
            output_name="VID_00-1.mp4",
        )
        assert cmd[0] == "python3"
        assert "spatial-media/spatialmedia" in cmd
        assert "-i" in cmd
        assert "--stereo=none" in cmd
        # 入力 -> 出力 の順
        assert cmd[-2] == "VID_00_convert-1.mp4"
        assert cmd[-1] == "VID_00-1.mp4"
