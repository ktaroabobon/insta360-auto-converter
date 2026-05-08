"""Spherical Video V2 atom 注入モジュール `spherical_v2` のユニットテスト。

PR #12 ユーザーフィードバック: PC 版 Google Photos では 360 動画として再生されたが、
Android 版で 360 として認識されない。原因の 1 つは vendored `spatial-media` が
v1.0 (uuid + XMP `<rdf:SphericalVideo>`) しか注入しないため。Google RFC では:

  - V1 (uuid box + XMP): 旧仕様、後方互換用
  - V2 (st3d, sv3d, svhd, proj, prhd, equi atoms): 現行仕様、`stsd/<sample>/` 直下に置く
  - 「両方ある場合は v2 が優先」

Android Google Photos は v2 atom を読む傾向があり (uuid box はサーバー transcode で
剥がされやすい)、v2 注入を必須化する。

ここでは「box の bytes layout を組み立てる pure 関数」と「mp4 への注入関数」のうち、
**前者のみ unit test で検証** する (mp4 注入は実バイナリ依存で CI で動かしづらいため、
docker E2E で検証する)。pure 関数だけでも各 atom のバイナリレイアウトを
RFC 通りに組み立てているかを確実に押さえられる。
"""
from __future__ import annotations

import struct

import pytest

import spherical_v2 as sv2


def _read_box_header(raw: bytes) -> tuple[int, bytes]:
    """先頭 8 byte の box header (size + 4 char tag) を返す。"""
    assert len(raw) >= 8
    size = struct.unpack(">I", raw[:4])[0]
    name = raw[4:8]
    return size, name


class TestSt3dBoxBytes:
    """st3d FullBox: 1 byte の stereo_mode を持つ。0=mono, 1=top-bottom, 2=left-right。

    モノスコピック equirect では stereo_mode=0 を入れる。
    """

    def test_size_is_header_plus_fullbox_plus_body(self):
        raw = sv2.st3d_box_bytes(stereo_mode=0)
        size, name = _read_box_header(raw)
        # 4 (size) + 4 (name 'st3d') + 1 (version) + 3 (flags) + 1 (stereo_mode) = 13 bytes
        assert size == 13
        assert name == b"st3d"
        assert len(raw) == size

    def test_default_stereo_mode_is_mono(self):
        raw = sv2.st3d_box_bytes()
        # 末尾 1 byte が stereo_mode = 0 (mono)
        assert raw[-1] == 0

    def test_top_bottom_mode(self):
        raw = sv2.st3d_box_bytes(stereo_mode=1)
        assert raw[-1] == 1

    def test_version_and_flags_are_zero(self):
        raw = sv2.st3d_box_bytes()
        # FullBox: version(1) + flags(3) = 4 zero bytes following 8-byte header
        assert raw[8:12] == b"\x00\x00\x00\x00"


class TestSvhdBoxBytes:
    """svhd FullBox: null-terminated UTF-8 文字列 (metadata_source) を持つ。"""

    def test_size_includes_null_terminator(self):
        raw = sv2.svhd_box_bytes(metadata_source="abc")
        size, name = _read_box_header(raw)
        # 8 (header) + 4 (fullbox) + 4 ("abc\0") = 16 bytes
        assert name == b"svhd"
        assert size == 16
        assert len(raw) == size

    def test_string_is_null_terminated(self):
        raw = sv2.svhd_box_bytes(metadata_source="abc")
        assert raw[-1] == 0  # null terminator
        # 8 byte header + 4 byte fullbox = 12 byte, after that "abc\0"
        assert raw[12:] == b"abc\x00"

    def test_default_metadata_source_identifies_tool(self):
        """metadata_source は parser がツール識別に使う。本ツールを示す ASCII 文字列を入れる。"""
        raw = sv2.svhd_box_bytes()
        # 12 byte header + fullbox の後ろが non-empty で末尾 0
        assert len(raw) > 13
        assert raw[-1] == 0


class TestPrhdBoxBytes:
    """prhd FullBox: 16.16 fixed point の yaw / pitch / roll を持つ (各 4 byte, 計 12 byte)."""

    def test_size_is_8_header_plus_4_fullbox_plus_12_pose(self):
        raw = sv2.prhd_box_bytes()
        size, name = _read_box_header(raw)
        assert name == b"prhd"
        assert size == 8 + 4 + 12  # = 24
        assert len(raw) == size

    def test_pose_defaults_are_zero(self):
        """ポーズ (yaw/pitch/roll) はデフォルト 0 (向きフラット)."""
        raw = sv2.prhd_box_bytes()
        # 12 byte header + 4 byte fullbox の後ろが 12 byte の zero
        assert raw[12:24] == b"\x00" * 12


class TestEquiBoxBytes:
    """equi FullBox: 4 つの 0.32 fixed point projection_bounds (top, bottom, left, right) を持つ.

    全部 0 = 全球 (uncropped equirect)。
    """

    def test_size_is_8_header_plus_4_fullbox_plus_16_bounds(self):
        raw = sv2.equi_box_bytes()
        size, name = _read_box_header(raw)
        assert name == b"equi"
        assert size == 8 + 4 + 16  # = 28
        assert len(raw) == size

    def test_bounds_default_uncropped(self):
        raw = sv2.equi_box_bytes()
        assert raw[12:28] == b"\x00" * 16


class TestProjBoxStructure:
    """proj は prhd + equi を子に持つ container box."""

    def test_proj_contains_prhd_then_equi(self):
        raw = sv2.proj_box_bytes()
        size, name = _read_box_header(raw)
        assert name == b"proj"
        # 子 box 領域
        body = raw[8:]
        # 1 個目 = prhd (size 24)
        prhd_size, prhd_name = _read_box_header(body)
        assert prhd_name == b"prhd"
        assert prhd_size == 24
        # 2 個目 = equi (size 28)
        equi_size, equi_name = _read_box_header(body[prhd_size:])
        assert equi_name == b"equi"
        assert equi_size == 28
        # 全体 size = 8 (proj header) + 24 (prhd) + 28 (equi) = 60
        assert size == 60
        assert len(raw) == size


class TestSv3dBoxStructure:
    """sv3d は svhd + proj を子に持つ container box."""

    def test_sv3d_contains_svhd_then_proj(self):
        raw = sv2.sv3d_box_bytes()
        size, name = _read_box_header(raw)
        assert name == b"sv3d"
        body = raw[8:]
        # 1 個目 = svhd
        svhd_size, svhd_name = _read_box_header(body)
        assert svhd_name == b"svhd"
        # 2 個目 = proj (size 60)
        proj_size, proj_name = _read_box_header(body[svhd_size:])
        assert proj_name == b"proj"
        assert proj_size == 60
        # sv3d 全体 = 8 + svhd_size + 60
        assert size == 8 + svhd_size + 60
        assert len(raw) == size


class TestCli:
    """`apps/spherical_v2.py` を CLI で呼んだときの引数解釈の薄い検証.

    - 引数 2 個: input, output mp4 path
    - 引数不足なら non-zero exit
    - 入力ファイル不在は明確なエラーで落ちる
    """

    def test_main_returns_nonzero_on_missing_args(self):
        rc = sv2.main([])
        assert rc != 0

    def test_main_returns_nonzero_on_missing_input_file(self, tmp_path):
        missing = tmp_path / "does-not-exist.mp4"
        out = tmp_path / "out.mp4"
        rc = sv2.main([str(missing), str(out)])
        assert rc != 0


class TestInjectV2AtomsMutatesBox:
    """`inject_v2_atoms` の box 操作部分が moov/trak/mdia/minf/stbl/stsd/<sample> の中に
    st3d と sv3d を追加することを、in-memory な container 木で検証する。

    実 mp4 の読み書き (file I/O) は別ロジックで vendored `spatialmedia.mpeg` 経由なので、
    ここでは「stsd/<sample> container を渡したら sv3d/st3d が contents に append される」
    ことだけをチェックする (副作用最小の pure-ish helper)。
    """

    def test_appends_sv3d_and_st3d_to_video_sample_description(self):
        # 簡易な container を作る: stsd/avc1 だけ持つ
        from spatialmedia.mpeg.container import Container
        avc1 = Container()
        avc1.name = b"avc1"
        avc1.header_size = 8
        avc1.contents = []

        sv2.append_v2_atoms_to_sample(avc1)

        names = [c.name for c in avc1.contents]
        # sv3d と st3d が両方挿入される
        assert b"sv3d" in names
        assert b"st3d" in names

    def test_idempotent_when_already_present(self):
        from spatialmedia.mpeg.container import Container
        from spatialmedia.mpeg.box import Box

        sample = Container()
        sample.name = b"hvc1"
        sample.header_size = 8
        existing_sv3d = Box()
        existing_sv3d.name = b"sv3d"
        existing_sv3d.header_size = 8
        existing_sv3d.content_size = 4
        existing_sv3d.contents = b"\x00\x00\x00\x00"
        sample.contents = [existing_sv3d]

        sv2.append_v2_atoms_to_sample(sample)

        names = [c.name for c in sample.contents]
        # 既に sv3d があれば多重追加しない
        assert names.count(b"sv3d") == 1
        # st3d は無かったので追加される
        assert b"st3d" in names
