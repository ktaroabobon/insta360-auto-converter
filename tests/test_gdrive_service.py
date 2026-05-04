"""GDriveService 周りのユニットテスト。

Google Drive API は呼ばずに、`retrieve_all_in_folder` / `createRemoteFolder` を
モック差し替えして `get_or_create_subfolder` の挙動だけを検証する。
"""
from __future__ import annotations

from unittest.mock import MagicMock

from gdrive_service import GDriveService


def _make_service(monkeypatch) -> GDriveService:
    """サービスアカウント認証 + Drive API クライアント生成をスキップしたインスタンスを返す。"""
    # __init__ の認証部を完全にバイパスするため、空インスタンスを作って属性だけ詰める
    gs = GDriveService.__new__(GDriveService)
    gs.SCOPES = []
    gs.drive_id = "drive-id-stub"
    gs.cred_path = "/dev/null"
    gs.creds = None
    gs.service = MagicMock(name="drive-api-stub")
    return gs


class TestGetOrCreateSubfolder:
    def test_returns_existing_folder_without_creating(self, monkeypatch):
        """同名サブフォルダが既にあれば、それを返し、新規作成はしない。"""
        gs = _make_service(monkeypatch)
        existing = [
            {"id": "f-other", "name": "other-album", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "f-target", "name": "trip-2026-04", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "file-1", "name": "trip-2026-04", "mimeType": "image/jpeg"},  # 同名でも folder 以外は無視
        ]
        monkeypatch.setattr(gs, "retrieve_all_in_folder", lambda parent_id: existing)
        create_spy = MagicMock(name="createRemoteFolder")
        monkeypatch.setattr(gs, "createRemoteFolder", create_spy)

        result = gs.get_or_create_subfolder("parent-id", "trip-2026-04")

        assert result == {
            "id": "f-target",
            "name": "trip-2026-04",
            "mimeType": "application/vnd.google-apps.folder",
        }
        create_spy.assert_not_called()

    def test_creates_when_missing_and_returns_dict_with_id_and_name(self, monkeypatch):
        """同名サブフォルダが無ければ作成し、id/name/mimeType を含む dict を返す。"""
        gs = _make_service(monkeypatch)
        monkeypatch.setattr(gs, "retrieve_all_in_folder", lambda parent_id: [])
        monkeypatch.setattr(gs, "createRemoteFolder", lambda name, parent: "newly-created-id")

        result = gs.get_or_create_subfolder("parent-id", "trip-2026-05")

        assert result["id"] == "newly-created-id"
        assert result["name"] == "trip-2026-05"
        assert result["mimeType"] == "application/vnd.google-apps.folder"

    def test_create_is_called_with_parent_id(self, monkeypatch):
        """新規作成時、createRemoteFolder には正しい parent_id が渡る。"""
        gs = _make_service(monkeypatch)
        monkeypatch.setattr(gs, "retrieve_all_in_folder", lambda parent_id: [])
        create_spy = MagicMock(return_value="created-id")
        monkeypatch.setattr(gs, "createRemoteFolder", create_spy)

        gs.get_or_create_subfolder("parent-xyz", "newalbum")

        create_spy.assert_called_once_with("newalbum", "parent-xyz")

    def test_ignores_non_folder_entries_with_same_name(self, monkeypatch):
        """同名でも folder mimeType でなければ「無い」とみなして作成する。"""
        gs = _make_service(monkeypatch)
        existing = [
            {"id": "file-x", "name": "trip", "mimeType": "image/jpeg"},
            {"id": "file-y", "name": "trip", "mimeType": "video/mp4"},
        ]
        monkeypatch.setattr(gs, "retrieve_all_in_folder", lambda parent_id: existing)
        create_spy = MagicMock(return_value="newid")
        monkeypatch.setattr(gs, "createRemoteFolder", create_spy)

        gs.get_or_create_subfolder("parent", "trip")

        create_spy.assert_called_once()
