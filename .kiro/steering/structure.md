---
name: Structure Steering
description: ディレクトリ構成、命名規約、モジュール責務の分割パターン、フラグファイルや絶対パスといった暗黙の取り決め
type: structure
inclusion: always
---

# Structure Steering

## Top-level layout

```
insta360-auto-converter/
├── Dockerfile                      # Ubuntu Focal + Python + MediaSDK ビルド
├── README.md                       # セットアップ手順 (外部 Google Doc リンク多数)
├── apps/                           # 実際に動く Python 一式
├── tests/                          # pytest ユニットテスト (TDD)
├── .github/workflows/              # GitHub Actions CI
├── MediaSDK/                       # Insta360 SDK (NDA、gitignored、要手動配置)
├── Image-ExifTool-12.10/           # ベンダーディレクトリ (写真メタデータ)
└── spatial-media/                  # ベンダーディレクトリ (動画メタデータ)
```

リポジトリ外で実行時に必要:

```
insta360-auto-converter-data/       # docker -v でマウント、絶対に共有しない
├── configs.txt                     # Drive / Gmail の ID/Secret
├── auto-conversion.json            # Drive サービスアカウント鍵
├── gphotos_auth.json               # Photos OAuth トークン
├── logs/                           # ローテーションログ出力先
└── local-input/                    # ローカル入力モード用 (任意)
    └── <アルバム名>/                  # 直下に .insv / .insp を置くと処理される
```

## `apps/` のモジュール責務

各ファイルは **1 つの外部サービス or 1 つのドメインに対応する**。
責務が混ざる変更を提案するときは、ファイル分割を先に検討する。

| ファイル | 役割 | エクスポート形態 |
|---|---|---|
| `insta360_auto_converter.py` | Drive モードのエントリポイント。`main()` の `while True` ループに全体フローを書く | スクリプト (`if __name__ == '__main__': main()`) |
| `local_auto_converter.py` | ローカル入力モードのエントリポイント。Drive 経由ではなくローカルディレクトリ polling | スクリプト |
| `local_input.py` | ローカル入力モードのファイル探索 / 命名規約 / 完了マーカー (pure 関数群、テスト容易) | モジュール関数群 |
| `stitcher.py` | MediaSDK / ExifTool / spatial-media の起動コマンド組み立て (pure、テスト容易) | モジュール関数群 |
| `gdrive_service.py` | Drive クライアントとフラグファイル規約 | `class GDriveService` |
| `google_photos_uploader.py` | Photos のレジューム可能アップロード + アルバム解決 | モジュールレベル関数群 (`upload_to_album` がエントリ) |
| `video_processor.py` | サイズ閾値での動画分割 | `class VideoProcessor` |
| `utils.py` | ロガー、SMTP メール、安全な削除。`INSTA360_LOGS_DIR` で出力先上書き可 | モジュールレベル関数 |
| `refersh_gphotos_cred.py` | ローカル PC で OAuth トークンを取得する CLI | スクリプト (運用補助) |
| `in_app_configs.conf` | アプリ内デフォルト (cleanup glob 等) | INI |

**Pattern:** 外部サービスごとに **クラス** を 1 つ持ち (`GDriveService` 等)、
内部状態 (認証セッション、サービスオブジェクト) はインスタンス変数として保持する。
Photos だけは class 化されておらずモジュール関数になっているが、これは歴史的経緯であり
**新規サービス追加時は class ベースを採用する**こと。

**TDD パターン:** SDK 起動 / API 呼び出し / subprocess を伴うコードは、
**コマンド組み立て (pure)** と **副作用 (impure)** を分離して書く (`stitcher.py` がその例)。
こうすることで pure 部分は CI でテスト可能、impure 部分は最小限に保てる。

## Naming conventions

- ファイル / 関数 / 変数: `snake_case` (Python 標準)
- クラス: `PascalCase`、サービス名 + `Service` / `Handler` / `Processor` のいずれか
- 定数: モジュール内なら大文字スネーク (`SDK_PATH`, `NO_FOUND_IN_A_ROW_LIMIT`)
- raw ファイル命名規約 (Insta360 仕様、外部仕様):
  - `*_00_*.insv` = 左目動画 (本体)、`*_10_*.insv` = 右目動画 (ペア)
  - `*_00_*.insp` = 左目写真 (写真は片目だけ存在)
- 出力ファイル変換規約:
  - `_convert.mp4` / `_convert.jpg` = stitching 直後 (まだメタデータ未注入)
  - サフィックス除去後 (例: `foo.mp4`) = メタデータ注入済み、アップロード対象
- フラグファイル命名規約 (Drive 上のコーディネーション):
  - `<rawname>.auto_processing` = 別コンテナが処理中
  - `<rawname>.auto_done` = 完了済 (再処理不要)
  - `<rawname>.auto_broken` = 失敗確定 (再処理不要、運用者の介入が必要)

**Why:** Insta360 のファイル命名は変更不可な外部仕様で、`_00_` / `_10_` がペアリング鍵。
フラグファイル方式は best-effort なロックで、3 種類の名前で「未着手 / 進行中 / 終端 (成功 or 失敗)」を区別する。

**How to apply:** raw 取り扱いコードでパース規約を弄るときは、Insta360 の命名仕様に依存していることを意識する。
新しいフラグの種類を増やすなら、既存 3 種を解釈する箇所 (`gdrive_service.py:get_need_convert_file_in_folder`) を全て更新する。

## Hardcoded absolute paths (intentional)

コードベースに以下の絶対パスがハードコードされている。これは **コンテナ運用前提** の意図的な設計。

- `/insta360-auto-converter/` — リポジトリの COPY 先
- `/insta360-auto-converter/apps` — `WORKDIR`、stitching 中間ファイルの作業場
- `/insta360-auto-converter/MediaSDK` — SDK バイナリとライブラリ
- `/insta360-auto-converter-data/` — マウントされる運用データ (configs / 認証 / logs)

**Why:** `os.path.join(__file__, ...)` のような相対解決を避け、Docker 環境でしか動かないことを
コードレベルで明示している。

**How to apply:** これらのパスを「設定可能」にしようとしない。コンテナ前提を崩すと運用手順全体が壊れる。
ローカルテストの仕組みを入れたい場合は、Docker から直接起動する形で再現する。

## Configuration loading pattern

```python
config = ConfigParser()
config.read("/insta360-auto-converter-data/configs.txt")
```

- **モジュールロード時** に `config.read()` する (各ファイルの先頭で実行)
- 設定値が無いと `KeyError` で落ちる (= フェイルファスト)
- `apps/in_app_configs.conf` は別の `ConfigParser` インスタンスで読む

**Why:** 設定の存在を起動時に確認することで、長時間動いた末に欠損で失敗する事故を避ける。

**How to apply:** 関数内で `config.read()` を呼ばない。新規モジュールでも先頭で読み込むパターンを踏襲する。

## Main loop structure (`insta360_auto_converter.py`)

```
while True:
  try:
    1. GDrive init
    2. retrieve all rawdata folders
    3. find one need-convert file pair
    4. (if found) call MediaSDK stitcher
    4.1 split video if > 7GB
    4.2 inject 360 metadata
    5. upload to Photos / YouTube
    upload .auto_done flag
  except: log
  finally: cleanup local files + remove .auto_processing flag
  sleep(3)
```

**Pattern:** ステップを番号付きコメント (`# 1.`, `# 2.`, ...) で区切り、各ステップは
**個別の `try/except`** で囲む。1 ステップ失敗しても次の周回で復旧できるようにする。

**Why:** 数十分〜数時間かかるパイプラインで、どのステップで何回目に失敗したかをログで追跡できるようにするため。

**How to apply:** メインループに新ステップを足すときは番号付きコメントと独立した `try/except` を踏襲する。
ステップ間で大きな状態を引き回す変更は避け、必要なら局所的に保持する。

## What NOT to add to this repo

- 認証情報・トークン・`configs.txt`(全て `/insta360-auto-converter-data/` 側)
- MediaSDK のバイナリやヘッダー (NDA、gitignored)
- `__pycache__/`, `.venv/`, `.python-version` など Python ローカル環境ファイル(gitignore 済)
- 個人の動画 / 写真 / ログ
- YouTube 関連のコード (2026 年に廃止済み)。再導入したい場合は要件確認の上、別 PR で議論
