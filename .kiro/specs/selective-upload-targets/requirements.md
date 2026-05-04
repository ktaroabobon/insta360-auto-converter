# Requirements: selective-upload-targets

## Project Description (Input)

ローカル入力モード (`apps/local_auto_converter.py`) において、ローカルディレクトリ
(`$INSTA360_DATA_DIR/local-input/<アルバム名>/`) に置かれた raw ファイルを変換した後、
Google Drive と Google Photos の **両方** に上げているのを、**それぞれの上げ先を独立に
有効/無効** にできるようにしたい。設定は YAML 形式の設定ファイルで真偽値を切り替える形式とし、
これに合わせて既存の INI 形式 (`configs.txt`) を YAML (`configs.yaml`) へ移行する。

- **誰の問題か**: insta360-auto-converter のセルフホスト運用者 (single-tenant、本人ユース)。
- **現状**:
  - ローカル入力モードでは Drive と Photos の **両方** に常時アップロードされ、片方だけ使う運用ができない。
  - 設定は INI 形式 (`configs.txt`) を `ConfigParser` で読んでおり、型情報や階層が乏しく、新しい toggle 系を表現しづらい。
- **何を変えたいか**:
  - YAML の設定キーで `upload.drive` / `upload.photos` をそれぞれ true/false で指定でき、true のものだけにアップロードするようにする。
  - 既存の INI 設定値もすべて YAML に移行する (二重管理を避けるため)。
  - 両方 false 等の不正設定は起動時に検出する (フェイルファスト)。

## Boundary

スコープが誤読されないよう、含む / 含まない / 隣接する期待を明示する。

**含む (Inclusion):**

- ローカル入力モードでの Drive / Photos アップロード先の個別 on/off
- `/insta360-auto-converter-data/configs.txt` (INI) を `configs.yaml` (YAML) へ移行
- 起動時の必須キー検証および不正組み合わせ (両方 false 等) の検出
- リポジトリ管理のサンプルファイル (`configs.yaml.sample`) 提供と運用者向け移行手順の周知

**含まない (Exclusion):**

- Drive モード (`apps/insta360_auto_converter.py`) のアップロード先 toggle
  (Drive モードは元々 Photos のみが既存仕様、変更しない)
- 認証ファイル (`auto-conversion.json` / `gphotos_auth.json`) の形式変更
  (Google API 由来の独自形式、本要件の対象外)
- リポジトリ内の `apps/in_app_configs.conf` (アプリ内デフォルト) の YAML 化
  (本要件は運用者編集の `configs.txt` のみが対象)
- 動作中の hot-reload (config 変更はコンテナ再起動で適用)
- アップロード先の追加 (3 つ目の宛先など)

**隣接する期待 (Adjacent expectations):**

- Drive モード (`insta360_auto_converter.py`) でも YAML を読むようになる
  (config 読み込みパターンは project 全体で一本化される)。
- README / `.envrc.sample` / docker 運用手順は YAML 化に追従して更新する。
- マルチプロセス運用 (best-effort 調停) の挙動は本要件で変更しない。

## Requirement 1: アップロード先選択の Config (Drive / Photos)

**User Story:** 運用者として、Photos だけにアップロードする / Drive だけにバックアップする運用ができるよう、
それぞれの上げ先を独立に on/off したい。

**Acceptance Criteria:**

1.1 The ローカル変換オーケストレータ shall read upload destination toggles `upload.drive` and `upload.photos` from `configs.yaml`.

1.2 When `upload.drive` is true, the ローカル変換オーケストレータ shall upload each converted file to the Drive working folder subfolder for the album.

1.3 When `upload.drive` is false, the ローカル変換オーケストレータ shall skip all Drive uploads for converted files in the local input pipeline.

1.4 When `upload.photos` is true, the ローカル変換オーケストレータ shall upload each converted file to the Google Photos album.

1.5 When `upload.photos` is false, the ローカル変換オーケストレータ shall skip all Google Photos uploads for converted files in the local input pipeline.

1.6 If both `upload.drive` and `upload.photos` are false, the insta360-auto-converter shall fail fast at startup with an error log naming the conflicting keys.

## Requirement 2: 部分有効構成での失敗時状態管理

**User Story:** 運用者として、片方だけ有効な構成でも従来どおり「有効な上げ先がすべて成功して初めて完了マーカーを残す」
挙動を維持してほしい。再処理回避と失敗からの復旧をこの挙動に依存しているため。

**Acceptance Criteria:**

2.1 When every enabled upload destination succeeds for a converted raw, the ローカル変換オーケストレータ shall create the `.done` marker for that raw.

2.2 If any enabled upload destination fails for a converted raw, the ローカル変換オーケストレータ shall not create the `.done` marker for that raw so that the next polling cycle retries.

2.3 While `upload.drive` is false, the ローカル変換オーケストレータ shall not initiate any Drive upload calls for converted files in the local input pipeline.

2.4 While `upload.photos` is false, the ローカル変換オーケストレータ shall not initiate any Google Photos upload calls for converted files in the local input pipeline.

## Requirement 3: 設定ファイルの YAML 化

**User Story:** 運用者として、設定ファイルが YAML になることで真偽値・文字列の型と階層が明確になり、
新規 toggle を含めた拡張がしやすくなることを期待する。

**Acceptance Criteria:**

3.1 The insta360-auto-converter shall load configuration from `/insta360-auto-converter-data/configs.yaml` at startup.

3.2 If `configs.yaml` is missing or unparseable as YAML, the insta360-auto-converter shall fail fast at startup with an error log naming the path and the parse failure reason.

3.3 If any required configuration key is missing (`gdrive.drive_id`, `gdrive.working_folder_id`, `gmail.address`, `gmail.password`, `upload.drive`, `upload.photos`), the insta360-auto-converter shall fail fast at startup with an error log naming the missing key.

3.4 The insta360-auto-converter shall preserve all configuration values currently consumed from `configs.txt` (Drive IDs, Gmail SMTP credentials) under the YAML schema so that existing operations (Drive モード polling、SMTP エラー通知) continue to function.

3.5 The insta360-auto-converter shall not silently fall back to `configs.txt` when `configs.yaml` is absent.

3.6 The repository shall provide a `configs.yaml.sample` documenting the YAML schema and listing all required keys with placeholder values.

## Requirement 4: 運用者観測性

**User Story:** 運用者として、有効になったアップロード先がログから読み取れ、設定誤りに早く気づけるようにしたい。

**Acceptance Criteria:**

4.1 When the ローカル変換オーケストレータ enters its main loop, the ローカル変換オーケストレータ shall emit an info-level log line stating the resolved upload destinations (e.g., `uploads enabled: drive=true, photos=false`).

4.2 When the ローカル変換オーケストレータ skips an upload destination because the corresponding toggle is false, the ローカル変換オーケストレータ shall not emit an error-level log and shall not trigger an operator alert email for that skip.

4.3 If a required configuration key is missing or invalid at startup, the insta360-auto-converter shall emit an operator alert email consistent with existing fatal-error notification behavior.

## Requirement 5: 移行手順

**User Story:** 運用者として、INI から YAML への切替が破壊的変更であることを把握し、
アップグレード時に必要な手順を README から追えるようにしたい。

**Acceptance Criteria:**

5.1 The repository shall include a migration note in `README.md` (or a clearly linked document) describing how to convert an existing `configs.txt` to `configs.yaml` and which INI sections map to which YAML keys.

5.2 The repository shall include `configs.yaml.sample` checked into the repository with all required keys present and example placeholder values.

5.3 The repository shall remove `configs.txt` from sample/onboarding files (`.envrc.sample` 等) and operator-facing docs once YAML is the only supported format.
