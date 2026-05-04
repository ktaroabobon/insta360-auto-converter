# Research Log: selective-upload-targets

## Discovery Scope

軽量 (Light) discovery を実施。本機能は既存システムへの拡張 (extension) であり、
- アップロード呼び出し点は `apps/local_auto_converter.py:process_pending` 1 箇所
- config 読み込みは `apps/utils.py` / `apps/insta360_auto_converter.py` / `apps/local_auto_converter.py` の 3 ファイルに分散
- 新規外部依存は YAML パーサのみ

なので大規模な discovery は不要と判断。

## Investigations

### I1. 既存 config 読み込みパターン

| ファイル | 現状 | 影響 |
|---|---|---|
| `apps/utils.py:30-31` | `config = ConfigParser(); config.read("/insta360-auto-converter-data/configs.txt")`、`send_mail` 内で `config["GMAIL_INFO"]["pass"|"id"|"error_mail_to"]` を参照 | YAML 化対象 |
| `apps/insta360_auto_converter.py:22-23` | 同上、`config["GDRIVE_INFO"]["drive_id"|"working_folder_id"]` を main で参照 | YAML 化対象 |
| `apps/local_auto_converter.py:184` | `main()` 内で `config.read()`。Drive ID と working_folder_id を取得 | YAML 化対象 + toggle 追加 |
| `apps/insta360_auto_converter.py:25-26` | `in_app_configs.conf` を別 `ConfigParser` で読む | **対象外** (リポジトリ管理側、boundary 外) |

すべてモジュールロード時 / `main()` 冒頭で読まれている (フェイルファスト)。新しい loader も同パターンを踏襲する。

### I2. 既存 INI スキーマと YAML 写像

`configs.txt` (INI) → `configs.yaml` (YAML) 写像案:

| INI | YAML |
|---|---|
| `[GDRIVE_INFO] drive_id` | `gdrive.drive_id` |
| `[GDRIVE_INFO] working_folder_id` | `gdrive.working_folder_id` |
| `[GMAIL_INFO] id` | `gmail.address` |
| `[GMAIL_INFO] pass` | `gmail.password` |
| `[GMAIL_INFO] error_mail_to` | `gmail.error_mail_to` |
| (新規) | `upload.drive` (bool) |
| (新規) | `upload.photos` (bool) |
| `[YOUTUBE_SETTINGS]` (廃止済、参照無し) | **マイグレーション後ドロップ** (tech.md 注記により後方互換不要) |

**根拠:** `apps/utils.py` および `apps/insta360_auto_converter.py` の `config[...]` アクセス箇所を grep 済。
`tech.md` で `[YOUTUBE_SETTINGS]` は「現在参照されていない」と明示。

### I3. YAML パーサ採用判断

| 候補 | 採否 | 理由 |
|---|---|---|
| **PyYAML 6.x** | ✅ 採用 | デファクトスタンダード、MIT、`safe_load` で型情報あり、Python 3.11 対応、活発にメンテ |
| ruamel.yaml | ✗ | コメント保持・往復編集向けで本要件には過剰 |
| tomllib (TOML) | ✗ | ユーザー指示 (YAML) に沿わない |
| 自作パーサ | ✗ | 車輪の再発明 |

`safe_load` は untrusted YAML の任意コード実行を防ぐ。本ツールの config は運用者が書くため厳格な untrusted ではないが、デフォルトの安全策として `safe_load` を使用する。

### I4. スキーマ検証ライブラリ採用判断

| 候補 | 採否 | 理由 |
|---|---|---|
| **手書き検証** | ✅ 採用 | キー数 ~7、ロジック小、依存追加コストの方が高い |
| pydantic v2 | ✗ | 6 キーに対して overkill、型チェック以外のメリット小 |
| jsonschema | ✗ | スキーマ DSL 学習コスト、型情報を別管理する負担 |

dataclass + 必須キー検査関数 (~50 行) で十分。

### I5. テストインフラへの影響

`tests/conftest.py` は `INSTA360_LOGS_DIR` を tmpdir に向けて副作用を回避している。
新 loader (`apps/app_config.py`) は **モジュールロード時** に `configs.yaml` を読まないようにすれば
(関数ベースで遅延ロードする)、テストは fixture で都度 YAML ファイルを `tmp_path` に書いて呼び出せる。

ただし `apps/utils.py` は現状モジュールロード時に config 読み込み + `send_mail` がそれを参照するため、
**`utils.py` も loader を遅延呼び出しに変える** か、テスト fixture で `configs.yaml` を `INSTA360_CONFIGS_PATH` 等で
差し替えられるようにする必要がある。後者を選択すると import 時失敗を避けられる。

## Design Decisions

### D1. Generalization

- アップロード先 toggle を `UploadTargets(drive: bool, photos: bool)` 値オブジェクトとして抽象化
- 「N 個目の上げ先」が増える場合は dataclass にフィールドを追加するだけ。プラグイン化等の過剰汎化はしない (simplicity ルール準拠)

### D2. Build vs Adopt

- **YAML パース**: PyYAML を採用 (I3 参照)
- **スキーマ検証**: 自作 (I4 参照)
- **設定オブジェクト**: stdlib `dataclasses` を採用 (型安全 + 不変)

### D3. Simplification

- `ConfigLoader` クラスは作らない。関数 `load_app_config(path: Path) -> AppConfig` で十分
- 環境変数による toggle 上書きは追加しない (`INSTA360_LOCAL_INPUT_ROOT` 等の既存 env 変数とは性質が違う)
- hot-reload なし

### D4. 互換性ポリシー

- INI へのフォールバックなし (Req 3.5 準拠)
- 移行は運用者の手作業 (README にマッピング表を載せる)
- `[YOUTUBE_SETTINGS]` は YAML へ移植せずに廃棄 (現行コード未参照)

### D5. テスト容易性のための loader API

`apps/utils.py` がモジュールロード時に config を必要とする現状を踏まえ:

- `load_app_config(path: Path | None = None) -> AppConfig`
- `path is None` の場合: `INSTA360_CONFIGS_PATH` 環境変数を見て、未設定なら `/insta360-auto-converter-data/configs.yaml`
- テストは `INSTA360_CONFIGS_PATH` を `tmp_path` 配下の YAML に向けて副作用を抑える

## Risks and Mitigations

| リスク | 影響 | 緩和策 |
|---|---|---|
| `apps/utils.py` の import 時 config 読み込みがテスト時に副作用を起こす | テスト全体が壊れる | `INSTA360_CONFIGS_PATH` で差替可能にし、`conftest.py` で tmp に向ける。失敗時は `INSTA360_LOGS_DIR` と同様にフォールバック (warning ログ) させる |
| 運用者が YAML 移行を忘れたままアップグレード | 起動失敗 (フェイルファスト) | README に明確な移行手順、`mail_out=True` で運用者にメール通知 |
| 既存キーの YAML 化漏れ (例えば `error_mail_to`) | SMTP 通知が壊れる | `app_config.py` の必須キーリストを単一の真実とし、テストで全キー存在チェック |
| `process_pending` の API 変更で既存テストが壊れる | TDD 失敗 | API 変更は **追加引数** で行い、デフォルト値で既存テストを保護しない (TDD 原則: テストも先に直す) |

## Out of Discovery Scope

- マルチテナント化、Web UI、認証情報の暗号化 (steering の Out of Scope に明示)
- `apps/in_app_configs.conf` の YAML 化 (本機能の boundary 外)
- 動画 7GB 分割閾値の config 化 (将来要件、本機能では触らない)
