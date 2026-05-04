# アーキテクチャルール

このファイルが本リポジトリのモジュール構成ルールの Single Source of Truth。
詳しい背景は `.kiro/steering/structure.md` も参照。

## 全体像

本プロジェクトは Clean Architecture のような厳密な層分けを採用していない。
代わりに以下のシンプルな分割を守る:

```
apps/
├── <entry>.py            # エントリポイント (insta360_auto_converter.py / local_auto_converter.py)
├── <service>_service.py  # 1 ファイル = 1 外部サービスのクラス (GDriveService 等)
├── <pure>.py             # pure な関数群 (local_input.py / stitcher.py 等)
└── utils.py              # 共通ロガー / SMTP メール / 安全な削除
```

## モジュール分割の原則

1. **1 ファイル = 1 外部サービス、または 1 ドメイン**

   `gdrive_service.py` は Drive クライアントのみ、`google_photos_uploader.py` は Photos のみ、
   `video_processor.py` は moviepy ベースの分割のみ。**責務が混ざる変更は分割を先に検討する**。

2. **pure / impure を分離する**

   SDK 起動 / 外部 API 呼び出し / subprocess を伴うコードは、
   **コマンド組み立て (pure)** と **副作用 (impure)** を分離して書く。
   `apps/stitcher.py` がその例 (コマンド配列を組み立てるだけ、subprocess は呼ばない)。

   こうすることで pure 部分は CI でテスト可能、impure 部分は最小限に保てる。

3. **エントリポイントは `while True` の long-running ループ**

   メインループは外側の `while True` + try/except で全例外を握りつぶし、
   3 秒後に次のジョブへ進む。コンテナクラッシュは `docker run` の運用で復旧する想定。
   この best-effort 前提を壊さない。

4. **新規サービス追加時は class ベース**

   外部サービスごとにクラスを 1 つ持ち (`GDriveService` 等)、内部状態は
   インスタンス変数として保持。`google_photos_uploader.py` だけは
   モジュール関数になっているが歴史的経緯で、**新規はクラスベース**。

## ハードコードされた絶対パス (意図的)

以下のパスはコード中にハードコードされている。コンテナ運用前提の意図的な設計:

- `/insta360-auto-converter/` — リポジトリの COPY 先
- `/insta360-auto-converter/apps` — WORKDIR、stitching 中間ファイルの作業場
- `/insta360-auto-converter/MediaSDK` — SDK バイナリ
- `/insta360-auto-converter-data/` — マウントされる運用データ

**これらを「設定可能」にしようとしない。** コンテナ前提を崩すと運用手順全体が壊れる。
ローカルテストの仕組みを入れたい場合は Docker から直接起動する形で再現する。

## 入力モード

入力源は 2 系統。両方 `apps/` 配下の独立したエントリポイントとして存在:

| モード | エントリ | 入力源 | 出力先 |
|---|---|---|---|
| Drive モード | `insta360_auto_converter.py` | Google Drive 作業フォルダ (polling) | Google Photos アルバム |
| ローカル入力モード | `local_auto_converter.py` | `$INSTA360_DATA_DIR/local-input/<アルバム>/` (polling) | Drive サブフォルダ + Photos アルバム |

**新しい入力モードを追加する場合**: 既存の 2 つに倣って `apps/<mode>_auto_converter.py` を新設し、
`Makefile` に `docker/run/<mode>` を追加する。`if mode == 'X'` で main を分岐する設計は採用しない。

## チェックリスト

新しいファイル / モジュールを追加する前に:

- [ ] 1 ファイル = 1 責務になっているか?
- [ ] pure / impure を分離しているか? (テスト容易性のため)
- [ ] 外部サービス追加ならクラスベースか?
- [ ] ハードコードパスを「設定可能化」しようとしていないか?
- [ ] エントリポイント追加なら `Makefile` の docker target も追加するか?
