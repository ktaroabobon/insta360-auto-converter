# コーディングスタイル

このファイルがコーディングルールの Single Source of Truth。

## ruff 準拠

`pyproject.toml` の `[tool.ruff]` で有効なルール:

- **`E9`**: 構文エラー
- **`F63`**: 比較のミス (`is`/`==` の取り違え)
- **`F7`**: 構文系の論理エラー (ループ外 break など)
- **`F82`**: 未定義名の使用
- **`F811`**: 同名再定義
- **`F821`**: 未定義の参照
- **`F823`**: ローカル変数を代入前に参照

**段階的にルールを追加する方針**。E/W/I/B などのスタイル系は当面追加しない
(既存コードの大規模再フォーマットを避けるため)。

`make lint` (= `uv run ruff check apps scripts tests`) を CI と同じコマンドで回せる。

## Python 命名規約

- **ファイル / 関数 / 変数**: `snake_case` (PEP 8 準拠)
- **クラス**: `PascalCase`、サービス名 + `Service` / `Handler` / `Processor`
- **モジュール内定数**: 大文字スネーク (`SDK_PATH`, `NO_FOUND_IN_A_ROW_LIMIT`)

## raw ファイル / 出力ファイル命名 (Insta360 仕様準拠)

- `*_00_*.insv` = 左目動画 (本体), `*_10_*.insv` = 右目動画 (ペア)
- `*_00_*.insp` = 左目写真 (写真は片目だけ存在)
- `_convert.mp4` / `_convert.jpg` = stitching 直後 (メタデータ未注入)
- サフィックス除去後 (例: `foo.mp4`) = メタデータ注入済み、アップロード対象

これらは外部仕様で変更不可。コード中で `'_00_'` / `_convert` 等を扱う箇所は
本ルールに従って解釈する。

## エラーハンドリング

- **メインループの各ステップは独立した `try/except` で囲む**

  1 ステップ失敗しても次の周回で復旧できるようにする。
  数十分〜数時間かかるパイプラインで、どのステップで何回目に失敗したかを
  ログで追跡できるようにするため。

- **重大なエラーは `log(msg, mail_out=True)` で SMTP 通知**

  運用者にメールが飛ぶ。気軽に True を付けないこと (メールスパムになる)。

- **失敗時の状態管理**

  - Drive モード: `.auto_broken` フラグを Drive にアップロード (再処理対象外として印付け)
  - ローカル入力モード: `.done` マーカーは作らない (次の周回で再試行可能な状態を維持)

## ロギング

- **`apps/utils.py:log()` がプロジェクト全体の標準**

  直接 `print` や `logging.getLogger` を呼ばない。
  ログ書式 / メール通知が一貫しなくなる。

- 出力は **stdout (docker logs 用)** + **`$INSTA360_LOGS_DIR/` へのローテーションファイル** の二系統
- `mail_out=True` を渡すとエラー扱い (`logger.error`) になり、Gmail SMTP で運用者へ通知が飛ぶ

## 設定読み込みパターン

```python
from app_config import load_app_config

_app_config = load_app_config()  # YAML を読み AppConfig (frozen dataclass) を返す
```

- **モジュールロード時** に `load_app_config()` を呼ぶ (各エントリポイントの先頭で実行)
- `configs.yaml` 不在 / 必須キー欠落 / 型不一致 / 両 `upload.*` false で `AppConfigError` を上げ、フェイルファスト
- 旧 INI (`configs.txt`) へのフォールバックは禁止 (`apps/app_config.py` で明示的にしていない)
- `apps/in_app_configs.conf` (アプリ内デフォルト) は引き続き別の `ConfigParser` インスタンスで読む

**関数内で `load_app_config()` を呼ばない**。新規モジュールでも先頭で読み込むパターンを踏襲する。テスト時は `INSTA360_CONFIGS_PATH` 環境変数で tmp YAML に差し替え可能。

## 文字列フォーマット

- 既存コードは `'{}'.format(...)` スタイル。新規コードでは f-string を優先しても構わないが、
  既存の log メッセージスタイルと混ぜすぎない。

## チェックリスト

PR 出す前に:

- [ ] `make lint` が green
- [ ] `make syntax` (compileall) が green
- [ ] `make test` (pytest) が green
- [ ] 新規追加した print / logging は `utils.log` 経由か?
- [ ] mail_out=True を不必要に多用していないか?
