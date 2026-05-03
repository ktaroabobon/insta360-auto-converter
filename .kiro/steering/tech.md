---
name: Tech Steering
description: ランタイム・主要依存・外部サービス・ビルド/デプロイの規約と、その背景にある技術的判断
type: tech
inclusion: always
---

# Tech Steering

## Runtime

- **Base image**: `ubuntu:focal` (20.04)
- **Python**: 3.8 系 (Ubuntu Focal 同梱 / `pip3` 直インストール、仮想環境は使わない)
- **コンパイラ**: g++ (C++11) — Insta360 MediaSDK の example/main.cc を `stitcherSDKDemo` にビルドするため
- **コンテナ前提**: コードは `/insta360-auto-converter/...` に COPY され、データは `/insta360-auto-converter-data/`
  へのホストマウントで供給される。**ホストでの直接実行はサポートされない**(パスがハードコード)

## External services

| サービス | 用途 | 認証方式 | クレデンシャル配置 |
|---|---|---|---|
| Google Drive | raw 取得 / フラグファイル / (将来の) アップロード | サービスアカウント JSON | `/insta360-auto-converter-data/auto-conversion.json` |
| Google Photos | 写真の公開先アルバム | OAuth user credentials | `/insta360-auto-converter-data/gphotos_auth.json` |
| YouTube Data API v3 | 動画の公開先 playlist | OAuth user credentials | `/insta360-auto-converter-data/youtube_auth.json` |
| Gmail SMTP | エラー通知メール | SMTP パスワード (configs.txt) | `/insta360-auto-converter-data/configs.txt` |
| Insta360 MediaSDK | 360° stitching | NDA 配布 (要申請) | リポジトリ直下に `MediaSDK/` を配置(gitignored) |

**Why:** 認証情報・SDK バイナリは法的・セキュリティ上リポジトリに含められないため、
ビルド時に `COPY` される `MediaSDK/` と、ランタイムにマウントされる `-data/` が完全に分離されている。

**How to apply:** 新しい外部サービスを追加するときは、認証ファイルを `/insta360-auto-converter-data/` 配下に置き、
`configs.txt` の新セクションでパス・ID を渡す既存パターンを踏襲する。リポジトリに鍵を入れる提案はしない。

## Key Python libraries

- `google-api-python-client` — Drive / YouTube の高レベルクライアント
- `google-auth-oauthlib` — Photos / YouTube の OAuth user flow (`InstalledAppFlow`)
- `requests-toolbelt` — Photos のレジューム可能アップロード
- `moviepy` — 動画分割 (`ffmpeg_extract_subclip`, `VideoFileClip`)
- `configparser` (標準) — INI 形式の設定読み込み
- `logging.handlers.RotatingFileHandler` — 50MB × 5 ローテーション

## Vendored binaries / tools

リポジトリ直下に第三者ツールを **vendored** として置く。pip で入らないか、特定バージョンに固定したいもの。

- `MediaSDK/` — Insta360 SDK(NDA、gitignored、ビルド時にコンテナへ COPY)
- `Image-ExifTool-12.10/` — 写真への XMP-GPano 注入 CLI
- `spatial-media/` — Google 製の 360° MP4 メタデータ注入ツール

**Why:** いずれもバージョン固定 or 配布制約があり、pip 等のパッケージマネージャで再現できない。
Docker ビルドで丸ごと固める方が再現性が高い。

**How to apply:** これらのディレクトリを「中身を読んで挙動を理解する対象」として扱わない。
バージョンアップの要件が来たら、まず `Dockerfile` のインストール手順とパス参照(`apps/insta360_auto_converter.py`
の `./Image-ExifTool-12.10/exiftool` や `spatial-media/spatialmedia` ハードコード)を併せて更新する。

## Configuration pattern

設定は **3 層** に分かれている。混同しないこと。

1. **`configs.txt`** (運用者編集、コンテナ外):
   `[GDRIVE_INFO]`, `[YOUTUBE_SETTINGS]`, `[GMAIL_INFO]` など。Drive ID、working folder ID、
   YouTube channel ID、メール宛先・パスワード。**個人ごと・環境ごとの値**。
2. **`apps/in_app_configs.conf`** (リポジトリ管理):
   `[FILES_TO_CLEAN_UP]` の glob パターンなど、コードと連動するアプリ内デフォルト。
3. **OAuth トークン JSON** (コンテナ外、自動更新):
   `gphotos_auth.json`, `youtube_auth.json`。`refersh_gphotos_cred.py` でローカル PC から取得して配置。

**Why:** 個人ごとに変わる値・コードと連動する値・自動更新される値が混じると運用ミスが起きるため。

**How to apply:** 新しい設定項目を増やすときは、**運用者が変える値か、コードと一緒に動く値か** を判別して
正しいファイルへ追加する。`configs.txt` のサンプルは README リンク先の Google Doc にあるためコード側には置かない。

## Logging

- `apps/utils.py:log()` がプロジェクト全体の標準。直接 `print` や `logging.getLogger` を呼ばない。
- 出力は **stdout (docker logs 用)** + **`/insta360-auto-converter-data/logs/` へのローテーションファイル** の二系統。
- `mail_out=True` を渡すとエラー扱い (`logger.error`) になり、Gmail SMTP で運用者へ通知が飛ぶ。

**Why:** 一箇所で制御することでログ書式とメール通知を一貫させ、ライブラリ追加で挙動が変わるリスクを避ける。

**How to apply:** 新規モジュールでも `from utils import log` を踏襲する。ログ書式の変更は `utils.py` 側で行う。

## Build & run

```bash
# build (リポジトリルートで)
sudo docker build -t insta360-auto-converter .

# run (--data ディレクトリを必ずマウント)
sudo docker run -d \
  -v /path/to/insta360-auto-converter-data:/insta360-auto-converter-data \
  insta360-auto-converter
```

- ビルド時に `g++` で MediaSDK example をコンパイルするため、`MediaSDK/` ディレクトリが必須
- `Dockerfile` は `google.auth.transport.requests._DEFAULT_TIMEOUT` を 120s → 86400s に書き換えるパッチを当てている
  (大容量アップロードのタイムアウト回避)。Python パッケージのバージョンを上げるとパッチパスが変わる可能性がある

## Multi-process pattern

同じ Google アカウントに対して **複数コンテナを別マシンで同時起動** することが想定されている。
調停は Drive 上の `.auto_processing` フラグファイルだけで行うため、競合は完全には防げない (best-effort)。
重複処理が稀に起きるが計算資源の無駄に留まる、という割り切り。

**Why:** 厳密なロックを Drive 上で実装するコストよりも、計算資源の二重消費の方が安価という判断。

**How to apply:** スケールアウトに関わる機能を提案するときは、フラグファイル方式の限界を尊重する。
DB やロックサービスの導入は単一テナント設計の範囲を超えるため、要件確認が必須。
