# 🎯 二次スクリーニング対象数不一致 - 完全ソリューション

## 📌 クイックスタート

### 問題
二次スクリーニング表示件数（206/609/332）が CSV 件数（314/879/344）より少ない

### 解決方法
```bash
# 1. 診断
cd /Users/kuniyuki/apathy_screen_app
python -m app.scripts.audit_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv

# 2. Dry-run確認
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --dry-run

# 3. 実行
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --create-missing

# 4. 検証
python -m app.scripts.verify_secondary_display
```

### 結果
```
✅ Physical: 314 (was 206, fixed +108)
✅ Brain: 879 (was 609, fixed +270)
✅ Psycho: 344 (was 332, fixed +12)
✅ Total: +390 candidates added
```

---

## 📚 ドキュメント一覧

### 1. **[SOLUTION_SUMMARY.md](SOLUTION_SUMMARY.md)** ⭐ はじめにこれを読む
- **対象**: プロジェクト管理者・技術リーダー
- **内容**: 問題・根本原因・解決結果の完全サマリ
- **時間**: 5分

### 2. **[SCRIPTS_USAGE.md](SCRIPTS_USAGE.md)** 🔧 スクリプトの使い方
- **対象**: エンジニア・運用担当者
- **内容**: 各スクリプトの詳細な使用方法・オプション・トラブル対応
- **時間**: 10分

### 3. **[RECONCILIATION_REPORT.md](RECONCILIATION_REPORT.md)** 📋 詳細な技術レポート
- **対象**: 開発チーム・監査者
- **内容**: 根本原因の詳細分析・実装詳細・安全性保証・サーバー展開手順
- **時間**: 20分

---

## 🛠️ スクリプト一覧

| スクリプト | 行数 | サイズ | 目的 |
|-----------|------|-------|------|
| `app/scripts/audit_secondary_candidates.py` | 278 | 9.7K | CSV vs DB 差分検出 |
| `app/scripts/reconcile_secondary_candidates.py` | 264 | 9.0K | 不足PMID補充（安全） |
| `app/scripts/verify_secondary_display.py` | 74 | 2.1K | 表示件数検証 |
| **合計** | **616** | **20.8K** | — |

---

## 📊 修正結果

```
        修正前              修正後
        ↓                 ↓
Physical  206  ➜  314  (+108, +52%)
Brain     609  ➜  879  (+270, +44%)
Psycho    332  ➜  344  (+12, +4%)
─────────────────────────────
Total    1147  ➜ 1537  (+390, +34%)
```

**CSV 一致度**: 75% ➜ **100%** ✅

---

## 🚀 展開フロー

```
1️⃣ ローカルで動作確認（完了）
   ✅ audit_secondary_candidates.py: 390 missing detected
   ✅ reconcile_secondary_candidates.py --dry-run: 390 records to update
   ✅ reconcile_secondary_candidates.py --create-missing: 390 records updated
   ✅ verify_secondary_display.py: All counts match

2️⃣ サーバーへの展開（準備完了）
   □ ファイルをコピー
   □ Dry-run で確認
   □ 実行
   □ アプリ再起動
   □ ブラウザで確認

3️⃣ 本番運用（継続監視）
   □ 月1回の監査実行
   □ 新CSV追加時の補充実行
```

---

## ✅ 安全性チェックリスト

- ✅ **既存レビュー保護**: SecondaryReview テーブルは未変更
- ✅ **自動抽出保護**: SecondaryAutoExtraction テーブルは未変更
- ✅ **Timestamps保護**: created_at は上書きなし
- ✅ **冪等性**: 複数回実行しても安全
- ✅ **Dry-run対応**: 実行前に確認可能
- ✅ **ロールバック不要**: フラグ追加のみ（データ削除なし）

---

## 🔐 Database URLs

```bash
# ローカル開発
sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db

# サーバー本番 ⚠️ **必ずこれを使用**
sqlite:////home/yvofxbku/apathy_data/apathy_screening.db
```

---

## 📈 改善数字

| 指標 | 数値 |
|-----|------|
| 修正されたPMID数 | 390 |
| 追加されたカテゴリフラグ | 390 |
| 新規作成行 | 0 |
| 削除行 | 0 |
| 影響を受けた既存レビュー | 0 |
| 影響を受けた既存抽出 | 0 |
| 実行時間（修正） | < 1秒 |
| ロールバック必要性 | なし |

---

## 📞 サポート情報

### 各ドキュメントの参照
1. **「何が起きたか知りたい」** → [SOLUTION_SUMMARY.md](SOLUTION_SUMMARY.md)
2. **「スクリプトをどう使うか」** → [SCRIPTS_USAGE.md](SCRIPTS_USAGE.md)
3. **「なぜこれが安全なのか」** → [RECONCILIATION_REPORT.md](RECONCILIATION_REPORT.md)

### トラブルシューティング

| 症状 | 対応 |
|-----|------|
| "unable to open database file" | DATABASE_URL パスを確認 |
| Missing count が0でない | CSV ファイルパスを確認 |
| 件数が変わっていない | `verify_secondary_display.py` で確認 |
| Dry-run 結果と実行結果が異なる | DB接続URLを確認 |

---

## 🎯 検証チェックリスト（サーバー展開前）

- [ ] 3つのスクリプトをサーバーにコピー
- [ ] Database URL をサーバーの正式パスに設定
- [ ] `audit_secondary_candidates.py` でdry-run確認
- [ ] 修正前の件数をスクリーンショット記録
- [ ] `reconcile_secondary_candidates.py --dry-run` で確認
- [ ] `reconcile_secondary_candidates.py --create-missing` で実行
- [ ] `verify_secondary_display.py` で件数確認
- [ ] /secondary にブラウザアクセスして確認
- [ ] 修正後の件数がドキュメント値（314/879/344）と一致
- [ ] 既存レビューが残っていることを確認

---

## 📅 実施履歴

| 日時 | 内容 | 状態 |
|-----|------|------|
| 2026-01-26 13:59 | audit_secondary_candidates.py 実行 | ✅ 390 missing detected |
| 2026-01-26 14:00 | reconcile_secondary_candidates.py --dry-run | ✅ Confirmed |
| 2026-01-26 14:00 | reconcile_secondary_candidates.py --create-missing | ✅ 390 updated |
| 2026-01-26 14:00 | verify_secondary_display.py | ✅ All counts match CSV |

---

## 📊 ファイル構成

```
apathy_screen_app/
├── 📄 SOLUTION_SUMMARY.md          ⭐ ここから読む
├── 📄 SCRIPTS_USAGE.md             スクリプト使用方法
├── 📄 RECONCILIATION_REPORT.md     詳細レポート
├── 📄 README.md (本ファイル)
│
├── app/scripts/
│   ├── audit_secondary_candidates.py        (278 行)
│   ├── reconcile_secondary_candidates.py    (264 行)
│   └── verify_secondary_display.py          (74 行)
│
└── data/
    ├── audit_secondary_report.json
    ├── missing_pmids_physical.csv   (108 PMIDs)
    ├── missing_pmids_brain.csv      (270 PMIDs)
    └── missing_pmids_psycho.csv     (12 PMIDs)
```

---

## 🎓 技術的なハイライト

### 採用した技術
- **SQLModel/SQLAlchemy**: 型安全なDB操作
- **Set演算**: 効率的な差分計算
- **CSV DictReader**: 堅牢なCSV処理
- **Dry-run パターン**: 安全な本番対応

### ベストプラクティス
- ✅ 既存データの保護
- ✅ トランザクション安全性
- ✅ 冪等性保証
- ✅ 監査ログの作成
- ✅ Dry-run対応

---

## ✨ 最後に

この修正により：

1. **正確性**: CSV と DB の件数が完全に一致 ✅
2. **安全性**: 既存レビュー・抽出データは全て保持 ✅
3. **再現性**: 今後の追加・修正も自動化可能 ✅
4. **監視性**: 問題発生時の検出・診断が容易 ✅

---

**最終ステータス**: 🟢 **本番展開可能**

修正内容: 390件の不足PMID補充  
実行時間: < 1秒  
リスク評価: **低** ✅  
検証状態: **完全確認済み** ✅

---

**作成日**: 2026-01-26  
**バージョン**: 1.0  
**ステータス**: 完了・本番対応可能
