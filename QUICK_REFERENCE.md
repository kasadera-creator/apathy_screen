# 🎯 クイックリファレンス - 二次スクリーニング修正

## 📌 1行ザマリ
**問題**: 二次スクリーニング表示件数（206/609/332）がCSV件数（314/879/344）より少ない  
**原因**: DBのカテゴリフラグ（is_physical/brain/psycho）が390件未設定  
**解決**: 390件のフラグを安全に更新 → 100% CSV一致達成 ✅

---

## ⚡ 実行コマンド（コピペ用）

### 1️⃣ 現状診断
```bash
cd /Users/kuniyuki/apathy_screen_app
python -m app.scripts.audit_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --database-url "sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db"
```

### 2️⃣ Dry-run確認（必須！）
```bash
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --database-url "sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db" \
  --dry-run
```

### 3️⃣ 実行（390件更新）
```bash
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --database-url "sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db" \
  --create-missing
```

### 4️⃣ 検証
```bash
python -m app.scripts.verify_secondary_display \
  --database-url "sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db"
```

---

## 📊 修正前後

| カテゴリ | CSV | Before | After | Status |
|---------|-----|--------|-------|--------|
| Physical | 314 | 206 | **314** | ✅ |
| Brain | 879 | 609 | **879** | ✅ |
| Psycho | 344 | 332 | **344** | ✅ |

---

## 📚 ドキュメント

| ファイル | 対象 | 説明 |
|---------|------|------|
| **README_SOLUTION.md** | 全員 | ⭐ ココから読む |
| SOLUTION_SUMMARY.md | 管理者 | 詳細サマリ |
| SCRIPTS_USAGE.md | エンジニア | スクリプト使い方 |
| RECONCILIATION_REPORT.md | 開発チーム | 技術詳細 |

---

## 🔒 安全性ガイド

✅ **既存レビュー**: 保持  
✅ **既存抽出**: 保持  
✅ **冪等性**: 複数回実行OK  
✅ **Dry-run**: 事前確認可能  
✅ **ロールバック**: 不要

---

## ⚠️ 注意点

- **DB URL**:
  - ローカル: `sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db`
  - サーバー: `sqlite:////home/yvofxbku/apathy_data/apathy_screening.db` ⚠️

- **必ず Dry-run で確認してから実行**

- **サーバー展開前に、上記コマンドをローカルで実行して動作確認**

---

## 🚀 サーバー展開手順

```bash
# 1. スクリプトをコピー
scp app/scripts/{audit,reconcile,verify}_secondary*.py \
    server:/home/yvofxbku/apathy_screen_app/app/scripts/

# 2. サーバーで実行
ssh server
cd /home/yvofxbku/apathy_screen_app
export DATABASE_URL="sqlite:////home/yvofxbku/apathy_data/apathy_screening.db"

# Dry-run
python -m app.scripts.reconcile_secondary_candidates \
  --physical /mnt/data/category_physical_allgroups.csv \
  --brain /mnt/data/category_brain_allgroups.csv \
  --psycho /mnt/data/category_psycho_allgroups.csv \
  --dry-run

# 実行
python -m app.scripts.reconcile_secondary_candidates \
  --physical /mnt/data/category_physical_allgroups.csv \
  --brain /mnt/data/category_brain_allgroups.csv \
  --psycho /mnt/data/category_psycho_allgroups.csv \
  --create-missing

# 3. アプリ再起動
./restart.sh
```

---

## 📞 トラブルシューティング

| 症状 | 対応 |
|------|------|
| DB接続エラー | DB URL パスを確認 |
| Missing count > 0 | CSV ファイルパス確認 |
| 件数が変わらない | `verify_secondary_display.py` 実行 |

---

## ✨ 最終確認チェックリスト

- [ ] Dry-run 出力: 390 records to update
- [ ] 実行後: 390 records updated
- [ ] verify_secondary_display: Physical/Brain/Psycho が CSV と一致
- [ ] /secondary ページ: 件数が 314/879/344 に更新

---

**完了日**: 2026-01-26 ✅  
**ステータス**: 本番展開可能
