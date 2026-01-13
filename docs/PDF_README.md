````markdown
PDF 配信連携メモ

概要
- Tada (この FastAPI) はログイン保護された `/pdf/{pmid}` エンドポイントを提供し、実ファイル配信は CoreServer の `pdf.php` が署名付き URL で行います。
- 署名鍵 `PDF_SECRET` は Tada と CoreServer で共通の長いランダム文字列とします。Git 管理には載せないでください。

環境変数
- PDF_SECRET: 必須（例: 長いランダム文字列）
- CORESERVER_PDF_ENDPOINT: 任意（デフォルト: https://ifc66.v2003.coreserver.jp/pdf.php ）
- PDF_TTL_SEC: 署名有効秒数（デフォルト: 300）

起動例（systemd / crontab など）
```
export PDF_SECRET="長いランダム文字列"
export CORESERVER_PDF_ENDPOINT="https://ifc66.v2003.coreserver.jp/pdf.php"
export PDF_TTL_SEC=300
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

動作確認手順
1. ログインしている状態で `GET /pdf/24963835` を開くと、Tada が CoreServer の署名付き URL を生成して 302 リダイレクトします。
2. 未ログインでアクセスした場合は `/login` にリダイレクトされます。
3. `/secondary/{group}/{pmid}` の画面に「PDFを開く」ボタンが表示され、ボタン経由で別タブで CoreServer の PDF が開くことを確認してください。

注意点
- 署名付き URL をテンプレートに事前埋め込みしないでください。必ず `/pdf/{pmid}` を経由させてログイン制御を行います。
- `PDF_SECRET` は外部に漏らさないでください。
- CoreServer 側 `pdf.php` は `pmid, exp, sig` を検証してファイルを返す実装が前提です。

問い合わせ
- 実際の CoreServer の `pdf.php` の検証ロジックや鍵の更新戦略が必要なら教えてください。

````
