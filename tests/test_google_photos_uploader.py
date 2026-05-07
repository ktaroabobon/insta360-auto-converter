"""apps/google_photos_uploader.py の create_or_retrieve_album テスト。

PR #7 で入った一時パッチ (毎回新規アルバム作成) を回収し、
album_id をローカルファイルに永続キャッシュする proper fix を検証する。

実 Google API は一切呼ばず、session を MagicMock で差し替える。
キャッシュファイルは tmp_path で実 I/O を行う (`.claude/rules/unit-test.md` の方針)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def gphotos():
    """apps/google_photos_uploader を import して返す。

    conftest で sys.path に apps/ が追加されている前提。
    モジュール side-effect (utils import) はテスト全体で共有される。
    """
    sys.modules.pop("google_photos_uploader", None)
    import google_photos_uploader as module
    return module


def _make_session_returning(album_id: str = "new-album-id") -> MagicMock:
    """POST /v1/albums の応答を {"id": album_id, ...} で返す session mock。"""
    session = MagicMock(name="AuthorizedSession")
    response = MagicMock()
    response.json.return_value = {"id": album_id, "title": "stub"}
    session.post.return_value = response
    return session


class TestCreateOrRetrieveAlbumCacheHit:
    """cache hit の場合は API を一切叩かず、保存済み ID を返す。"""

    def test_cache_hit_returns_id_without_calling_api(self, tmp_path: Path, gphotos):
        cache_path = tmp_path / "album_cache.json"
        cache_path.write_text(json.dumps({"trip-2026-04": "cached-id-xyz"}))

        session = _make_session_returning()

        album_id = gphotos.create_or_retrieve_album(
            session, "trip-2026-04", cache_path=str(cache_path)
        )

        assert album_id == "cached-id-xyz"
        session.post.assert_not_called()


class TestCreateOrRetrieveAlbumCacheMiss:
    """cache miss のときは POST /v1/albums を呼んで結果を cache に追記する。"""

    def test_cache_miss_calls_api_and_writes_cache(self, tmp_path: Path, gphotos):
        cache_path = tmp_path / "album_cache.json"
        cache_path.write_text(json.dumps({}))

        session = _make_session_returning(album_id="new-album-id-123")

        album_id = gphotos.create_or_retrieve_album(
            session, "trip-2026-05", cache_path=str(cache_path)
        )

        assert album_id == "new-album-id-123"
        session.post.assert_called_once()
        url = session.post.call_args.args[0]
        assert url == "https://photoslibrary.googleapis.com/v1/albums"

        cache = json.loads(cache_path.read_text())
        assert cache == {"trip-2026-05": "new-album-id-123"}

    def test_cache_miss_preserves_existing_entries(self, tmp_path: Path, gphotos):
        cache_path = tmp_path / "album_cache.json"
        cache_path.write_text(json.dumps({"old-album": "old-id"}))

        session = _make_session_returning(album_id="brand-new-id")

        gphotos.create_or_retrieve_album(
            session, "new-album", cache_path=str(cache_path)
        )

        cache = json.loads(cache_path.read_text())
        assert cache == {"old-album": "old-id", "new-album": "brand-new-id"}


class TestCreateOrRetrieveAlbumCacheCorrupt:
    """JSON parse error の場合は空 dict から再開し、新規エントリで上書き保存する。"""

    def test_corrupt_cache_falls_back_to_empty_dict(self, tmp_path: Path, gphotos):
        cache_path = tmp_path / "album_cache.json"
        cache_path.write_text("{ this is not json")

        session = _make_session_returning(album_id="recovered-id")

        album_id = gphotos.create_or_retrieve_album(
            session, "trip-2026-06", cache_path=str(cache_path)
        )

        assert album_id == "recovered-id"
        session.post.assert_called_once()

        cache = json.loads(cache_path.read_text())
        assert cache == {"trip-2026-06": "recovered-id"}

    def test_non_dict_cache_falls_back_to_empty_dict(self, tmp_path: Path, gphotos):
        """JSON としては valid だが dict でない場合 (例: list) も空 dict 扱い。"""
        cache_path = tmp_path / "album_cache.json"
        cache_path.write_text(json.dumps(["this", "is", "a", "list"]))

        session = _make_session_returning(album_id="recovered-id-2")

        album_id = gphotos.create_or_retrieve_album(
            session, "trip-2026-08", cache_path=str(cache_path)
        )

        assert album_id == "recovered-id-2"
        cache = json.loads(cache_path.read_text())
        assert cache == {"trip-2026-08": "recovered-id-2"}


class TestCreateOrRetrieveAlbumCacheMissing:
    """cache ファイル不在の場合は空 dict から開始し、保存時にファイルを新規作成する。"""

    def test_missing_cache_starts_with_empty_dict(self, tmp_path: Path, gphotos):
        cache_path = tmp_path / "album_cache.json"
        assert not cache_path.exists()

        session = _make_session_returning(album_id="first-album-id")

        album_id = gphotos.create_or_retrieve_album(
            session, "trip-2026-07", cache_path=str(cache_path)
        )

        assert album_id == "first-album-id"
        session.post.assert_called_once()

        assert cache_path.exists()
        cache = json.loads(cache_path.read_text())
        assert cache == {"trip-2026-07": "first-album-id"}

    def test_missing_parent_directory_is_created(self, tmp_path: Path, gphotos):
        """親ディレクトリ不在の場合も自動で makedirs して保存する。"""
        cache_path = tmp_path / "nested" / "subdir" / "album_cache.json"
        assert not cache_path.parent.exists()

        session = _make_session_returning(album_id="nested-id")

        album_id = gphotos.create_or_retrieve_album(
            session, "nested-album", cache_path=str(cache_path)
        )

        assert album_id == "nested-id"
        assert cache_path.exists()


class TestCreateOrRetrieveAlbumIdempotent:
    """同 album_name の連続呼出で 2 回目以降は API を呼ばない。"""

    def test_consecutive_calls_with_same_name_call_api_only_once(
        self, tmp_path: Path, gphotos
    ):
        cache_path = tmp_path / "album_cache.json"

        session = _make_session_returning(album_id="album-id-xyz")

        first = gphotos.create_or_retrieve_album(
            session, "same-album", cache_path=str(cache_path)
        )
        second = gphotos.create_or_retrieve_album(
            session, "same-album", cache_path=str(cache_path)
        )

        assert first == "album-id-xyz"
        assert second == "album-id-xyz"
        assert session.post.call_count == 1


class TestCreateOrRetrieveAlbumWriteFailure:
    """cache 書き込み失敗 (read-only fs 等) は warn ログで継続する (best-effort)。"""

    def test_cache_write_failure_does_not_raise(self, tmp_path: Path, gphotos):
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        cache_path = readonly_dir / "album_cache.json"
        readonly_dir.chmod(0o555)

        try:
            session = _make_session_returning(album_id="returned-id")

            album_id = gphotos.create_or_retrieve_album(
                session, "trip", cache_path=str(cache_path)
            )

            assert album_id == "returned-id"
            session.post.assert_called_once()
            assert not cache_path.exists()
        finally:
            readonly_dir.chmod(0o755)


class TestCreateOrRetrieveAlbumApiFailure:
    """サーバーが id を返さない場合は None を返し、cache を破壊しない。"""

    def test_api_failure_returns_none_and_does_not_write_cache(
        self, tmp_path: Path, gphotos
    ):
        cache_path = tmp_path / "album_cache.json"
        cache_path.write_text(json.dumps({"existing": "existing-id"}))

        session = MagicMock(name="AuthorizedSession")
        response = MagicMock()
        response.json.return_value = {"error": "PERMISSION_DENIED"}
        session.post.return_value = response

        album_id = gphotos.create_or_retrieve_album(
            session, "doomed-album", cache_path=str(cache_path)
        )

        assert album_id is None
        cache = json.loads(cache_path.read_text())
        assert cache == {"existing": "existing-id"}
