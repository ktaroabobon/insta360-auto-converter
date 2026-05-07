"""ローカル入力モードの「次に何を処理するか」と命名規約を担う pure な関数群。

副作用 (SDK 呼び出し / Drive / Photos) はここに置かない。`local_auto_converter.py`
側のメインループからこのモジュールの関数を呼んで、処理対象の決定とマーカー操作だけ任せる。

ファイル命名規約は Insta360 仕様を踏襲する:

- ONE X (~2018) 動画: `_00_*.insv` (左目) + `_10_*.insv` (右目) のペア
- X5 (2024-) 動画: `_00_*.insv` 単独 (dual-lens を 1 ファイルに統合、`_10_` 無し)
- 写真 (両カメラ共通): `_00_*.insp` 単独 (片目のみ)

完了マーカーは `<左目ファイル名>.done` で、同じディレクトリに置く。
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Optional


DONE_SUFFIX = ".done"
PROCESSED_DIR_NAME = ".processed"


def is_image(name: str) -> bool:
    """`.insp` (= 写真) なら True、`.insv` (= 動画) なら False。"""
    return name.endswith(".insp")


def pair_right_name(left_name: str) -> Optional[str]:
    """左目ファイル名から、ペアになる右目動画ファイル名を返す。

    写真 (`.insp`) は片目のみ存在するため None を返す。
    動画は `_00_` を `_10_` に置換した名前。
    """
    if is_image(left_name):
        return None
    return left_name.replace("_00_", "_10_")


def derive_output_names(left_name: str) -> tuple[str, str]:
    """raw のファイル名から、SDK 直後の中間ファイル名と最終出力ファイル名を導出する。

    動画: `foo_00_001.insv` -> (`foo_00_001_convert.mp4`, `foo_00_001.mp4`)
    写真: `foo_00_001.insp` -> (`foo_00_001_convert.jpg`, `foo_00_001.jpg`)
    """
    if is_image(left_name):
        convert = left_name.replace(".insp", "_convert.jpg")
        output = left_name.replace(".insp", ".jpg")
    else:
        convert = left_name.replace(".insv", "_convert.mp4")
        output = left_name.replace(".insv", ".mp4")
    return convert, output


def mark_done(left_path: Path) -> None:
    """完了マーカー `<left_path>.done` を作成する。既に存在する場合は何もしない。"""
    marker = left_path.with_suffix(left_path.suffix + DONE_SUFFIX)
    marker.touch(exist_ok=True)


def list_album_dirs(input_root: Path) -> list[Path]:
    """input_root の直下サブディレクトリ (= アルバム) を列挙して返す。

    - 隠しディレクトリ (先頭が `.`) は除外する (`.processed` などの内部用ディレクトリと衝突しないため)
    - input_root 自体が存在しない場合は空 list を返す (呼び出し側で「待機」と解釈)
    """
    if not input_root.exists() or not input_root.is_dir():
        return []
    return [p for p in sorted(input_root.iterdir()) if p.is_dir() and not p.name.startswith(".")]


def find_pending(album_dir: Path) -> Optional[dict]:
    """1 つのアルバムディレクトリから、次に処理すべき raw を 1 件返す。

    優先順位は既存の Drive モードに合わせて **動画ペア > 写真**。
    既に `<name>.done` マーカーがある raw はスキップする。
    macOS の AppleDouble (`._foo.insv`) は無視する。
    `.processed/` などの隠しサブディレクトリ内は探索しない (直下のみ)。

    返却 dict 形式:
      {'left': Path, 'right': Path | None, 'is_image': bool, 'album_name': str}
    該当無しなら None。
    """
    if not album_dir.exists() or not album_dir.is_dir():
        return None

    direct_files = [
        p for p in album_dir.iterdir()
        if p.is_file() and not p.name.startswith("._")
    ]
    names = {p.name for p in direct_files}

    def _is_done(name: str) -> bool:
        return f"{name}{DONE_SUFFIX}" in names

    left_videos = [p for p in direct_files if p.name.endswith(".insv") and "_00_" in p.name]
    right_videos = [p for p in direct_files if p.name.endswith(".insv") and "_10_" in p.name]
    left_photos = [p for p in direct_files if p.name.endswith(".insp") and "_00_" in p.name]

    # 動画優先 (best-effort のシャッフルで複数プロセス時の偏りを減らす)。
    # ONE X はペア (`_00_` + `_10_`)、X5 は `_00_` 単独 (`right=None` で返す)。
    random.shuffle(left_videos)
    for lv in left_videos:
        if _is_done(lv.name):
            continue
        right_name = pair_right_name(lv.name)
        right = next((rv for rv in right_videos if rv.name == right_name), None)
        return {
            "left": lv,
            "right": right,  # X5 形式 (ペア無し) は None
            "is_image": False,
            "album_name": album_dir.name,
        }

    # 写真は片目のみ
    random.shuffle(left_photos)
    for lp in left_photos:
        if _is_done(lp.name):
            continue
        return {
            "left": lp,
            "right": None,
            "is_image": True,
            "album_name": album_dir.name,
        }

    return None
