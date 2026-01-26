# Secondary Candidates Audit & Reconciliation Scripts

## 📌 Overview

これらのスクリプトは、二次スクリーニング対象数が CSV より少ない問題を診断・修正するためのツール群です。

## 🔧 Scripts

### 1. `audit_secondary_candidates.py` - 監査スクリプト

CSV ファイルと DB 内の `SecondaryArticle` レコードを比較し、不一致を検出します。

**使用方法**:
```bash
python -m app.scripts.audit_secondary_candidates \
  --physical /path/to/category_physical_allgroups.csv \
  --brain /path/to/category_brain_allgroups.csv \
  --psycho /path/to/category_psycho_allgroups.csv \
  [--database-url sqlite:///...] \
  [--output-dir data/]
```

**出力**:
- 標準出力: サマリー表示
- `data/audit_secondary_report.json`: 詳細レポート
- `data/missing_pmids_*.csv`: 不足PMID一覧

**例**:
```bash
# ローカル開発
python -m app.scripts.audit_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --database-url "sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db"

# サーバー本番
export DATABASE_URL="sqlite:////home/yvofxbku/apathy_data/apathy_screening.db"
python -m app.scripts.audit_secondary_candidates \
  --physical /mnt/data/category_physical_allgroups.csv \
  --brain /mnt/data/category_brain_allgroups.csv \
  --psycho /mnt/data/category_psycho_allgroups.csv
```

---

### 2. `reconcile_secondary_candidates.py` - 補充スクリプト

不足している PMID のカテゴリフラグを安全に更新します。

**⚠️ 必ず `--dry-run` で確認してから実行してください！**

**使用方法**:
```bash
# Step 1: Dry-run で確認
python -m app.scripts.reconcile_secondary_candidates \
  --physical /path/to/category_physical_allgroups.csv \
  --brain /path/to/category_brain_allgroups.csv \
  --psycho /path/to/category_psycho_allgroups.csv \
  --dry-run

# Step 2: 問題なければ実行
python -m app.scripts.reconcile_secondary_candidates \
  --physical /path/to/category_physical_allgroups.csv \
  --brain /path/to/category_brain_allgroups.csv \
  --psycho /path/to/category_psycho_allgroups.csv \
  --create-missing
```

**特徴**:
- 既存の `SecondaryReview` は一切変更しない
- 既存の `SecondaryAutoExtraction` は一切変更しない
- `created_at` は上書きしない
- 複数回実行しても安全（冪等性）

**例**:
```bash
# Dry-run
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --database-url "sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db" \
  --dry-run

# 実行
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --database-url "sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db" \
  --create-missing
```

---

### 3. `verify_secondary_display.py` - 検証スクリプト

`/secondary` エンドポイントで表示される件数が、CSV と一致していることを確認します。

**使用方法**:
```bash
python -m app.scripts.verify_secondary_display \
  [--database-url sqlite:///...]
```

**例**:
```bash
python -m app.scripts.verify_secondary_display \
  --database-url "sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db"
```

**期待される出力**:
```
Category     Expected     Display      Match   
--------------------------------------------------
physical     314          314          ✅       
brain        879          879          ✅       
psycho       344          344          ✅       
```

---

## 📊 実行フロー例

```bash
# 1. 現状診断
python -m app.scripts.audit_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv

# 2. 結果を確認
cat data/audit_secondary_report.json

# 3. Dry-run で補充を確認
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --dry-run

# 4. 実際に補充
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --create-missing

# 5. 検証
python -m app.scripts.verify_secondary_display
python -m app.scripts.audit_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv
```

---

## 🔐 Safety Guarantees

✅ **新規作成・削除なし**: 不足フラグの追加のみ  
✅ **レビューデータ保護**: `SecondaryReview` テーブルは変更しない  
✅ **自動抽出保護**: `SecondaryAutoExtraction` テーブルは変更しない  
✅ **Timestamps保護**: `created_at` は上書きしない  
✅ **冪等性**: 何度実行してもOK  
✅ **Dry-run対応**: 実行前に確認可能  

---

## ⚠️ Database URLs

### ローカル開発
```
sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db
```

### サーバー本番 🚨 **必ずこれを使用**
```
sqlite:////home/yvofxbku/apathy_data/apathy_screening.db
```

---

## 📋 Troubleshooting

### "unable to open database file" エラー
→ DATABASE_URL の パスを確認してください

### Missing count が0でない
→ CSV ファイルのパスが正しいか確認してください

### 修正前と後で件数が変わっていない
→ `verify_secondary_display.py` で確認してください

---

## 📚 関連ドキュメント

- [RECONCILIATION_REPORT.md](./RECONCILIATION_REPORT.md) - 詳細な調査・修正レポート
- [app/models.py](./app/models.py) - データモデル定義
- [app/main.py](./app/main.py) - /secondary エンドポイント実装

---

## 🎯 Success Criteria

修正が成功すれば以下の状態になります：

| Category | Before | After | Status |
|----------|--------|-------|--------|
| Physical | 206 | 314 | ✅ |
| Brain | 609 | 879 | ✅ |
| Psycho | 332 | 344 | ✅ |

---

**最終更新**: 2026-01-26  
**作成者**: 自動化スクリプト
