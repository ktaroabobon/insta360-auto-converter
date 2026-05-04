# Implementation Tasks: selective-upload-targets

タスクは TDD サイクル (Red → Green → Refactor) で実装する前提。
test 用語と impl 用語を明確に分離し、test 先行を必須とする (`.kiro/steering/testing.md`)。
`(P)` 印は、直前のピアと並列実行が安全なタスク。

- [ ] 1. Foundation: 依存関係とテスト基盤の準備
- [ ] 1.1 YAML パーサ依存を追加し、ロックファイルを更新する
  - `pyproject.toml` の `dependencies` に PyYAML (バージョン 6.x 系) を追加し、`uv lock` で `uv.lock` を再生成する
  - `make lint` / `make syntax` / `make test` がすべて green のままであることを確認する
  - 観測可能な完了状態: `uv.lock` 内に PyYAML のエントリがあり、`uv run python -c "import yaml; print(yaml.__version__)"` が 6.x を出力する
  - _Requirements: 3.1_
  - _Boundary: Project Dependencies_

- [ ] 1.2 設定パスを差し替えるテスト fixture を導入する
  - 新規 autouse fixture が、テスト時に `INSTA360_CONFIGS_PATH` を `tmp_path` 配下のダミー YAML に向けるようにする
  - ダミー YAML はすべての必須キーをプレースホルダ値で含み、後続の各テストが副作用なく `apps.utils` を import できる構造にする
  - 既存の `_TEST_LOGS_DIR` パターンに揃え、テストプロセス全体で 1 度だけ生成し、不要時は cleanup する
  - 観測可能な完了状態: `pytest -q` が現状のテストすべて green のまま通り、conftest fixture が新たな YAML パスを設定するログ/挙動が確認できる
  - _Requirements: 3.1, 3.2_
  - _Boundary: Test Infrastructure_

- [ ] 2. AppConfigLoader を TDD で構築する
- [ ] 2.1 AppConfigLoader の失敗するユニットテストを書く
  - 正常な YAML を渡したときに、`AppConfig` が gdrive / gmail / upload の全フィールドを保持して返ることを期待するテストを書く
  - ファイル不在 / YAML パース失敗 / 必須キー欠落 / 型不一致 (`upload.drive` を文字列にする等) / `upload.drive` と `upload.photos` の両 false で `AppConfigError` が送出されることを期待するテストを書く
  - エラーメッセージにファイルパスや欠落キー名が含まれることをアサーションする
  - `INSTA360_CONFIGS_PATH` 環境変数による上書きと、`configs.txt` が同じディレクトリに存在しても fallback しないことを検証するテストを書く
  - 観測可能な完了状態: 新規追加したテスト群が `pytest -q` で **必ず赤** になり (loader 未実装のため import error または assert 失敗)、ログから「未実装 / 期待値不一致」が確認できる
  - _Requirements: 1.1, 1.6, 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: AppConfigLoader_

- [ ] 2.2 AppConfigLoader を最小実装で green にする
  - 不変な dataclass (GdriveConfig / GmailConfig / UploadTargets / AppConfig) と `AppConfigError` を定義する
  - YAML を `safe_load` で読み、必須キー (`gdrive.drive_id`, `gdrive.working_folder_id`, `gmail.address`, `gmail.password`, `gmail.error_mail_to`, `upload.drive`, `upload.photos`) を 1 つでも欠けたら欠落キー名を含む `AppConfigError` を raise する
  - `upload.drive` と `upload.photos` の bool 型チェック、両 false の組合せ検出を行う
  - パスは `INSTA360_CONFIGS_PATH` 環境変数 → `/insta360-auto-converter-data/configs.yaml` の優先順で解決し、`configs.txt` への fallback を一切行わない
  - 観測可能な完了状態: 2.1 で書いた全テストが green になり、`pytest -q` がフルセットで通る
  - _Requirements: 1.1, 1.6, 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: AppConfigLoader_

- [ ] 3. LocalUploadGate を TDD で構築する
- [ ] 3.1 process_pending の UploadTargets ゲーティング失敗テストを書く
  - 既存の `test_local_auto_converter.py` を拡張し、`process_pending` の新しい `upload_targets` 引数 (UploadTargets) を取る前提のテストに揃える
  - `UploadTargets(drive=True, photos=False)` 構成で Photos uploader が呼ばれず、Drive subfolder 解決と `upload_file_to_folder` のみが呼ばれ、`.done` マーカーが作られることを検証
  - `UploadTargets(drive=False, photos=True)` 構成で `gs.get_or_create_subfolder` / `gs.upload_file_to_folder` が呼ばれず、Photos uploader のみが呼ばれ、`.done` が作られることを検証
  - 片方のみ有効な構成で、その有効先がアップロード失敗 (例外) を起こした場合に `.done` マーカーが作られないことを検証
  - toggle off によるスキップでは `mail_out=True` ログ (= operator alert email) が呼ばれないことを検証
  - 観測可能な完了状態: 新テストが `pytest -q` で **赤** (process_pending が新引数に対応していない / 旧挙動)
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 4.2_
  - _Boundary: LocalUploadGate_

- [ ] 3.2 process_pending に UploadTargets ゲートを実装して green にする
  - `process_pending` のシグネチャに `upload_targets: UploadTargets` を必須引数として追加
  - `upload_targets.drive` が True の場合のみ Drive subfolder 解決 + `upload_file_to_folder` を呼ぶ
  - `upload_targets.photos` が True の場合のみ Photos uploader を呼ぶ
  - 有効な上げ先がすべて成功した場合のみ `mark_done(left)` を呼ぶ
  - toggle off の skip は info ログのみ、`mail_out=True` を渡さない
  - 観測可能な完了状態: 3.1 のテストすべてが green、既存テストも green、`pytest -q` がフルセット通過
  - _Requirements: 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 4.2_
  - _Boundary: LocalUploadGate_

- [ ] 4. 既存 config 消費者を AppConfigLoader 経由に切替える
- [ ] 4.1 (P) UtilsMailConsumer の SMTP 認証読込を AppConfigLoader 経由にする
  - `apps/utils.py` のモジュールロード時 `ConfigParser` 関連を削除し、`load_app_config()` で読み込んだ `AppConfig.gmail` を保持する
  - `send_mail()` は `gmail.address` / `gmail.password` / `gmail.error_mail_to` を AppConfig 経由で参照する
  - `log()` 関数の外部 API は不変 (シグネチャと振る舞い)
  - 既存テストの green を維持しつつ、SMTP 認証取得が YAML 経由になっていることを検証する追加テスト 1 件を `tests/test_utils.py` に加える
  - 観測可能な完了状態: `tests/test_utils.py` の新旧テスト全 green、リグレッションテストが SMTP 認証の YAML 由来を確認している
  - _Depends: 1.2, 2.2_
  - _Requirements: 3.1, 3.4, 4.3_
  - _Boundary: UtilsMailConsumer_

- [ ] 4.2 (P) DriveModeConfigConsumer の Drive ID 読込を AppConfigLoader 経由にする
  - `apps/insta360_auto_converter.py` のモジュールロード時 `ConfigParser` 関連を削除し、`load_app_config()` 由来の `AppConfig.gdrive` を main() で参照する
  - `[GDRIVE_INFO]` の参照箇所すべてを `_app_config.gdrive.drive_id` / `_app_config.gdrive.working_folder_id` に置換する
  - 動作 (Drive モードのアップロード先や フラグファイル運用) を一切変更しない
  - import smoke test (`tests/test_drive_mode_config_consumer_loads_yaml`) を追加し、`INSTA360_CONFIGS_PATH` を tmp に向けたうえで本モジュールが import できることを検証する
  - 観測可能な完了状態: smoke test が green、`make lint` / `make syntax` / `make test` がすべて green
  - _Depends: 1.2, 2.2_
  - _Requirements: 3.1, 3.4_
  - _Boundary: DriveModeConfigConsumer_

- [ ] 4.3 (P) LocalStartupValidator: main() の起動時検証 + UploadTargets 受け渡し配線
  - `apps/local_auto_converter.py:main()` の冒頭で `load_app_config()` を呼び、`AppConfig` を取得
  - 主ループ突入直前に info ログで `uploads enabled: drive=<bool>, photos=<bool>` を 1 回出力
  - `AppConfigError` (両 toggle false / 必須キー欠落 / パース失敗) を捕捉し、`log(message, mail_out=True)` で operator alert email + `SystemExit(1)` で fail-fast 終了
  - main() の polling ループから `process_pending(...)` を呼ぶ際、`upload_targets=cfg.upload` を渡すように配線する
  - 上記挙動を検証するテストを 2 件追加 (起動ログに toggle 行が 1 回出ること、`AppConfigError` 発生時に mail_out=True ログが呼ばれて SystemExit すること)
  - 観測可能な完了状態: 新テスト 2 件が green、本番起動時に `uploads enabled: drive=..., photos=...` が docker logs に出る挙動が想定どおり (手動確認チェックリストへ追加)
  - _Depends: 1.2, 2.2, 3.2_
  - _Requirements: 1.6, 3.1, 4.1, 4.3_
  - _Boundary: LocalStartupValidator_

- [ ] 5. ConfigSampleAndDocs: 運用者向け移行アーティファクトを整える
- [ ] 5.1 (P) configs.yaml.sample をリポジトリ直下に追加する
  - 全必須キー (`gdrive.drive_id`, `gdrive.working_folder_id`, `gmail.address`, `gmail.password`, `gmail.error_mail_to`, `upload.drive`, `upload.photos`) を含むサンプル YAML を提供
  - 各値はプレースホルダ ("REPLACE-WITH-..." 等) にし、`upload.drive: true`, `upload.photos: true` をデフォルト例として記載
  - ファイル末尾に「両方 false は不可」「廃止された `[YOUTUBE_SETTINGS]` は YAML へ移植不要」の注釈コメントを入れる
  - `.envrc.sample` 整合性チェック (CI) が新規ファイルに引っかからないことを確認
  - 観測可能な完了状態: `configs.yaml.sample` がリポジトリ直下に存在し、`yaml.safe_load` で構文エラーなくロードできる (既存 CI を通る)
  - _Depends: 2.2_
  - _Requirements: 3.6, 5.2_
  - _Boundary: ConfigSampleAndDocs_

- [ ] 5.2 (P) README に YAML 移行手順セクションを追加し、INI 言及を整理する
  - README に "Migrating from configs.txt to configs.yaml" セクションを新設し、INI セクション → YAML キーの対照表 (`research.md` I2 と同等) と、`[YOUTUBE_SETTINGS]` 廃棄、`upload.*` 新規キー、両 false 禁止のルールを明記する
  - `.envrc.sample` および operator-facing docs に残る `configs.txt` 言及を `configs.yaml` に書き換えるか、不要な記述は削除する
  - ハードコードパスの規約 (`/insta360-auto-converter-data/configs.yaml`) を docs 上で 1 箇所のみに集約する
  - 観測可能な完了状態: README で対照表が表形式で確認でき、`grep -RIn "configs\.txt" --exclude-dir=.git` の検索結果がマイグレーションメモ内の言及のみに収束する
  - _Depends: 2.2_
  - _Requirements: 5.1, 5.3_
  - _Boundary: ConfigSampleAndDocs_
