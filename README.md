# insta360-auto-converter

Insta360 が出力する `.insv` / `.insp` ファイルを Google Drive から自動で取得して 360 動画 (mp4) / 写真 (jpg) に変換し、Google Photos と YouTube にアップロードする自動化パイプライン。

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
├── configs.txt
└── gphotos_auth.json
```

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

# コンテナを起動（INSTA360_DATA_DIR が /insta360-auto-converter-data にマウントされる）
make docker/run

# ログを追従
make docker/logs

# 停止・削除（破壊的操作のため /d サフィックス）
make docker/stop/d

# 停止 → ビルド → 起動 を一括実行
make docker/rebuild/d
```

`make help` で全ターゲットの一覧を確認できる。

## ファイル配置のしかた（Google Drive 側）

1. Google Drive のセットアップ手順で作成した「作業フォルダ」配下に、`.insv` / `.insp` を入れたサブフォルダをアップロードする。
2. 自動コンバータが、Google Photos のアルバム名としてそのサブフォルダ名を使い mp4 / jpg をアップロードする。
3. 例: 作業フォルダが `inst360_autoflow` の場合、`測試1_360raw` などのサブフォルダを作って `.insv` / `.insp` を入れる。

![image](https://user-images.githubusercontent.com/23136724/99519497-ec551c00-29cc-11eb-9a3b-c6cdc212a805.png)

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
├── scripts/                  # 補助スクリプト（envrc 差分チェック等）
├── .kiro/                    # Kiro 仕様駆動開発用
├── Dockerfile                # uv ベースの実行イメージ
├── Makefile                  # 開発・運用ターゲット
├── mise.toml                 # Python 3.11 + uv ピン
├── pyproject.toml            # 依存定義
├── uv.lock                   # 依存ロック
├── .envrc.sample             # direnv のサンプル
└── .dockerignore
```

## バグ修正リリースノート

### 2020-11-25
- 動画変換のストール対応、エラーハンドリング追加
- Google Photos への resumable upload 対応により 2GB 超のファイルもアップロード可能に
