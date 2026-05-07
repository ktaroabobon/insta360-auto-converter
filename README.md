# insta360-auto-converter

[![CI](https://github.com/ktaroabobon/insta360-auto-converter/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ktaroabobon/insta360-auto-converter/actions/workflows/ci.yml)

Insta360 が出力する `.insv` / `.insp` ファイルを 360 動画 (mp4) / 写真 (jpg) に変換し、**Google Drive と Google Photos の両方** にアップロードする自動化パイプライン。

入力源として 2 つのモードがある:

1. **Drive モード** (`apps/insta360_auto_converter.py`): Google Drive の作業フォルダに raw を置くと、コンテナが polling して変換 → Photos アルバムに上げる
2. **ローカル入力モード** (`apps/local_auto_converter.py`): ホスト側のローカルディレクトリ (`$INSTA360_DATA_DIR/local-input/<アルバム名>/`) に raw を置くと、コンテナが polling して **Drive サブフォルダ + Photos アルバム** の両方に上げる

![image](https://user-images.githubusercontent.com/23136724/99520953-bfa20400-29ce-11eb-9d28-5244a4614edc.png)

## なぜこのプロジェクトが必要か

Insta360 ONE X で頻繁に撮影しており、1 回の旅行で 128GB の `.insv` / `.insp` が溜まる。以下の課題を解消するためにこのパイプラインを構築した。

1. 128GB の `.insv` を mp4 に変換するには Mac 上に 128 × 2 = 256GB の空きが必要で現実的でない。
2. 公式 360Studio で変換すると CPU 使用率が張り付き、ほかの作業ができない。
3. cardboard / スマホ / Mac で 360 体験を楽しむには Google Photos へのアップロードが必須だが、Web UI からの大量アップロードは UX が悪い。

## 前提

1. `python3` と `docker` の基本操作を理解していること
2. Google Drive と Google Photos に十分な空き容量があること（GSuite for Business / Education など）
3. `docker` を 24 時間稼働させられる Linux マシン（AWS EC2 / GCE / 余っている Mac など）

## セットアップ

### 1. リポジトリ取得

```bash
git clone git@github.com:ktaroabobon/insta360-auto-converter.git
cd insta360-auto-converter
```

### 2. 認証情報の準備（NDA / セキュリティ要件あり）

以下 4 つの手順を踏む必要がある（ややハードルは高いが、運用に乗ればコスパは良い）。

1. Insta360 Media SDK の取得 ([guide](https://docs.google.com/document/d/1ob-R5ThN-1azgNpgDqXDr433MFnuSa72c6_hRM4jyY0/edit?usp=sharing))
2. Google Drive サービスアカウントの認証情報取得 ([guide](https://docs.google.com/document/d/1-hhtCnrqRcazClOKOpwbrPocnDZIUy07m_MafZAFZM0/edit?usp=sharing))
3. Google Photos OAuth 認証情報取得 ([guide](https://docs.google.com/document/d/1NEnDdgkJIp0a97D7uGtXbwle2uhmd0_cdLKD9-Whrxo/edit?usp=sharing))
4. config ファイルのセットアップ ([guide](https://docs.google.com/document/d/1y_sskH7c9jXu_5y5FjqztmesNgY2fz5fIMomOZSbkwQ/edit?usp=sharing))

完了後、リポジトリのレイアウトと外部に置くデータディレクトリは下記のようになる（データディレクトリの中身は機密。共有しないこと）。

```
insta360-auto-converter
├── Dockerfile
├── MediaSDK            # 上記 1. で取得（gitignore 済み）
└── apps
```

```
insta360-auto-converter-data   # ホスト側のどこかに配置（マウント対象）
├── auto-conversion.json
├── configs.yaml               # 設定ファイル (旧 configs.txt から YAML 化、後述)
├── gphotos_auth.json
├── album_cache.json           # Photos アルバム ID キャッシュ (自動生成、削除可)
└── local-input/               # ローカル入力モード用 (任意)
    └── <アルバム名>/            # ここに .insv / .insp を置くと自動アップロード
```

`album_cache.json` は `apps/google_photos_uploader.py` が自動生成・更新する `{album_name: album_id}` 形式の JSON。Photos Library API が `photoslibrary.appendonly` スコープでは `GET /v1/albums` を許可しないため、アルバム ID をローカル側で永続化することで同名アルバムの重複作成を防ぐ。手動で削除すると次回起動時に新規アルバムが作られる (既存 Photos 上のアルバムとは紐付かなくなるので注意)。`INSTA360_ALBUM_CACHE_PATH` 環境変数で配置先を上書きできる。

### 設定ファイル: configs.yaml

リポジトリ直下の `configs.yaml.sample` を `/insta360-auto-converter-data/configs.yaml` にコピーして、自分の環境用の値に書き換える。必要なキーは下記の通り。

| YAML キー | 内容 |
|---|---|
| `gdrive.drive_id` | Shared Drive の ID |
| `gdrive.working_folder_id` | 作業フォルダ (insta360_autoflow) の ID |
| `gmail.address` | 通知メールの送信元アドレス |
| `gmail.password` | Gmail のアプリパスワード |
| `gmail.error_mail_to` | エラー通知の送信先 |
| `upload.drive` | ローカル入力モードで Drive にアップロードするか (true/false) |
| `upload.photos` | ローカル入力モードで Photos にアップロードするか (true/false) |

`upload.drive` と `upload.photos` の **両方を false** にすることはできず、起動時に `AppConfigError` でフェイルファストする。Drive モード (`apps/insta360_auto_converter.py`) は元から Photos のみへ送るため `upload.*` トグルの影響を受けない。

#### 旧 configs.txt から configs.yaml への移行

旧形式の INI (`configs.txt`) からは下表のとおりキーを書き写す。アプリは INI へフォールバックしないので、`configs.yaml` 用意前にコンテナを再起動すると起動時に失敗してメール通知が飛ぶ。

| 旧 INI セクション / キー | 新 YAML キー |
|---|---|
| `[GDRIVE_INFO] drive_id` | `gdrive.drive_id` |
| `[GDRIVE_INFO] working_folder_id` | `gdrive.working_folder_id` |
| `[GMAIL_INFO] id` | `gmail.address` |
| `[GMAIL_INFO] pass` | `gmail.password` |
| `[GMAIL_INFO] error_mail_to` | `gmail.error_mail_to` |
| `[YOUTUBE_SETTINGS]` (廃止済) | **破棄** (現行コード未参照) |
| (新規) | `upload.drive` / `upload.photos` |

### 3. 開発環境の初期化

このリポジトリは [mise](https://mise.jdx.dev/) + [uv](https://docs.astral.sh/uv/) で Python ツールチェーンを管理する。

```bash
# .envrc.sample を .envrc にコピー → direnv allow
make cp

# mise で Python / uv をインストール → uv sync で依存をインストール
make init
```

`.envrc` で `INSTA360_DATA_DIR` を実環境のデータディレクトリパスに書き換える。

```bash
# 例
export INSTA360_DATA_DIR=$HOME/Documents/insta360-auto-converter-data
```

## 実行

通常は Docker コンテナとして 24 時間稼働させる。

```bash
# Docker イメージをビルド
make docker/build

# Drive モードで起動 (Drive 上の作業フォルダを polling)
make docker/run

# ローカル入力モードで起動 ($INSTA360_DATA_DIR/local-input を polling)
make docker/run/local

# ログを追従
make docker/logs

# 停止・削除（破壊的操作のため /d サフィックス）
make docker/stop/d

# 停止 → ビルド → 起動 を一括実行
make docker/rebuild/d
```

`make help` で全ターゲットの一覧を確認できる。

## NVIDIA GPU で動かす (WSL2 / Linux)

Insta360 MediaSDK は **NVIDIA CUDA 11.7 + libnvcuvid** を要求する。GPU 非搭載環境 (Mac / linux/amd64 emulation) では SDK の dual-lens stitching が動かず、出力が dual-fisheye SBS のままになる。**動画パイプライン全体を正しく動かすには NVIDIA GPU 環境が必須**。本セクションは Windows 11 + WSL2 + RTX 系 GPU を想定したセットアップ手順。

### stitch_type について (`apps/stitcher.py`)

動画 / 写真とも `dynamicstitch` (`STITCH_TYPE::DYNAMICSTITCH`) を使う。GPU 上では `arvrender::DynamicStitcher` が CUDA で動き equirectangular を生成する。GPU 不在環境では `flow estimator failed` で落ちて出力が dual-fisheye SBS のままになるため `INSTA360_GPU=1` 起動が事実上必須。

aistitch (Insta360 公式は X5 で推奨) は MediaSDK 3.1.1 同梱の `example/main.cc` + `libMediaSDK.so` に `SetAiStitchModelFile` 系のシンボルが無く、`-stitch_type aistitch` だけでは model 適用が走らず出力 mp4 が「全フレーム真っ黒」になる (PR #12 / WSL2 + RTX 3070 で実機確認)。aistitch を有効化するには SDK example をカスタムビルドして `SetAiStitchModelFile("ai_stitcher_v2.ins")` を呼び出す追加実装が必要 (今後の課題)。

### 前提

- Windows 11 + WSL2 (Ubuntu 22.04 / 24.04 推奨)
- NVIDIA GPU (RTX 30/40 系など、CUDA Compute Capability 8.x 以上)
- NVIDIA Windows ドライバ (Game Ready / Studio どちらでも、ver 470+)
- Docker Desktop for Windows (4.x 以降、WSL2 backend integration ON)

### セットアップ確認

WSL2 ターミナルで以下が成功すれば下準備 OK:

```bash
# 1. ホストで GPU 認識
nvidia-smi

# 2. Docker → コンテナ → GPU パススルーが通る
docker run --rm --gpus all nvidia/cuda:11.7.0-base-ubuntu22.04 nvidia-smi
```

Docker Desktop 4.x は **NVIDIA Container Toolkit を内蔵** しているので、追加 install 不要で `--gpus all` が即使える。手動で `nvidia-container-toolkit` を入れる必要はない (詳細: [NVIDIA CUDA on WSL User Guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html))。

### 起動

`INSTA360_GPU=1` を付けるだけ:

```bash
# ローカル入力モードを GPU 有効で起動
INSTA360_GPU=1 make docker/run/local

# Drive モードも同様
INSTA360_GPU=1 make docker/run
```

未指定 (Mac / GPU 無し環境) では `--gpus all` は付かないので副作用なし。

### 動作確認

GPU が正しく通っているか確認:

```bash
make docker/exec
# コンテナ内で
nvidia-smi      # ホスト GPU が見えれば OK
ls /usr/lib/x86_64-linux-gnu/libnvcuvid.so.1   # NVIDIA Container Toolkit が host から注入する
```

X5 動画を `local-input/<アルバム名>/` に置いてしばらく待ったあと、`docker exec insta360-auto-converter ls /insta360-auto-converter/apps/*.mp4` で出力 mp4 が生成されているか確認。フレームを取り出して目視:

```bash
docker exec insta360-auto-converter python3 -c "from moviepy.editor import VideoFileClip; c=VideoFileClip('/insta360-auto-converter/apps/VID_xxx.mp4'); c.save_frame('/tmp/check.jpg', t=2.0)"
docker cp insta360-auto-converter:/tmp/check.jpg ./
```

正しく動いていれば `check.jpg` は **equirectangular** (横長 2:1、被写体が中央付近にも分布) になっているはず。**dual-fisheye が左右に並んだまま** だと SDK の stitching が走っていない (= GPU が通っていない or libnvcuvid が見えていない)。

### トラブルシュート

- **`nvidia-smi` が WSL2 で見えない** → Windows 側のドライバが古い、または WSL カーネルが古い (`wsl --update`)
- **`docker run --gpus all` で `unknown flag` エラー** → Docker Desktop が古い、または WSL2 backend integration が OFF
- **コンテナで `libnvcuvid.so.1: cannot open shared object`** → Docker Desktop の GPU 機能が無効。Settings > General > "Use the WSL 2 based engine" を確認

## ファイル配置のしかた

### Drive モード (Google Drive 側)

1. Google Drive のセットアップ手順で作成した「作業フォルダ」配下に、`.insv` / `.insp` を入れたサブフォルダをアップロードする。
2. 自動コンバータが、Google Photos のアルバム名としてそのサブフォルダ名を使い mp4 / jpg をアップロードする。
3. 例: 作業フォルダが `inst360_autoflow` の場合、`測試1_360raw` などのサブフォルダを作って `.insv` / `.insp` を入れる。

![image](https://user-images.githubusercontent.com/23136724/99519497-ec551c00-29cc-11eb-9a3b-c6cdc212a805.png)

### ローカル入力モード (ホスト側ディレクトリ)

1. `$INSTA360_DATA_DIR/local-input/<アルバム名>/` に `.insv` / `.insp` を置く (例: `local-input/trip-2026-04/VID_*_00_*.insv`)。
2. `make docker/run/local` で起動したコンテナがディレクトリを polling し、変換後に **Drive (working folder 配下に同名サブフォルダを自動作成) と Google Photos アルバム** の両方にアップロードする。
3. 完了したファイルには `<元ファイル名>.done` マーカーが置かれ、次回以降スキップされる (再処理したい場合はマーカーを削除)。

`INSTA360_LOCAL_INPUT_ROOT` 環境変数で監視ディレクトリを上書き可能 (デフォルト: `/insta360-auto-converter-data/local-input`)。

## 対応カメラとファイル命名規約

| カメラ | 動画 | 写真 |
|---|---|---|
| Insta360 ONE X (~2018) | `*_00_*.insv` (左目) + `*_10_*.insv` (右目) のペアを SDK の dual-input に渡す | `*_00_*.insp` 単独 |
| Insta360 X5 (2024-) | `*_00_*.insv` 単独 (dual-lens を 1 ファイルに統合、`_10_` は出力されない) | `*_00_*.insp` 単独 |

サフィックス `_convert` (`*_convert.mp4` / `*_convert.jpg`) は MediaSDK での stitching 直後の中間ファイル、サフィックス無し (`*.mp4` / `*.jpg`) はメタデータ注入後のアップロード対象 (内部仕様)。

X5 と ONE X は同じディレクトリに混在させても問題ない (左目ファイル名から `_10_` ペアの有無を自動判定し、ペア有なら ONE X、無なら X5 として扱う)。

X5 は SD カード上に同じ録画の低解像度プロキシ `LRV_*_01_*.lrv` も同時生成するが、SDK に `.insv` と一緒に渡すと `couple_media_frame_reader` で frame 不整合になり stitching が走らず dual-fisheye SBS 出力になる。**`.lrv` は SDK には渡さない** (検出対象外。`local-input/<アルバム>/` に `.lrv` ファイルが転がっていても無視されるので、SD カードからまるごとコピーしても問題ない)。

## マルチプロセス

- 同じ Google アカウントに対して複数のインスタンスでコンテナを並走させられる。Google Drive 上のフラグファイルでタスク管理しているため、N 台のコンテナが同じファイルを掴む可能性は低い（厳密な排他はしておらず、たまに無駄な計算が発生する程度の素朴な実装）。

## 制限事項

1. HDR 写真は MediaSDK 側で merge 未対応のため、一部の写真は手ぶれ補正が掛からない。

## 開発メモ

### バージョン方針

- Python は **3.11** を採用。`apps/video_processor.py` が `from moviepy.editor import VideoFileClip` という moviepy 1.x 系 API を使っており、Python 3.12 以降では `imp` モジュール削除の影響で moviepy 1.x が動かないため。
- Python 3.12+ に移行する場合は `apps/video_processor.py` の moviepy 関連 import を 2.x 系の API に書き換える必要がある。

### 依存

`pyproject.toml` で管理。

- `google-api-python-client>=2.100`
- `google-auth-oauthlib>=1.0`
- `requests-toolbelt>=1.0`
- `moviepy<2.0`

`uv.lock` をコミットしているので、`uv sync --frozen` で再現可能。

### 主要なディレクトリ

```
insta360-auto-converter
├── apps/                     # Python アプリ本体
├── tests/                    # pytest ユニットテスト
├── scripts/                  # 補助スクリプト（envrc 差分チェック等）
├── .kiro/                    # Kiro 仕様駆動開発用
├── .github/workflows/        # GitHub Actions CI
├── Dockerfile                # uv ベースの実行イメージ
├── Makefile                  # 開発・運用ターゲット
├── mise.toml                 # Python 3.11 + uv ピン
├── pyproject.toml            # 依存定義
├── uv.lock                   # 依存ロック
├── .envrc.sample             # direnv のサンプル
└── .dockerignore
```

### テスト

`tests/` 配下に pytest 形式のユニットテストを置く。**今後の実装はすべて TDD で進める** (詳細は `.kiro/steering/testing.md`)。

```bash
make test          # uv run pytest
```

## バグ修正リリースノート

### 2020-11-25
- 動画変換のストール対応、エラーハンドリング追加
- Google Photos への resumable upload 対応により 2GB 超のファイルもアップロード可能に
