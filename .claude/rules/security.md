# セキュリティガイドライン

このファイルがセキュリティルールの Single Source of Truth。

## コミット前チェックリスト

- [ ] ハードコードされた認証情報 / API キー / パスワードがないこと
- [ ] `MediaSDK/` 配下のファイルが含まれていないこと (NDA 違反になる)
- [ ] `insta360-auto-converter-data/` 配下のファイルが含まれていないこと
- [ ] `.envrc` (個人環境設定) が含まれていないこと
- [ ] 個人撮影の動画 / 写真 / ログが含まれていないこと

`git status` / `git diff --stat` で **必ず目視確認** してから commit する。

## シークレット管理

- **環境変数は `.envrc` で管理**。コードにハードコード禁止
- **認証情報ファイルは `/insta360-auto-converter-data/` 配下にのみ置く**:
  - `auto-conversion.json` — Drive サービスアカウント鍵
  - `gphotos_auth.json` — Photos OAuth トークン
  - `configs.txt` — Drive ID, Gmail パスワード等
- これらは `.gitignore` で `insta360-auto-converter-data/` ごと除外済み

## NDA 配布バイナリ

- **`MediaSDK/`** は Insta360 から **NDA を経て個別申請** するもの。リポジトリに含めない
- `.gitignore` / `.dockerignore` で除外済み。**`git add MediaSDK` を絶対にしない**
- ビルド時にローカルの `MediaSDK/` がコンテナへ COPY される (Dockerfile)

## Vendored ツール

- `Image-ExifTool-12.10/` — Perl 製、写真メタデータ注入。ライセンスは ExifTool 同梱の README 参照
- `spatial-media/` — Google 製、動画メタデータ注入

これらは pip で入らないか特定バージョンに固定したいので vendored。
**勝手にバージョン変更しない**。Dockerfile のパス参照とコード中のハードコードパスを併せて更新する必要がある。

## ハードコードパス (意図的)

- `/insta360-auto-converter/` — リポジトリの COPY 先
- `/insta360-auto-converter-data/` — マウントされる運用データ

これらは「コンテナ運用前提」を明示するための意図的なハードコード。
**「設定可能化」しようとしない**。

例外: `INSTA360_LOCAL_INPUT_ROOT` (ローカル入力モードの監視ディレクトリ) と
`INSTA360_LOGS_DIR` (ログ出力先) のみ env で上書き可能 (テスト用 + 運用柔軟性)。

## マルチプロセス時の競合

- 同じ Google アカウントで複数コンテナを別マシンに立てるのは想定済み
- Drive 上の `.auto_processing` フラグでコーディネーション (best-effort、稀な重複処理は許容)
- **厳密なロックを Drive 上で実装する提案は不要** (要件確認が必要なスコープ拡張)

## 運用時の通知

- `log(msg, mail_out=True)` で Gmail SMTP からアラートメールが飛ぶ
- `configs.txt` の `[GMAIL_INFO]` が認証情報。**SMTP パスワードを Slack や PR に貼らない**

## クロステナント / 個人情報

- 本ツールは **single-tenant 設計** (個人ユース想定)
- ユーザー認証 / マルチテナント / Web UI はスコープ外
- 「他人のアカウントでも使えるように」する変更は要件確認が必須
