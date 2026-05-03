---
name: Testing & TDD Steering
description: 本リポジトリの実装は TDD で進める。Red → Green → Refactor の順序、テスト配置と実行、CI でのゲートを定義する。
type: testing
inclusion: always
---

# Testing & TDD Steering

## 大原則

**今後の実装はすべて TDD (Test-Driven Development) で進める。**

- 機能追加 / バグ修正 / リファクタを問わず、**まず失敗するテストを書く** (Red)
- 次に **テストを通す最小実装** を入れる (Green)
- 最後に **実装とテストの両方を整える** (Refactor)
- テスト無しで本実装をコミットしない

**Why:** 既存コードはテストが無い状態で長く運用されており、副作用や暗黙の仕様が多い。
今後の変更は「期待される挙動」を実行可能なテストとして残し、リグレッションを CI でブロックする方針に転換する。

**How to apply:** 仕様の確定 → テスト記述 → 実装 → テスト通過確認 の順をどんな小さな変更でも踏む。
「まず動くものを書いてからテストを足す」順序は本リポジトリでは採用しない。

## TDD のサイクル

1. **Red — 失敗するテストを書く**
   - 仕様を表現する最小のテストを 1 つ書き、`uv run pytest` で **必ず失敗** することを確認する
   - 失敗の理由が「未実装」または「期待した分岐に入らない」であることをログで確認する
2. **Green — 最小実装で通す**
   - テストを通すためだけのコードを書く。過剰な汎化や設計の作り込みはしない
   - `uv run pytest` でそのテストが通ることを確認する
3. **Refactor — 設計を整える**
   - テストが緑のまま、命名・重複・構造を整える
   - リファクタの途中で赤になったら、リファクタを巻き戻すのではなく **小さく分割して再度赤→緑** を踏む

## ディレクトリ構成

- テストはリポジトリ直下の `tests/` に配置する
- ファイル名は `test_<対象モジュール>.py`、関数名は `test_<挙動>` 形式
- 例: `apps/local_auto_converter.py` のテストは `tests/test_local_auto_converter.py`

```
insta360-auto-converter/
├── apps/
└── tests/                          # TDD で増やしていくテスト
    ├── conftest.py                 # 共有 fixture (tmpdir、ダミー設定など)
    └── test_<module>.py
```

**Why:** Python の慣例に従い、`apps/` は production コード専用にする。
テストを `apps/` 内に混ぜると、Docker イメージのビルド時にテストコードが container に入ってしまう。

**How to apply:** Dockerfile の `COPY . .` から `tests/` を除外する設定 (`.dockerignore` 反映)
を追加するか、`COPY apps/ ./apps` のようにスコープを絞る。

## テストフレームワーク

- **pytest** を採用する (標準 unittest より fixture / parametrize が明示的)
- `dependency-groups.dev` に `pytest` を追加し、`uv run pytest` で起動できる状態を保つ

### モックポリシー

- **外部サービス境界 (Google API, ファイル I/O, subprocess) は基本的にモックする**
  - Google API クライアントは `unittest.mock.MagicMock` で差し替える
  - `subprocess.Popen` / `subprocess.call` も同様にモックする
- **ファイル I/O は `tmp_path` fixture を使う** (実ディスクに書く)
  - モック多用で「実装と乖離したテスト」になるくらいなら、tmpdir で実 I/O を回す
- **Insta360 MediaSDK バイナリは絶対に呼ばない** (NDA 配布、CI に置けない、決定論性ゼロ)
  - SDK 呼び出し関数は thin wrapper にして、wrapper 自体をモックする方針

**Why:** 本プロジェクトは外部依存 (Google API, SDK バイナリ, ffmpeg) が多く、
ユニットテストでこれらを実呼び出しすると CI が安定せず、料金・トークン消費も発生する。

**How to apply:** 新規モジュールでは「外部呼び出しを 1 箇所に集約」した上で、
それをモック差し替えできるようにする。`MagicMock` のみで構築されたテストは
回帰防止になりにくいため、できるだけ実型に近い fake / fixture を選ぶ。

## CI とのゲート

- `tests/` が存在する状態では、CI の Python ジョブで `uv run pytest -q` を必ず実行する
- テストが赤の PR は `main` にマージしない (GitHub の必須チェック化を後追いで設定)
- テスト未追加で「リファクタのみ」と称する PR は原則レビューで差し戻す

## カバレッジ方針

- 行カバレッジの目標値は当面設定しない (テスト数が少ないうちは指標化が無意味)
- ただし **新規追加・変更したコードパスは必ずテストで通す** ことを PR レビューで確認する
- 既存コードは TDD レガシー扱い: 触る箇所だけテストを足し、既存全体の網羅は段階的に進める

**Why:** 一律カバレッジ目標は、ノイズの多いカバー率テストを増やす副作用がある。
「変更箇所は必ずテストで触る」という最小ルールが、回帰防止に最も効く。

**How to apply:** Pull Request の Test plan 欄に、追加 / 変更したコードを cover するテスト名を箇条書きで記す。

## 例外的に TDD を緩める場合

以下に限り、テストファーストの厳格適用を緩める:

1. **typo 修正・コメント変更・lint 自動修正など、挙動に影響しない変更**
2. **設定ファイルのみの変更** (`pyproject.toml` の dev deps 追加など)
3. **third-party バイナリ更新** (MediaSDK, ExifTool など vendored ツールのバージョン上げ)

それ以外 (ロジック変更、I/O 変更、エラーハンドリング変更) は **必ず** TDD を踏む。

**Why:** TDD は手段であって目的ではない。挙動を変えない変更にテストを義務付けると形骸化する。
ただし「これは挙動を変えない」と判断しているのは人間なので、迷ったらテストを書く側に倒す。
