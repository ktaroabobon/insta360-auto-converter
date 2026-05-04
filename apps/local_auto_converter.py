"""ローカル入力モード: ローカルディレクトリから raw を取り、変換して Drive / Photos に上げる。

Drive をソースに使う既存の `insta360_auto_converter.py` と並列の役割を担うが、
入力源が **ホスト側のローカルディレクトリ** (`/insta360-auto-converter-data/local-input/<アルバム名>/`)
である点が異なる。アップロード先は **Drive (working folder 配下のサブフォルダ) と Photos の両方**。

完了マーカーは Drive ではなくローカルファイル `.done` で管理する (best-effort、再起動安全)。

設定読み込み (`configs.txt`) と SDK バイナリ起動はモジュールロード時 / `main()` 内で行うため、
本ファイルを **テスト用に import** する場合でも副作用が走らないように、import 時の I/O を最小化している。
"""
from __future__ import annotations

import os
import sys
import time
import glob
import subprocess
from configparser import ConfigParser
from pathlib import Path
from subprocess import PIPE, Popen
from typing import Callable, Optional

sys.path.append('.')
import google_photos_uploader as gphotos  # noqa: E402
from app_config import UploadTargets  # noqa: E402
from gdrive_service import GDriveService  # noqa: E402
from local_input import (  # noqa: E402
    derive_output_names,
    find_pending,
    is_image,
    list_album_dirs,
    mark_done,
)
from stitcher import (  # noqa: E402
    build_command,
    build_exiftool_command,
    build_spatial_media_command,
)
from utils import log, silentremove  # noqa: E402
from video_processor import VideoProcessor  # noqa: E402


# ローカル入力モードの規約
DEFAULT_LOCAL_INPUT_ROOT = "/insta360-auto-converter-data/local-input"
SLEEP_SEC_NO_WORK = 3
NO_FOUND_IN_A_ROW_LIMIT = 10


# ---------------------------------------------------------------------------
# テスト可能なオーケストレータ
# ---------------------------------------------------------------------------

SdkRunner = Callable[[dict, str, str, Path], None]
PhotosUploader = Callable[[str, str], None]


def process_pending(
    pending: dict,
    working_folder: str,
    drive_parent_id: str,
    gs,
    sdk_runner: SdkRunner,
    upload_targets: UploadTargets,
    photos_uploader: PhotosUploader = gphotos.upload_to_album,
    split_outputs: Optional[list[str]] = None,
) -> None:
    """1 件分の処理: SDK 変換 → 有効なアップロード先のみ上げる → 完了マーカー。

    `sdk_runner` はテスト時に差し替え可能。本番では `_run_sdk_and_inject_metadata` を渡す。
    `split_outputs` は動画分割後のファイル名リスト (None の場合は単一 `output_name` を使う)。
    `upload_targets` は Drive / Photos の on/off を保持する `UploadTargets` 値オブジェクト。
    `upload_targets.drive == True` のときのみ Drive 系呼出 (`get_or_create_subfolder` /
    `upload_file_to_folder`) を行い、`upload_targets.photos == True` のときのみ
    `photos_uploader(...)` を呼ぶ。**有効な上げ先がすべて成功したときのみ** `.done` を残す
    (失敗時は例外を伝播し、次の周回で再試行する)。
    """
    left: Path = pending["left"]
    img = pending["is_image"]
    album_name = pending["album_name"]
    convert_name, output_name = derive_output_names(left.name)

    # 1. SDK + 必要ならメタデータ注入。失敗時はここで例外を投げてもらい、done マーカーは作らない。
    sdk_runner(pending, convert_name, output_name, Path(working_folder))

    # 2. アップロード対象を決める (動画は分割の可能性あり)
    if img:
        outputs = [output_name]
        mimetype = "image/jpeg"
    else:
        outputs = split_outputs if split_outputs is not None else [output_name]
        mimetype = "video/mp4"

    # 3. Drive (toggle on のときのみ): アルバム名のサブフォルダを取得 (なければ作成)
    drive_subfolder = None
    if upload_targets.drive:
        drive_subfolder = gs.get_or_create_subfolder(drive_parent_id, album_name)

    # 4. 各出力を有効な先のみに上げる。
    #    どこかで例外が出れば伝播し、`mark_done` には到達しない (再試行可能な状態を保つ)。
    for out_name in outputs:
        out_path = "{}/{}".format(working_folder, out_name)
        if upload_targets.drive:
            gs.upload_file_to_folder(out_path, drive_subfolder, mimetype)
        if upload_targets.photos:
            photos_uploader(out_path, album_name)

    # 5. 有効な上げ先がすべて成功したらマーカーを残す。
    mark_done(left)


# ---------------------------------------------------------------------------
# 本番用 SDK ランナー (テスト対象外: subprocess + ファイル I/O)
# ---------------------------------------------------------------------------


def _run_sdk_and_inject_metadata(pending: dict, convert_name: str, output_name: str, working_folder: Path) -> list[str]:
    """SDK で stitching → 必要なら動画分割 → 360 メタデータ注入。

    最後に「アップロードすべきファイル名のリスト」を返す。動画は分割で複数になる。
    既存 `apps/insta360_auto_converter.py` の SDK 周りロジックと挙動を揃えている。
    """
    sdk_path = "/insta360-auto-converter/MediaSDK"
    left_name = pending["left"].name
    right_name = pending["right"].name if pending["right"] is not None else None
    img = pending["is_image"]

    # 入力 raw を working_folder にコピー (SDK が working_folder/<name> を読むため)
    import shutil
    shutil.copy(pending["left"], working_folder / left_name)
    if pending["right"] is not None:
        shutil.copy(pending["right"], working_folder / right_name)

    stabilize_flag = True
    while True:
        cmds = build_command(
            sdk_path=sdk_path,
            working_folder=str(working_folder),
            left_name=left_name,
            right_name=right_name,
            convert_name=convert_name,
            is_image=img,
            stabilize=stabilize_flag,
        )
        log("360 convert command (local mode): {}".format(cmds))
        p = Popen(" ".join(cmds), stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
        return_code = p.wait()
        log("return_code of the conversion: {}".format(return_code))
        if return_code == 139 and img and stabilize_flag:
            # SIGSEGV: 写真の手ブレ補正で発生することがある (HDR 等)。一度だけ stabilize 無しで再試行。
            stabilize_flag = False
            continue
        if return_code != 0:
            raise RuntimeError("SDK conversion failed, return_code={}".format(return_code))
        break

    # 動画は閾値超なら分割
    split_videos: list[str] = []
    if not img:
        # working_folder 内の `*insv` (raw) は変換が終わったので削除
        for filename in glob.glob(str(working_folder / "*insv")):
            silentremove(filename)
        time.sleep(30)
        vp = VideoProcessor()
        split_videos = vp.split_video(str(working_folder / convert_name))
        log("split_videos: {}".format(split_videos))

    # メタデータ注入
    if img:
        cmd = build_exiftool_command(str(working_folder / convert_name))
        subprocess.call(" ".join(cmd), shell=True)
        os.rename(working_folder / convert_name, working_folder / output_name)
        return [output_name]

    # 動画: split_video の戻り値はファイル名のみ (cwd 依存)。working_folder 直下に居る前提。
    outputs: list[str] = []
    for tmp_video in split_videos:
        out_name = tmp_video.replace("_convert", "")
        cmd = build_spatial_media_command(
            convert_name=tmp_video,
            output_name=out_name,
        )
        subprocess.call(" ".join(cmd), shell=True)
        silentremove(tmp_video)
        outputs.append(out_name)
    return outputs


# ---------------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------------


def main():
    config = ConfigParser()
    config.read("/insta360-auto-converter-data/configs.txt")

    cred_path = "/insta360-auto-converter-data/auto-conversion.json"
    drive_id = config["GDRIVE_INFO"]["drive_id"]
    drive_parent_id = config["GDRIVE_INFO"]["working_folder_id"]
    input_root = Path(os.environ.get("INSTA360_LOCAL_INPUT_ROOT", DEFAULT_LOCAL_INPUT_ROOT))
    working_folder = "/insta360-auto-converter/apps"

    log_flag = True
    no_found_in_a_row = 0

    while True:
        gs = None
        try:
            try:
                gs = GDriveService(cred_path, drive_id)
            except Exception as e:
                log("GDriveService init failed (local mode): {}".format(e))

            processed = False
            for album_dir in list_album_dirs(input_root):
                pending = find_pending(album_dir)
                if not pending:
                    continue

                # SDK 実行 + 分割を 1 回ぶん回し、戻り値の split_outputs を取得
                # process_pending には外部から split_outputs を渡せるが、
                # 本番では _run_sdk_and_inject_metadata がリストを返してくるので、ここで橋渡しする。
                outputs_holder: dict[str, list[str]] = {}

                def _runner(p_arg, convert_name, output_name, wf):
                    outs = _run_sdk_and_inject_metadata(p_arg, convert_name, output_name, wf)
                    outputs_holder["outputs"] = outs

                # is_image なら outputs はそのまま [output_name]、動画は split_outputs を渡す
                # NOTE: upload_targets は task 4.3 で main() を YAML 経由に置き換えるまでの
                #       暫定シム。現状は既存挙動 (Drive + Photos 両方上げる) を保つ。
                process_pending(
                    pending=pending,
                    working_folder=working_folder,
                    drive_parent_id=drive_parent_id,
                    gs=gs,
                    sdk_runner=_runner,
                    upload_targets=UploadTargets(drive=True, photos=True),
                    split_outputs=outputs_holder.get("outputs") if not pending["is_image"] else None,
                )
                processed = True
                no_found_in_a_row = 0
                log_flag = True
                break

            if not processed:
                no_found_in_a_row += 1
                if log_flag and no_found_in_a_row > NO_FOUND_IN_A_ROW_LIMIT:
                    log("entering silent mode (local input)...")
                    log_flag = False
        except Exception as e:
            log("local_auto_converter has some error: {} at line: {}".format(e, sys.exc_info()[2].tb_lineno), True)
        finally:
            try:
                if gs is not None:
                    gs.service.close()
            except Exception:
                pass

        if log_flag:
            log("sleep {} secs for getting next job (local mode)...".format(SLEEP_SEC_NO_WORK))
        time.sleep(SLEEP_SEC_NO_WORK)


if __name__ == "__main__":
    main()
