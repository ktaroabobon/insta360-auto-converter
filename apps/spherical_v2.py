"""Spherical Video V2 atom 注入モジュール.

PR #12 ユーザーフィードバック対応で追加 (2026-05): vendored の Google `spatial-media` は
v1.0 (uuid + XMP `<rdf:SphericalVideo>`) のみ注入で v2 atom を入れない。Google RFC では
"両方ある場合は v2 が優先" とされ、Android 版 Google Photos はサーバー transcode 後の
v2 atom (sv3d/st3d/proj/equi) を読む傾向 (uuid box は剥がされやすい) があるため、
v1 注入後にこのモジュールで v2 atom を追加する。

注入箇所 (RFC: spherical-video-v2-rfc.md より):

    moov
    └── trak (track_type == "vide" の各トラック)
        └── mdia
            └── minf
                └── stbl
                    └── stsd
                        └── <video sample description>  (avc1 / hvc1 / mp4v 等)
                            ├── st3d   (新規追加: stereo_mode=0=mono)
                            └── sv3d   (新規追加: 中に svhd + proj/{prhd,equi})

このモジュールは:
- ① 各 atom を bytes で組み立てる pure な helper (`*_box_bytes()`)
- ② sample description container に v2 atom を append する pure helper
  (`append_v2_atoms_to_sample()`)
- ③ 実 mp4 を読み書きする impure な runner (`inject_v2_atoms()`, `main()`)

を提供する。① ② はユニットテスト可能、③ は Docker E2E でのみ検証する。

vendored 制約: `apps/spatial-media/` の Google ツールは「v1 inject + parser」のみ実装。
本モジュールはそのコードを読み専用で再利用 (mpeg4_container.load, Box, Container) し、
書き換えは行わない。ただし stsd 直下の VisualSampleEntry (avc1/hvc1 等) を **container として
扱うために container.load を本モジュール内で monkey-patch する** (vendored 自体は触らない)。
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path
from typing import Optional


# vendored spatial-media を import path に追加 (ローカル import を簡潔にするため)
_SPATIAL_MEDIA_DIR = Path(__file__).resolve().parent / "spatial-media"
if str(_SPATIAL_MEDIA_DIR) not in sys.path:
    sys.path.insert(0, str(_SPATIAL_MEDIA_DIR))

from spatialmedia.mpeg import constants, container as _container_mod  # noqa: E402
from spatialmedia.mpeg.box import Box  # noqa: E402
from spatialmedia.mpeg.container import Container  # noqa: E402
from spatialmedia.mpeg.mpeg4_container import load as load_mpeg4  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# stsd 直下に来る VisualSampleEntry box の name 群。これらは「子 box を持つ container」
# だが ISO BMFF 仕様では同 entry 冒頭に 78 byte の固定ヘッダ (SampleEntry 8 byte +
# VisualSampleEntry 70 byte) を持つため、子 box parse 前に padding として読み飛ばす必要がある。
_VIDEO_SAMPLE_DESCRIPTIONS: frozenset[bytes] = frozenset({
    b"avc1", b"avc3",   # H.264 (AVC)
    b"hvc1", b"hev1",   # H.265 (HEVC)
    b"mp4v",            # MPEG-4 Visual
    b"vp08", b"vp09",   # VP8 / VP9
    b"av01",            # AV1
})

# SampleEntry (8 byte) + VisualSampleEntry 固有領域 (70 byte) = 78 byte
_VISUAL_SAMPLE_ENTRY_PADDING = 78


# ---------------------------------------------------------------------------
# Pure helpers — V2 atom byte layout (RFC 準拠, big-endian)
# ---------------------------------------------------------------------------

def _full_box_header(version: int = 0, flags: int = 0) -> bytes:
    """ISO BMFF FullBox 共通ヘッダ: 1 byte version + 3 byte flags."""
    return bytes([version & 0xFF]) + flags.to_bytes(3, "big")


def _wrap(name: bytes, body: bytes) -> bytes:
    """Box ヘッダ (size 4 byte + name 4 byte) を body の前に付ける."""
    size = 8 + len(body)
    return size.to_bytes(4, "big") + name + body


def st3d_box_bytes(stereo_mode: int = 0) -> bytes:
    """st3d (Stereoscopic 3D) FullBox.

    Body: 1 byte の stereo_mode. 0=mono (monoscopic), 1=top-bottom, 2=left-right.
    本ツールは monoscopic equirect のみ扱うのでデフォルト 0。
    """
    body = _full_box_header() + bytes([stereo_mode & 0xFF])
    return _wrap(b"st3d", body)


_DEFAULT_METADATA_SOURCE = "insta360-auto-converter"


def svhd_box_bytes(metadata_source: str = _DEFAULT_METADATA_SOURCE) -> bytes:
    """svhd (Spherical Video Header) FullBox.

    Body: null-terminated UTF-8 文字列 (metadata_source). Parser がツール識別に使う。
    """
    body = _full_box_header() + metadata_source.encode("utf-8") + b"\x00"
    return _wrap(b"svhd", body)


def prhd_box_bytes() -> bytes:
    """prhd (Projection Header) FullBox.

    Body: 16.16 fixed point の yaw / pitch / roll (各 4 byte). 全部 0 = 向きフラット。
    """
    body = _full_box_header() + b"\x00" * 12
    return _wrap(b"prhd", body)


def equi_box_bytes() -> bytes:
    """equi (Equirectangular Projection) FullBox.

    Body: 4 つの 0.32 fixed point projection_bounds (top, bottom, left, right; 各 4 byte).
    全部 0 = 全球 (uncropped equirect).
    """
    body = _full_box_header() + b"\x00" * 16
    return _wrap(b"equi", body)


def proj_box_bytes() -> bytes:
    """proj (Projection) container: prhd + equi.

    container box は FullBox ではない (version/flags 無し)。
    """
    body = prhd_box_bytes() + equi_box_bytes()
    return _wrap(b"proj", body)


def sv3d_box_bytes() -> bytes:
    """sv3d (Spherical Video v2) container: svhd + proj."""
    body = svhd_box_bytes() + proj_box_bytes()
    return _wrap(b"sv3d", body)


# ---------------------------------------------------------------------------
# Box / Container manipulation helpers
# ---------------------------------------------------------------------------

def _make_leaf_from_bytes(name: bytes, raw: bytes) -> Box:
    """先頭 8 byte の box ヘッダ込み bytes から、vendored の Box (leaf) を組み立てる.

    vendored の `Box.save` は header (size + name) を struct.pack で書き戻し、
    `self.contents` (= body 部分の bytes) を続けて write する。よって `contents` には
    header を除いた body bytes を入れる。
    """
    leaf = Box()
    leaf.name = name
    leaf.header_size = 8
    leaf.content_size = len(raw) - 8
    leaf.contents = raw[8:]
    return leaf


def append_v2_atoms_to_sample(sample: Container) -> None:
    """video sample description container (avc1 / hvc1 等) に sv3d と st3d を append する.

    冪等: 既に同名 atom が contents に含まれていれば追加しない。
    container の resize() は呼ばない (呼び出し側で `mpeg4_file.resize()` する想定)。
    """
    if sample.contents is None:
        sample.contents = []

    existing = {c.name for c in sample.contents}

    if b"sv3d" not in existing:
        sample.contents.append(_make_leaf_from_bytes(b"sv3d", sv3d_box_bytes()))

    if b"st3d" not in existing:
        sample.contents.append(_make_leaf_from_bytes(b"st3d", st3d_box_bytes()))


# ---------------------------------------------------------------------------
# vendored container.load monkey-patch
# stsd 配下の avc1/hvc1 等を container として扱うため. 本モジュール内のみ有効
# (sys.path に追加した時点でモジュールスコープで walk するため import 時に 1 回だけ実行)。
# ---------------------------------------------------------------------------

_orig_container_load = _container_mod.load


def _patched_container_load(fh, position, end):
    """container.load の薄いラッパ. video sample description のときだけ padding 78 byte で
    container として load する。それ以外は vendored の挙動に委譲。
    """
    if position is None:
        position = fh.tell()
    fh.seek(position)
    size_raw = fh.read(4)
    if len(size_raw) < 4:
        fh.seek(position)
        return _orig_container_load(fh, position, end)
    size = struct.unpack(">I", size_raw)[0]
    name = fh.read(4)

    if name not in _VIDEO_SAMPLE_DESCRIPTIONS:
        # 通常の box / container として既存ロジックに委ねる (file 位置を巻き戻す)
        fh.seek(position)
        return _orig_container_load(fh, position, end)

    header_size = 8
    if size == 1:
        size = struct.unpack(">Q", fh.read(8))[0]
        header_size = 16

    if size < 8 or (position + size) > end:
        # 異常時は既存ロジックに委ねる (エラー扱い)
        fh.seek(position)
        return _orig_container_load(fh, position, end)

    new_box = Container()
    new_box.name = name
    new_box.position = position
    new_box.header_size = header_size
    new_box.content_size = size - header_size
    new_box.padding = _VISUAL_SAMPLE_ENTRY_PADDING
    new_box.contents = _container_mod.load_multiple(
        fh,
        position + header_size + _VISUAL_SAMPLE_ENTRY_PADDING,
        position + size,
    )
    if new_box.contents is None:
        return None
    return new_box


_container_mod.load = _patched_container_load


# ---------------------------------------------------------------------------
# Walk + inject (impure: 実 mp4 file 読み書き)
# ---------------------------------------------------------------------------

def _walk_video_sample_descriptions(mpeg4_file) -> list[Container]:
    """mpeg4_file の moov を辿り、video sample description container を集めて返す."""
    found: list[Container] = []
    for trak in (e for e in mpeg4_file.moov_box.contents if e.name == constants.TAG_TRAK):
        for mdia in (e for e in trak.contents if e.name == constants.TAG_MDIA):
            for minf in (e for e in mdia.contents if e.name == constants.TAG_MINF):
                for stbl in (e for e in minf.contents if e.name == constants.TAG_STBL):
                    for stsd in (e for e in stbl.contents if e.name == constants.TAG_STSD):
                        for sample in stsd.contents:
                            if sample.name in _VIDEO_SAMPLE_DESCRIPTIONS:
                                found.append(sample)
    return found


def inject_v2_atoms(input_path: str, output_path: str) -> int:
    """input_path の mp4 を読み、各 video sample description に sv3d/st3d を追加して
    output_path に書き出す.

    Returns:
        0 成功、非 0 エラーコード:
          1=入力ファイル無し / 2=入出力同パス / 3=mp4 解析失敗 / 4=video track 無し
    """
    if not os.path.exists(input_path):
        sys.stderr.write("input file not found: {}\n".format(input_path))
        return 1
    if os.path.abspath(input_path) == os.path.abspath(output_path):
        sys.stderr.write("input and output cannot be the same\n")
        return 2

    with open(input_path, "rb") as in_fh:
        mpeg4_file = load_mpeg4(in_fh)
        if mpeg4_file is None:
            sys.stderr.write("failed to parse mpeg4: {}\n".format(input_path))
            return 3

        samples = _walk_video_sample_descriptions(mpeg4_file)
        if not samples:
            sys.stderr.write(
                "no video sample description found, nothing injected: {}\n".format(input_path)
            )
            return 4

        for sample in samples:
            append_v2_atoms_to_sample(sample)

        mpeg4_file.resize()
        with open(output_path, "wb") as out_fh:
            mpeg4_file.save(in_fh, out_fh)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 2:
        sys.stderr.write("usage: spherical_v2.py <input.mp4> <output.mp4>\n")
        return 2
    return inject_v2_atoms(argv[0], argv[1])


if __name__ == "__main__":
    sys.exit(main())
