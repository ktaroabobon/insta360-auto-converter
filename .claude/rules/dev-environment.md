# 開発環境ルール

## ツールチェーン

- **Python**: 3.11 (`mise.toml` でピン)
- **パッケージマネージャ**: `uv` (`uv.lock` をコミット、`uv sync --frozen` で再現可能)
- **環境変数**: `direnv` + `.envrc` (`.envrc.sample` をコピー)
- **Docker**: 本番ランタイム (`docker/build`, `docker/run`)

## 初期セットアップ

```bash
make cp     # .envrc.sample を .envrc にコピー → direnv allow
make init   # mise install + uv sync
```

`.envrc` の `INSTA360_DATA_DIR` は実環境のデータディレクトリパスに書き換える。

## よく使う Make ターゲット

| ターゲット | 用途 |
|---|---|
| `make lint` | ruff (CI と同じ) |
| `make lint/fix` | ruff 自動修正 |
| `make syntax` | python -m compileall |
| `make test` | pytest (CI と同じ) |
| `make docker/build` | Docker イメージビルド |
| `make docker/run` | Drive モードで起動 |
| `make docker/run/local` | ローカル入力モードで起動 |
| `make docker/logs` | コンテナログ追従 |
| `make docker/stop/d` | コンテナ停止・削除 (`/d` は破壊的操作の意思表示) |
| `make docker/rebuild/d` | 停止 → ビルド → 起動 |

## 破壊的操作のガード

Docker の停止 / 再ビルドは `/d` サフィックス付きのターゲットを使う:

- `make docker/stop` → 警告のみ表示、`make docker/stop/d` を案内
- `make docker/rebuild` → 同上、`make docker/rebuild/d` を案内

**意図しない `make docker/stop` 等の暴発を防ぐための仕組み**。
新しい破壊的操作を Makefile に追加するときは同パターンを踏襲する。

## ホストでの直接実行

- 本番は **必ず Docker コンテナ内で実行する** (パスがハードコード)
- ホストから `make run` で `apps/insta360_auto_converter.py` を直接起動する仕組みはあるが、
  あくまで「Python 単体の動作確認」用。MediaSDK バイナリは動かない

## ローカル input mount

ローカル入力モード (`make docker/run/local`) を使うとき:

```
$INSTA360_DATA_DIR/local-input/
├── trip-2026-04/        # アルバム名 = サブディレクトリ名
│   ├── VID_*_00_*.insv
│   └── VID_*_10_*.insv
└── 別のアルバム/
    └── IMG_*_00_*.insp
```

`.envrc` で `INSTA360_DATA_DIR` をホスト側の任意のパスに向けておけば、
そのまま container の `/insta360-auto-converter-data/local-input/` として見える。
