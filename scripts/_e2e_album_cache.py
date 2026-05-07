"""実 Google Photos API を叩いて create_or_retrieve_album の cache 挙動を E2E 検証する。

注意: 実 OAuth (`insta360-auto-converter-data/gphotos_auth.json`) を使うため、
本物の Google Photos アカウント上に空のテストアルバムが作成される。
PR #10 の動作確認後に手動で削除すること。

実行方法 (リポジトリ直下から):

    INSTA360_LOGS_DIR=/tmp/i360-e2e-logs \\
    INSTA360_CONFIGS_PATH=$PWD/insta360-auto-converter-data/configs.yaml \\
    uv run python scripts/_e2e_album_cache.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps"))

import google_photos_uploader as gphotos  # noqa: E402


CACHE_PATH = "/tmp/e2e_album_cache.json"
AUTH_PATH = str(REPO_ROOT / "insta360-auto-converter-data" / "gphotos_auth.json")


def _print(msg: str) -> None:
    print("[E2E] " + msg, flush=True)


def main() -> int:
    if os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)
        _print("removed pre-existing {}".format(CACHE_PATH))

    _print("auth: {}".format(AUTH_PATH))
    session = gphotos.get_authorized_session(AUTH_PATH)

    suffix = int(time.time())
    album_a = "cache-e2e-A-{}".format(suffix)
    album_b = "cache-e2e-B-{}".format(suffix)

    failures: list[str] = []

    # ---- Phase 1: cache miss for album_a -> create new
    _print("Phase 1: first call for '{}' (expect cache MISS, POST /v1/albums)".format(album_a))
    id1 = gphotos.create_or_retrieve_album(session, album_a, cache_path=CACHE_PATH)
    _print("  id1={}".format(id1))
    if not id1:
        failures.append("Phase 1: id1 is falsy")

    # ---- Phase 2: cache hit for album_a -> same id, no API call
    _print("Phase 2: second call for '{}' (expect cache HIT, no POST)".format(album_a))
    id2 = gphotos.create_or_retrieve_album(session, album_a, cache_path=CACHE_PATH)
    _print("  id2={} (same as id1: {})".format(id2, id1 == id2))
    if id1 != id2:
        failures.append("Phase 2: id1 ({}) != id2 ({}), cache hit failed".format(id1, id2))

    # ---- Phase 3: cache miss for album_b -> create new (different from album_a)
    _print("Phase 3: first call for '{}' (expect cache MISS for new name)".format(album_b))
    id3 = gphotos.create_or_retrieve_album(session, album_b, cache_path=CACHE_PATH)
    _print("  id3={}".format(id3))
    if not id3:
        failures.append("Phase 3: id3 is falsy")
    if id3 == id1:
        failures.append("Phase 3: id3 == id1, separate album not created")

    # ---- Phase 4: cache contents verification
    cache = json.loads(Path(CACHE_PATH).read_text())
    _print("Phase 4: cache contents = {}".format(cache))
    expected_keys = {album_a, album_b}
    if set(cache.keys()) != expected_keys:
        failures.append("Phase 4: cache keys {} != expected {}".format(set(cache.keys()), expected_keys))
    if cache.get(album_a) != id1:
        failures.append("Phase 4: cache[{}] != id1".format(album_a))
    if cache.get(album_b) != id3:
        failures.append("Phase 4: cache[{}] != id3".format(album_b))

    # ---- Phase 5: cache deleted -> regenerate (creates duplicate album as expected)
    os.remove(CACHE_PATH)
    _print("Phase 5: cache deleted, retry '{}' (expect cache MISS, NEW duplicate album)".format(album_a))
    id4 = gphotos.create_or_retrieve_album(session, album_a, cache_path=CACHE_PATH)
    _print("  id4={} (different from id1: {})".format(id4, id1 != id4))
    if not id4:
        failures.append("Phase 5: id4 is falsy")
    if id4 == id1:
        failures.append("Phase 5: id4 == id1, expected new duplicate after cache deletion")

    cache_after = json.loads(Path(CACHE_PATH).read_text())
    _print("Phase 5: regenerated cache = {}".format(cache_after))
    if set(cache_after.keys()) != {album_a}:
        failures.append("Phase 5: regenerated cache keys {} != expected {{ {} }}".format(set(cache_after.keys()), album_a))

    session.close()

    print()
    if failures:
        _print("RESULT: FAIL ({} failures)".format(len(failures)))
        for f in failures:
            _print("  - " + f)
        return 1
    _print("RESULT: ALL PASS (5 phases)")
    _print("created albums (need manual cleanup on Photos): '{}' x2, '{}' x1".format(album_a, album_b))
    _print("  album_a id1={} (Phase 1)".format(id1))
    _print("  album_a id4={} (Phase 5, duplicate after cache reset)".format(id4))
    _print("  album_b id3={} (Phase 3)".format(id3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
