# 二次スクリーニング再閲覧・再編集機能 - クイックリファレンス

## 🎯 実装概要（30秒版）

**問題**: 二次スクリーニング完了後、同じ論文が見られなくなる
**解決**: `completed_at` フィールドを追加して、完了状態を"ステータス"として扱う
**結果**: 完了後も常に再閲覧・再編集可能

---

## ⚡ 実装完了チェック

```bash
# 1. Migration 実行確認
sqlite3 apathy_screening.db ".schema secondaryreview" | grep completed_at

# 2. DB 確認
sqlite3 apathy_screening.db "SELECT COUNT(*) FROM secondaryreview WHERE completed_at IS NOT NULL;"

# 3. サーバー起動
cd /Users/kuniyuki/apathy_screen_app
/Users/kuniyuki/apathy_screen_app/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4. ダッシュボード確認
# ブラウザ: http://127.0.0.1:8000/secondary
```

---

## 📱 ユーザー流れ

### 未完了項目を完了させる

1. `/secondary` → ダッシュボード表示
2. グループカード → 「候補一覧を表示」クリック
3. 未処理候補（🟡バッジ）をクリック
4. `/secondary/{group}/{pmid}` → 詳細ページ
5. 内容確認 → 「完了として保存」ボタンクリック
6. ページ留まる + 警告メッセージ表示
7. ダッシュボール戻る → 該当項目に「✓ 完了済み」バッジ

### 完了済み項目を再編集する

1. `/secondary` → ダッシュボール表示
2. 完了済み候補（✓ 完了済みバッジ）をクリック
3. `/secondary/{group}/{pmid}` → 詳細ページ
4. 警告メッセージ表示（ℹ️ 完了済みレビュー）
5. 内容修正
6. 「保存して次へ」 → 内容更新 + 次へ進行
7. `completed_at` は変わらない（完了時刻を保持）

---

## 🔧 コード変更サマリ

### Model (`app/models.py` Line 183)
```python
completed_at: Optional[str] = None
```

### Backend - 一覧 (`app/main.py` Line 1827)
```python
completed = session.exec(
    select(func.count(SecondaryReview.id)).where(
        (SecondaryReview.group == g) & 
        (SecondaryReview.reviewer_id == user.id) & 
        (SecondaryReview.completed_at != None)
    )
).one()
```

### Backend - 保存 (`app/main.py` Line 1983)
```python
if action == 'complete':
    review.completed_at = datetime.utcnow().isoformat()
```

### Frontend - ダッシュボール (`templates/secondary_index.html` Line 54-89)
```html
{% for cand in candidates_by_group[g] %}
  <a href="/secondary/{{ g }}/{{ cand.pmid }}">PMID: {{ cand.pmid }}</a>
  {% if cand.is_completed %}
    ✓ 完了済み
  {% endif %}
{% endfor %}
```

### Frontend - 詳細 (`templates/secondary_review.html` Line 145-218)
```html
<!-- 完了バッジ -->
{% if review.completed_at %}
  <span class="badge bg-info ms-2">完了済み</span>
{% endif %}

<!-- 警告メッセージ -->
{% if review.completed_at %}
  <div class="alert alert-info mb-3">
    このレビューは {{ review.completed_at }} に完了されています。
  </div>
{% endif %}

<!-- 条件付きボタン -->
{% if not review.completed_at %}
  <button name="action" value="complete">完了として保存</button>
{% else %}
  <span class="badge bg-info">✓ 完了済み</span>
{% endif %}
```

---

## 🧪 テストチェックリスト

- [ ] `/secondary` で候補一覧が表示されるか
- [ ] 未完了項目が 🟡 バッジで表示されるか
- [ ] 完了済み項目があれば ✓ バッジで表示されるか
- [ ] 候補をクリックで `/secondary/{group}/{pmid}` に遷移するか
- [ ] 未完了: 「完了として保存」ボタン表示
- [ ] 「完了として保存」クリック → ページ留まる
- [ ] ページ留まった後、警告メッセージ表示
- [ ] ページ留まった後、「完了として保存」ボタン消える
- [ ] ダッシュボール戻る → 該当項目に ✓ バッジ
- [ ] 完了済み項目をクリック → 詳細ページ表示（404 エラーなし）
- [ ] 完了済み項目の詳細ページで内容修正可能か
- [ ] 修正後「保存して次へ」で内容更新されるか
- [ ] `updated_at` は更新されて `completed_at` は変わらないか

---

## ⚙️ システム仕様

| 項目 | 説明 |
|-----|------|
| **完了状態** | `completed_at IS NOT NULL` |
| **完了フロー** | action='complete' → completed_at = ISO8601 timestamp |
| **ナビゲーション** | action='complete' → 同ページリダイレクト (303) |
| **再編集** | 「保存して次へ」で `decision`, `final_*` フィールド更新可能 |
| **completed_at** | 再編集時も変わらない（完了時刻を保持） |
| **updated_at** | 常に最新時刻に更新 |
| **/next フィルタ** | `decision == 'pending'` のみ（completed_at 無視） |
| **ダッシュボール統計** | `completed_at != NULL` でカウント |

---

## 🚀 デプロイ手順

### ステップ 1: Migration 実行
```bash
cd /Users/kuniyuki/apathy_screen_app
python -m app.scripts.migrate_add_completed_at_secondary
```

**確認**:
```
✓ Column 'completed_at' added successfully to SecondaryReview table
✓ Verification: Column 'completed_at' is now in schema
```

### ステップ 2: コード デプロイ
```bash
# 既存コードをデプロイ（全ファイルを上書き）
```

### ステップ 3: サーバー再起動
```bash
# FastAPI/Uvicorn の再起動
```

### ステップ 4: テスト
- `/secondary` で一覧表示確認
- 候補クリック → 詳細ページ表示確認
- 「完了として保存」テスト

---

## 🐛 トラブルシューティング

### Q: 完了ボタンが見えない
**A**: ブラウザキャッシュクリア（Ctrl+Shift+Delete）

### Q: completed_at 列がない
**A**: Migration 実行確認
```bash
python -m app.scripts.migrate_add_completed_at_secondary
```

### Q: 404 エラーが出る
**A**: 詳細ページの取得ロジックを確認（completed_at で除外していないか）

### Q: 完了後の画面がおかしい
**A**: テンプレートの `review.completed_at` が正しく render されているか確認

---

## 📊 DB クエリ例

### 完了済み件数を確認
```sql
SELECT group, COUNT(*) as completed_count 
FROM secondaryreview 
WHERE completed_at IS NOT NULL 
GROUP BY group;
```

### 特定 PMID の完了状態確認
```sql
SELECT pmid, group, decision, completed_at, updated_at 
FROM secondaryreview 
WHERE pmid = 12345;
```

### 完了後に再編集された項目確認
```sql
SELECT pmid, completed_at, updated_at 
FROM secondaryreview 
WHERE completed_at IS NOT NULL 
  AND updated_at > completed_at 
ORDER BY updated_at DESC;
```

---

## 📚 ファイル参照

| ファイル | 用途 |
|---------|------|
| [IMPLEMENTATION_VERIFICATION.md](IMPLEMENTATION_VERIFICATION.md) | 詳細な検証チェックリスト |
| [COMPLETION_SUMMARY.md](COMPLETION_SUMMARY.md) | 実装完了サマリ |
| [app/models.py](app/models.py#L183) | Model 定義 |
| [app/scripts/migrate_add_completed_at_secondary.py](app/scripts/migrate_add_completed_at_secondary.py) | Migration スクリプト |
| [app/main.py](app/main.py) | Backend ロジック |
| [templates/secondary_index.html](templates/secondary_index.html) | ダッシュボール UI |
| [templates/secondary_review.html](templates/secondary_review.html) | 詳細ページ UI |

---

**Status**: ✅ PRODUCTION READY  
**Last Updated**: 2025-01-12
