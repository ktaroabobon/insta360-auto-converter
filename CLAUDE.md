# insta360-auto-converter — Claude Code project instructions

このリポジトリで Claude Code を使うときの project-local 指示書。
**ユーザーの home (~/CLAUDE.md / ~/.claude/CLAUDE.md) の指示を上書きしない**、補完する位置付け。

## まず読むファイル

- **`.kiro/steering/`** (常時インクルージョン) — プロジェクト全体のステアリング
  - `product.md` / `tech.md` / `structure.md` / `testing.md`
- **`.claude/rules/`** (タスクに応じて参照) — 単一責任ごとのルール SoT
  - `architecture.md` — モジュール構成 / 責務分割 / pure-impure 分離
  - `coding-style.md` — Python スタイル / ruff / 命名規約 / ロギング / エラー処理
  - `dev-environment.md` — mise / uv / Docker / Makefile
  - `security.md` — 認証情報 / NDA バイナリ / .gitignore
  - `simplicity.md` — YAGNI / KISS / 過剰抽象化の禁止
  - `tdd.md` — TDD サイクル
  - `unit-test.md` — テスト基準 / モックポリシー / カバレッジ方針

## 実装方針

### TDD を必ず守る

**今後の実装はすべて TDD で進める** (`.claude/rules/tdd.md` 参照)。

- 機能追加 / バグ修正 / リファクタを問わず、まず失敗するテストを書く
- テスト無しで本実装をコミットしない
- 例外は `tdd.md` に列挙された緩和ケースのみ

### モジュール分割

- 1 ファイル = 1 外部サービス、または 1 ドメイン (`.claude/rules/architecture.md`)
- pure (コマンド組み立て) と impure (subprocess / API 呼び出し) を分離する
  - 例: `apps/stitcher.py` (pure) vs `apps/local_auto_converter.py` の SDK ランナー (impure)

### コーディングスタイル

- ruff 準拠 (`.claude/rules/coding-style.md`)
- ロギングは `from utils import log` を経由する (直接 `print` / `logging.getLogger` を使わない)
- エラーハンドリングはメインループで「ステップごとに try/except」パターンを踏襲する

### セキュリティ

- 認証情報・トークン・`MediaSDK/` を **絶対にコミットしない** (`.claude/rules/security.md`)
- ハードコードされたパスは「コンテナ運用前提」の意図的な設計、設定可能化しない

## 編集ルール

- ファイルを編集する前に、必ず Read で対象ファイルを読むこと
- 関連ファイル (テスト / 呼び出し元 / steering) も確認してから編集する
- Write (全ファイル書き換え) ではなく Edit (差分編集) を優先する
- 推測で編集せず、必ずコードを読んで理解してから変更する

## PR / コミット運用

- ブランチ命名:
  - `chore/<topic>` — CI / 設定整備
  - `feat/<topic>` — 機能追加
  - `fix/<topic>` — バグ修正
- PR タイトル / 本文は **日本語**
- PR に Test plan セクションを必ず含める (チェックボックス形式)
- `make lint` / `make syntax` / `make test` の 3 つが green になってからコミット

## CI

- GitHub Actions (`.github/workflows/ci.yml`) で以下を自動実行:
  - `uv lock --check` → `uv sync --frozen --group dev`
  - `ruff check apps scripts tests`
  - `python -m compileall -q apps`
  - `pytest`
  - shellcheck (severity: warning)
  - `.envrc.sample` 整合性チェック
- **CI が赤の PR はマージしない**

## 詳細リファレンス

- ステアリング: `.kiro/steering/`
- ルール: `.claude/rules/`
- 開発ワークフロー: `~/CLAUDE.md` (Kiro 仕様駆動開発)
- README: ユーザー向けセットアップ手順
