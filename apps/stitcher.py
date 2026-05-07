"""Insta360 MediaSDK / ExifTool / spatial-media のコマンド組み立てを担う pure 関数群。

実際の `subprocess` 起動は呼び出し側 (insta360_auto_converter.py / local_auto_converter.py)
に残し、ここでは「どんな引数列を渡すか」だけを確定させる。これにより:

- SDK バイナリ (NDA 配布) が無い CI 環境でもコマンド組み立てロジックをテスト可能
- 動画 / 写真の分岐や stabilize フラグの取り扱いを明示的に検証できる

引数命名は既存実装 (`apps/insta360_auto_converter.py` 内のインライン版) と完全に揃える。
"""
from __future__ import annotations

from typing import Optional


# 動画 / 写真それぞれの 360 出力解像度。Insta360 MediaSDK の既存運用に合わせている。
VIDEO_OUTPUT_SIZE = "5760x2880"
IMAGE_OUTPUT_SIZE = "6080x3040"
VIDEO_BITRATE = "200000000"

# stitch_type:
# - dynamicstitch: 写真 / 動画とも実機 (Mac+Docker emulation) でフレーム描画ができる
# - aistitch: Insta360 公式は X5 で推奨 (`ai_stitcher_v2.ins` 使用) だが NVIDIA CUDA 必須。
#   開発環境 (Mac + Docker linux/amd64 emulation) では空 mp4 を吐くため切替を見送り。
#   本番 Linux + NVIDIA GPU 環境で再評価する余地あり (将来 issue 化検討)。
VIDEO_STITCH_TYPE = "dynamicstitch"
IMAGE_STITCH_TYPE = "dynamicstitch"

# AI stitching を選択した場合のモデルファイル root。dynamicstitch でも副作用なく渡せる。
SDK_MODEL_ROOT_DIR = "/insta360-auto-converter/MediaSDK/models"

# vendored ツールの実行コマンド
EXIFTOOL_BIN = "./Image-ExifTool-12.10/exiftool"
SPATIAL_MEDIA_BIN = "spatial-media/spatialmedia"


def build_command(
    sdk_path: str,
    working_folder: str,
    left_name: str,
    right_name: Optional[str],
    convert_name: str,
    is_image: bool,
    stabilize: bool,
) -> list[str]:
    """`stitcherSDKDemo` 起動コマンドを組み立てて返す。

    呼び出し側で `subprocess.Popen(" ".join(cmd), shell=True)` のように
    既存の起動方法に渡せる文字列リストを返す。
    """
    cmd: list[str] = [
        f"{sdk_path}/stitcherSDKDemo",
        "-inputs",
        f"{working_folder}/{left_name}",
    ]
    if not is_image:
        # ONE X (~2018) は左/右目で 2 ファイル、X5 (2024-) は dual-lens を 1 ファイルに統合する。
        # MediaSDK の `-inputs` は可変長 vector を取るため、ペア有無でそのまま分岐できる。
        if right_name is not None:
            cmd.append(f"{working_folder}/{right_name}")
        cmd += ["-output_size", VIDEO_OUTPUT_SIZE, "-bitrate", VIDEO_BITRATE]
        stitch_type = VIDEO_STITCH_TYPE
    else:
        cmd += ["-output_size", IMAGE_OUTPUT_SIZE]
        stitch_type = IMAGE_STITCH_TYPE
    cmd += ["-stitch_type", stitch_type]
    # AI stitching は `-model_root_dir` 配下の `ai_stitcher_v2.ins` 等を必要とするため
    # 常に渡す。dynamicstitch (写真側) も渡しておいて副作用は無い。
    cmd += ["-model_root_dir", SDK_MODEL_ROOT_DIR]
    if stabilize:
        cmd.append("-enable_flowstate")
    cmd += ["-output", f"{working_folder}/{convert_name}"]
    return cmd


def build_exiftool_command(convert_name: str) -> list[str]:
    """ExifTool で XMP-GPano メタデータを写真に注入するコマンド列を返す。"""
    return [
        EXIFTOOL_BIN,
        '-XMP-GPano:FullPanoHeightPixels="3040"',
        '-XMP-GPano:FullPanoWidthPixels="6080"',
        '-XMP-GPano:ProjectionType="equirectangular"',
        '-XMP-GPano:UsePanoramaViewer="True"',
        convert_name,
    ]


def build_spatial_media_command(convert_name: str, output_name: str) -> list[str]:
    """Google `spatial-media` で 360° 動画 atom を MP4 に注入するコマンド列を返す。"""
    return [
        "python3",
        SPATIAL_MEDIA_BIN,
        "-i",
        "--stereo=none",
        convert_name,
        output_name,
    ]
