# beautiful_hokkaido

Instagram 北海道特化型キュレーションアカウントを **完全無料（0円）** で自動運用する Python プロジェクトです。

- データ台帳: **Google スプレッドシート**
- 審美性/被写体判定・バイリンガルキャプション生成: **Gemini 2.5 Flash（無料枠）**
- 動画/静止画の正規化: **FFmpeg + Pillow**
- アセットホスティング: **Cloudinary 無料枠**
- 投稿: **Instagram Graph API（Content Publishing）**
- 定期実行: **GitHub Actions（無料枠）**

---

## 1. ディレクトリ構成

```
beautiful_hokkaido/
├── .env.example
├── requirements.txt
├── config.py
├── modules/
│   ├── __init__.py
│   ├── sheet_manager.py       # Google スプレッドシート
│   ├── evaluator.py           # Gemini 2.5 Flash
│   ├── asset_processor.py     # FFmpeg/Pillow + Cloudinary
│   └── ig_publisher.py        # Instagram Graph API
├── main.py                    # CLI オーケストレーター
├── .github/workflows/
│   └── auto_post.yml          # GitHub Actions (JST 8:00 / 18:00)
├── setup_venv.bat             # Windows 初期セットアップ
├── run_evaluate.bat           # 判定モード手動実行
├── run_publish.bat            # 投稿モード手動実行
└── README.md
```

---

## 2. セットアップ手順

### 2-1. 仮想環境と依存ライブラリ

> **重要**: `google-genai` は Python 3.9+ 必須。システムに複数バージョンが入っている場合は必ず **`py -3.11`**（または `py -3.10`/`py -3.12`）を明示してください。素の `python` だと古い 3.8 系が選ばれて `No matching distribution found for google-genai` エラーになります。

**Windows (PowerShell):**
```powershell
cd C:\Users\ADMIN\claude-projects\beautiful_hokkaido
py -3.11 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Windows (BAT ダブルクリック):**
`setup_venv.bat` をダブルクリックすると自動で venv 作成〜依存インストールまで完了します。

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2-2. FFmpeg のインストール

- **Windows**: https://www.gyan.dev/ffmpeg/builds/ から `ffmpeg-release-essentials.zip` を落とし、`bin/` を PATH に通す
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

`ffmpeg -version` でバージョンが出れば OK。

### 2-3. `.env` の作成

```bash
cp .env.example .env
```
エディタで `.env` を開き、下の各 API キーを埋めます。

---

## 3. 各種 API キー取得手順

### 3-1. Google スプレッドシート

1. [Google Cloud Console](https://console.cloud.google.com/) で新規プロジェクト作成
2. **「APIとサービス → ライブラリ」** で下の2つを有効化
   - Google Sheets API
   - Google Drive API
3. **「APIとサービス → 認証情報 → 認証情報を作成 → サービスアカウント」** を作成
4. 作成したサービスアカウントを開き、**「キー → 鍵を追加 → JSON」** でキーを発行
5. ダウンロードした JSON を `service_account.json` としてプロジェクト直下に置く
6. スプレッドシートを新規作成し、サービスアカウントの `client_email`（JSON の中にある `***@***.iam.gserviceaccount.com`）を **編集者として共有**
7. シートの URL `https://docs.google.com/spreadsheets/d/【ここ】/edit` の **【ここ】** を `.env` の `SPREADSHEET_ID` に設定
8. 1 枚目のシート名を `posts` にする（または `.env` の `WORKSHEET_NAME` を変える）
9. 1 行目にヘッダーを自動書き込み: `python main.py --mode init_sheet`

**カラム（9 列）:**
| ID | Original_URL | Author_Handle | Status | Location | Generated_Caption | Public_Media_URL | IG_Post_ID | Scheduled_Time |
|---|---|---|---|---|---|---|---|---|

- `Status`: `Pending` / `Approved` / `Posted` / `Rejected` / `Error`
- `Scheduled_Time`: `2026-11-01T18:00:00` のような ISO 8601（タイムゾーン省略時は JST）

### 3-2. Gemini 2.5 Flash

1. https://aistudio.google.com/app/apikey にアクセス
2. **「Create API key」** → 既存の GCP プロジェクトに紐付け
3. 発行された `AIzaSy...` または `AQ.Ab8...` 形式のキーを `.env` の `GEMINI_API_KEY` に設定
4. 無料枠: 1 分あたり 15 リクエスト、1 日 1,500 リクエスト（2026 年現在）

### 3-2b. Groq（Gemini 503 時のフォールバック・必須）

Gemini 無料枠は過負荷でよく 503 を返すので、Groq を自動フォールバックに使います。

1. https://console.groq.com/keys にアクセス（Google ログイン可）
2. **「Create API Key」** → 名前は `beautiful_hokkaido`
3. 発行された `gsk_...` キーを `.env` の `GROQ_API_KEY` に設定
4. 無料枠: Llama 4 Scout Vision が 1日 14,400 リクエスト無料（2026 年現在）

### 3-3. Cloudinary

1. https://cloudinary.com/users/register_free で無料アカウント作成
2. Dashboard 上部の
   - `Cloud name` → `CLOUDINARY_CLOUD_NAME`
   - `API Key` → `CLOUDINARY_API_KEY`
   - `API Secret` → `CLOUDINARY_API_SECRET`
3. 無料枠: 25GB ストレージ / 25GB 月間帯域

### 3-4. Unsplash API（全自動ソースモード用）

1. https://unsplash.com/developers にアクセス → ログイン
2. **「Register as a developer」** → アプリケーション作成
3. アプリ名: `beautiful_hokkaido_bot`、用途説明は `AI-curated Hokkaido landscape reposting with Unsplash credit` 等
4. 作成後の画面に表示される **Access Key**（`Secret Key` ではない方）をコピー
5. `.env` に:
   ```
   UNSPLASH_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
6. 無料枠: **50 req/hour**（デモアプリ）。日次実行なら十分

**本番プロダクション申請（オプション）:** 50/hour では足りない場合、Unsplash に申請して承認されると **5,000 req/hour** まで拡張可能。初期は不要。

### 3-5. Instagram Graph API

**前提:** 投稿する Instagram アカウントは **プロアカウント（ビジネス/クリエイター）** かつ **Facebook ページに紐付け済み** であること。

1. https://developers.facebook.com/ → **Meta for Developers** にログイン
2. **「マイアプリ → アプリを作成」** → タイプ: **「Business」**
3. 製品に **「Instagram Graph API」** を追加
4. **Graph API エクスプローラ** で以下の権限を持つトークンを発行:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
   - `business_management`
5. 短期トークンを **長期トークン（60 日）** に変換:
   ```
   GET https://graph.facebook.com/v21.0/oauth/access_token
     ?grant_type=fb_exchange_token
     &client_id={APP_ID}
     &client_secret={APP_SECRET}
     &fb_exchange_token={SHORT_LIVED_TOKEN}
   ```
   → `META_ACCESS_TOKEN` に設定
6. Instagram Business Account ID を取得:
   ```
   GET https://graph.facebook.com/v21.0/me/accounts?access_token={TOKEN}
   → page_id を取る
   GET https://graph.facebook.com/v21.0/{page_id}?fields=instagram_business_account&access_token={TOKEN}
   → instagram_business_account.id が IG_USER_ID
   ```
   → `IG_USER_ID` に設定

---

## 4. 使い方

### 4-1. スプレッドシートに候補を追加

| ID | Original_URL | Author_Handle | Status | ... | Scheduled_Time |
|---|---|---|---|---|---|
| 001 | https://example.com/biei_winter.jpg | some_photographer | Pending | | 2026-11-01T08:00:00 |

- `Original_URL`: 画像/動画の直リンク（Cloudinary / Imgur / 自前ストレージなど）
- `Author_Handle`: クレジットに使う Instagram ハンドル（`@` 不要）
- `Status`: 新規行は `Pending` を手入力
- `Scheduled_Time`: 公開希望時刻（JST）。空欄なら即時対象

### 4-2. 全自動ソースモード（Unsplash候補を自動発見→AI選別→Approved投入）

```bash
python main.py --mode auto_source
```
- Unsplash API を `UNSPLASH_QUERIES` の各ワードで叩く
- 既存シートに無い新規写真だけを Gemini に投げる
- `AUTO_APPROVE` 判定だけをシートに `Approved` として追加（最大 `AUTO_SOURCE_MAX_APPROVE` 件）
- キャプションに自動で `📷 Photo by {name} (@{handle}) on Unsplash` のクレジットが入る
- `--mode publish` が cron で順次1枚ずつ消化する

Windows: `run_auto_source.bat` をダブルクリック

### 4-3. 判定モード（手動URL投入時）

```bash
python main.py --mode evaluate
```
- `Status = Pending` の全行を Gemini に投げる
- 両スコア 8 以上 & 品質 Pass → `Approved` に自動昇格
- 中間 → `Pending` のまま（人間レビュー対象）
- 低品質/自撮り等 → `Rejected`
- `Generated_Caption`・`Location` が同時に埋まる

### 4-4. 投稿モード

```bash
python main.py --mode publish
```
- 1 件だけ `Approved` かつ時間到来の行を処理
- アセットを 4:5 or 9:16 に整形 → Cloudinary アップ → IG コンテナ作成 → Polling → 公開
- 成功: `Status = Posted`、`IG_Post_ID` を書き戻し
- 失敗: `Status = Error`、キャプション末尾にスタックトレース要約を追記

Windows の場合は `run_evaluate.bat` / `run_publish.bat` をダブルクリック。

---

## 5. GitHub Actions 自動運用

### 5-1. リポジトリ化

```bash
git init
git add .
git commit -m "init beautiful_hokkaido"
gh repo create beautiful_hokkaido --private --source=. --push
```

### 5-2. Secrets 設定

`Settings → Secrets and variables → Actions → New repository secret` で以下を登録:

| 名前 | 値 |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | `service_account.json` の **ファイル全体** を貼り付け |
| `SPREADSHEET_ID` | シート ID |
| `WORKSHEET_NAME` | `posts` |
| `GEMINI_API_KEY` | Gemini キー |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary |
| `CLOUDINARY_API_KEY` | Cloudinary |
| `CLOUDINARY_API_SECRET` | Cloudinary |
| `IG_USER_ID` | IG Business Account ID |
| `META_ACCESS_TOKEN` | 長期アクセストークン |
| `DEFAULT_HASHTAGS` | 任意（空なら config のデフォ） |

### 5-3. スケジュール

`.github/workflows/auto_post.yml` に 3 本の cron を設定済み:

| JST | UTC | モード | 役割 |
|---|---|---|---|
| 07:30 | 22:30（前日） | `auto_source` | Unsplash から候補を発見→AI選別→Approved投入 |
| 08:00 | 23:00（前日） | `publish` | Approved 1件を朝投稿 |
| 18:00 | 09:00 | `publish` | Approved 1件を夜投稿 |

手動実行は `Actions タブ → auto_post → Run workflow` で `mode` を切り替え可。

### 5-4. 必要な Secrets（Unsplash追加）

既存の11個に加えて:
- `UNSPLASH_ACCESS_KEY`
- `UNSPLASH_QUERIES`（任意、デフォルトでも動作）
- `UNSPLASH_PER_QUERY`（任意、デフォ5）
- `AUTO_SOURCE_MAX_APPROVE`（任意、デフォ5）

### 5-5. アクセストークンのリフレッシュ

Meta の長期トークンは **60 日で失効** します。失効前に下の URL をブラウザで叩いて新しいトークンを取得し、`META_ACCESS_TOKEN` Secret を更新してください。
```
https://graph.facebook.com/v21.0/oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id={APP_ID}
  &client_secret={APP_SECRET}
  &fb_exchange_token={現トークン}
```

---

## 6. トラブルシュート

| 症状 | 原因 | 対処 |
|---|---|---|
| `Container ERROR` | 動画の長さ / 解像度 / コーデック不足 | `asset_processor._fit_video_9x16` の `vf` を調整 |
| `OAuthException: Session has expired` | 長期トークン失効（60 日） | 5-4 参照 |
| Gemini が JSON を返さない | モデル返答のゆらぎ | `evaluator._extract_json` が自動で `{...}` 抜き出し。失敗時は `Error` ステータスでシートに記録 |
| `permission denied` for Sheets | サービスアカウントが共有されていない | シートを `***@***.iam.gserviceaccount.com` に **編集者** として共有 |
| ffmpeg 404 | PATH 未設定 | `ffmpeg -version` を確認 |

---

## 7. ライセンス / クレジット

- 画像/動画の **著作権は原作者** にあります。必ず作者から再掲載許諾を取り、`Author_Handle` 列を埋めてキャプションにクレジットを明示してください。
- 本プロジェクトは MIT 相当で自由に改変可。
