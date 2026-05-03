---
name: Product Steering
description: insta360-auto-converter が解決する課題、利用者像、コア機能、プロダクトとしての境界条件
type: product
inclusion: always
---

# Product Steering

## What this is

Insta360 One X 等で撮影した raw ファイル (`.insv` 動画 / `.insp` 写真) を 360° 等距円筒 (equirectangular)
形式に stitching し、メタデータを注入し、**Google Drive と Google Photos の両方** に公開する
**ヘッドレスなバックグラウンドサービス**。Docker コンテナとして 24 時間稼働させる前提で設計されている。

入力源として 2 モード:

1. **Drive モード** (`apps/insta360_auto_converter.py`): Google Drive の作業フォルダを polling
2. **ローカル入力モード** (`apps/local_auto_converter.py`): ホスト側のローカルディレクトリを polling

YouTube への公開は **2026 年に廃止**。動画も写真と同様に Google Photos のアルバムに上げる。

## Core problem

Insta360 公式の 360 Studio で raw を変換すると以下の苦痛がある:

1. **ストレージ圧迫**: 128GB の raw を mp4 にするだけでローカルに 256GB 空き容量が必要
2. **CPU 占有**: 公式ツールの stitching 中はマシンが事実上使えない
3. **アップロードの煩雑さ**: 360° 体験 (Cardboard / モバイル) のためには Google Photos / YouTube への手動アップロードが必須で UI が貧弱

このサービスはユーザーの手元のマシンを一切使わず、クラウド (or 余った Linux/Mac) に置いた Docker で全自動処理する。

## Target user

- Insta360 ユーザー本人 (single-tenant 設計、認証情報は個人のもの)
- `python3` / `docker` の基本概念がわかる人
- Google Workspace 等で Drive / Photos / YouTube に十分な容量・割り当てがある人
- 24/7 稼働できる Linux 機 (EC2, GCE, Mac mini など) を持っている人

**Why:** README が明示的に前提として宣言しているため、本ツールはエンドユーザー向け SaaS ではなく
セルフホスト型の個人用ツールとして設計されている。GUI・マルチテナント・セキュアな鍵管理は範囲外。

**How to apply:** 機能追加を検討するときは「セルフホストで一人のオーナーが運用する」前提を維持する。
複数アカウント分離、Web UI、サードパーティ向け配布などはスコープ外として扱う。

## Core capabilities

1. **取り込み (Drive モード)**: Google Drive の指定 working folder 配下のサブフォルダを polling し、raw ペアを発見
2. **取り込み (ローカル入力モード)**: ホスト側 `$INSTA360_DATA_DIR/local-input/<アルバム名>/` 配下を polling し raw を発見
3. **タスク調停 (Drive モード)**: `.auto_processing` / `.auto_done` / `.auto_broken` フラグファイルを Drive 上に置くことで
   複数コンテナの並列実行を緩く調整する (best-effort、稀に重複処理は許容)
4. **タスク調停 (ローカルモード)**: 完了後に `<元ファイル名>.done` をローカルに作成して再処理を防ぐ
5. **Stitching**: Insta360 MediaSDK (`stitcherSDKDemo`) を `subprocess` で起動し、左目 (`_00_`) / 右目 (`_10_`)
   raw を 1 本の equirectangular に統合
6. **大容量分割**: 7GB を超える動画は moviepy/ffmpeg でサイズ均等分割 (Photos の上限を意識)
7. **360° メタデータ注入**: 写真は ExifTool で XMP-GPano、動画は Google の `spatial-media` ツールで mp4 atom
8. **公開**:
   - Drive モード: 動画 / 写真ともに Google Photos アルバム (= 元フォルダ名) に投入
   - ローカル入力モード: 動画 / 写真ともに **Drive (working folder 配下のアルバム名サブフォルダ) と Google Photos アルバム の両方** に投入
9. **失敗通知**: `mail_out=True` ログは Gmail SMTP で運用者にメール

## Behavioral principles

- **冪等性 (best-effort)**: フラグファイル方式はファイルシステムロックではないため、
  「同じ raw が二度処理されないこと」を絶対保証しない。重複アップロードのコストが安いという前提で割り切っている。
- **落ちても再起動で復旧**: メインループは外側の `while True` + `try/except` で全例外を握りつぶし、
  3 秒後に次のジョブへ進む。コンテナ自体のクラッシュも `docker run` の運用で復旧する想定。
- **ローカル一時ファイルは使い捨て**: `finally` 句で raw / 中間 mp4 / フラグを必ず削除。
  作業ディレクトリは常に空に近い状態を保つ。

**Why:** 動画変換は数十分かかり、ネットワーク・SDK・API のいずれもが頻繁に過渡的失敗を起こす。
完全な exactly-once を狙うとコードが複雑化するため、「壊れたら次の周回でリトライ」を許容する設計。

**How to apply:** 例外処理の改修や状態管理の変更を提案するときは、この best-effort 前提を壊さないこと。
たとえば「処理途中でコンテナが死ぬと孤児フラグが残る」のは仕様であり、自動回収機構の追加は要件確認が必要。

## Out of scope

- HDR 写真の stabilization (MediaSDK 側未対応のため明示的に未サポート)
- 処理進捗の Web UI / ダッシュボード
- ユーザー認証、課金、マルチテナント
- YouTube への動画公開 (2026 年に廃止)
