# 二次スクリーニング対象数不一致 - 調査・補充完了レポート

**実施日**: 2026-01-26  
**作業内容**: 二次スクリーニング対象数がCSVより少ない問題の原因調査と安全な補充

---

## 📊 問題の概要

### 現象
/secondary に表示されている二次スクリーニング対象数が、インポート用CSVファイルの件数より少なかった：

| カテゴリ | CSV件数 | 表示件数（修正前） | 不足数 |
|---------|--------|-----------------|-------|
| 身体要因（Physical）| 314 | 206 | **108** |
| 脳神経疾患（Brain） | 879 | 609 | **270** |
| 精神心理環境要因（Psycho） | 344 | 332 | **12** |
| **合計** | **1,537** | **1,147** | **390** |

### 影響
- /secondary の表示件数が不正確
- CSVで定義された全候補に対して二次スクリーニングが実施されていない可能性
- スクリーニング母集団の過小報告

---

## 🔍 根本原因の特定

### 調査手法
新規作成した監査スクリプト (`app/scripts/audit_secondary_candidates.py`) で、CSV vs DBの差分を定量化：

```python
# CSV から PMID を正規化して集合化
# DB から二次候補（SecondaryArticle）をカテゴリ別に取得
# 差分を計算・レポート
```

### 根本原因の判明

**予想外の発見**：PMIDはDB内に存在するが、**カテゴリフラグ（is_physical/is_brain/is_psycho）が未設定**

#### 詳細分析

1. **Audit結果**（修正前）:
   - Physical: DB内に206件の `is_physical=True`
   - Brain: DB内に609件の `is_brain=True`  
   - Psycho: DB内に332件の `is_psycho=True`
   - しかし、これらのPMIDのうち108/270/12件は**別のカテゴリ行では存在するが、当該カテゴリではフラグが立っていない**

2. **推定原因**:
   - 初期インポート時に、SecondaryArticle テーブルには複数のカテゴリから参照されるPMIDが挿入される
   - しかし、インポートロジックが正確に**全てのカテゴリフラグを一度に設定できず**、部分的にしか反映されない
   - 結果として、`SELECT * FROM SecondaryArticle WHERE is_physical=True` などの集計が不正確になる

3. **Display Logic確認**:
   ```python
   # app/main.py - secondary_index() から引用
   col = getattr(SecondaryArticle, f"is_{g}")
   total = session.exec(
       select(func.count(SecondaryArticle.id)).where(col == True)
   ).one()
   ```
   → 正しく実装されている。問題はDBのカテゴリフラグ設定側にあった。

---

## 🛠️ 実装した解決策

### 1. 監査スクリプト作成
**ファイル**: `app/scripts/audit_secondary_candidates.py`

**機能**:
- CSV（category_physical/brain/psycho_allgroups.csv）から PMID を読込
- DB（SecondaryArticle）から各カテゴリのPMIDを取得
- CSV vs DB の差分を計算・レポート
- `data/audit_secondary_report.json` にサマリを保存
- `data/missing_pmids_{category}.csv` に不足PMID一覧を出力

**実行例**:
```bash
python -m app.scripts.audit_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --database-url sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db
```

**出力**:
```
=====================================================================
Summary
=====================================================================
Category     CSV      DB       Missing  Extra   
--------------------------------------------------
physical     314      206      108      0       
brain        879      609      270      0       
psycho       344      332      12       0       

✓ Report saved: data/audit_secondary_report.json
✓ Missing PMIDs exported: data/missing_pmids_physical.csv (108 rows)
✓ Missing PMIDs exported: data/missing_pmids_brain.csv (270 rows)
✓ Missing PMIDs exported: data/missing_pmids_psycho.csv (12 rows)
```

### 2. 安全な補充スクリプト作成
**ファイル**: `app/scripts/reconcile_secondary_candidates.py`

**特徴**:
- **既存レコードは上書きしない**（SecondaryReview/SecondaryAutoExtraction は保持）
- 不足PMIDのカテゴリフラグだけを更新
- `--dry-run` で事前確認が可能
- `--create-missing` で実際に実行

**Upsert方針**:
```python
# 既に SecondaryArticle が存在する PMID:
#   → is_{category} フラグだけを True に更新
#   → updated_at を現在時刻に更新
#   → その他のフィールドは変更しない

# 存在しないPMID:
#   → 新規作成（今回のケースでは発生しなかった）
```

**実行例**:
```bash
# Dry-run（確認）
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --database-url sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db \
  --dry-run

# 実行（390件を更新）
python -m app.scripts.reconcile_secondary_candidates \
  --physical data/category_physical_allgroups.csv \
  --brain data/category_brain_allgroups.csv \
  --psycho data/category_psycho_allgroups.csv \
  --database-url sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db \
  --create-missing
```

**結果**:
```
Results:
  Created: 0 new SecondaryArticle records
  Updated: 390 existing records (only category flags)
  Total:   390 changes
```

### 3. 検証スクリプト作成
**ファイル**: `app/scripts/verify_secondary_display.py`

/secondary エンドポイントの集計ロジックを実際に実行して、修正後の表示件数を確認

---

## ✅ 修正結果

### 修正前 vs 修正後

| カテゴリ | CSV件数 | 修正前 | 修正後 | 状態 |
|---------|--------|-------|-------|------|
| Physical | 314 | 206 | **314** | ✅ 一致 |
| Brain | 879 | 609 | **879** | ✅ 一致 |
| Psycho | 344 | 332 | **344** | ✅ 一致 |

### 監査スクリプト確認（修正後）

```
Auditing physical...
  CSV count:         314
  DB count:          314     ✅ Missing: 0

Auditing brain...
  CSV count:         879
  DB count:          879     ✅ Missing: 0

Auditing psycho...
  CSV count:         344
  DB count:          344     ✅ Missing: 0
```

### 既存データ保護確認
- ✅ SecondaryReview（レビュー履歴）: 保持
- ✅ SecondaryAutoExtraction（Gemini自動抽出）: 保持  
- ✅ created_at: 上書きなし
- ✅ 既レビュー件数: 影響なし

---

## 📋 提供ファイル一覧

### 新規作成スクリプト

| ファイル | 説明 |
|---------|------|
| `app/scripts/audit_secondary_candidates.py` | CSV vs DB 監査スクリプト |
| `app/scripts/reconcile_secondary_candidates.py` | 安全な補充スクリプト |
| `app/scripts/verify_secondary_display.py` | 表示件数検証スクリプト |

### 生成レポート

| ファイル | 説明 |
|---------|------|
| `data/audit_secondary_report.json` | 監査結果サマリ（JSON形式） |
| `data/missing_pmids_physical.csv` | 不足していたPhysical PMID一覧（108件） |
| `data/missing_pmids_brain.csv` | 不足していたBrain PMID一覧（270件） |
| `data/missing_pmids_psycho.csv` | 不足していたPsycho PMID一覧（12件） |

---

## 🚀 サーバーへの展開手順

### 前提条件
- サーバー上の正式DB: `/home/yvofxbku/apathy_data/apathy_screening.db`
- 環境変数: `DATABASE_URL=sqlite:////home/yvofxbku/apathy_data/apathy_screening.db`

### 展開手順

1. **スクリプトファイルをサーバーにコピー**:
   ```bash
   scp app/scripts/audit_secondary_candidates.py server:/path/to/apathy_screen_app/app/scripts/
   scp app/scripts/reconcile_secondary_candidates.py server:/path/to/apathy_screen_app/app/scripts/
   scp app/scripts/verify_secondary_display.py server:/path/to/apathy_screen_app/app/scripts/
   ```

2. **サーバー上でDry-runを実行**:
   ```bash
   ssh server
   cd /home/yvofxbku/apathy_screen_app
   
   export DATABASE_URL="sqlite:////home/yvofxbku/apathy_data/apathy_screening.db"
   
   python -m app.scripts.reconcile_secondary_candidates \
     --physical /mnt/data/category_physical_allgroups.csv \
     --brain /mnt/data/category_brain_allgroups.csv \
     --psycho /mnt/data/category_psycho_allgroups.csv \
     --dry-run
   ```

3. **実行（確認後）**:
   ```bash
   python -m app.scripts.reconcile_secondary_candidates \
     --physical /mnt/data/category_physical_allgroups.csv \
     --brain /mnt/data/category_brain_allgroups.csv \
     --psycho /mnt/data/category_psycho_allgroups.csv \
     --create-missing
   ```

4. **検証**:
   ```bash
   python -m app.scripts.audit_secondary_candidates \
     --physical /mnt/data/category_physical_allgroups.csv \
     --brain /mnt/data/category_brain_allgroups.csv \
     --psycho /mnt/data/category_psycho_allgroups.csv
   
   python -m app.scripts.verify_secondary_display
   ```

5. **アプリケーション再起動**:
   ```bash
   ./restart.sh
   ```

6. **ブラウザで確認**:
   - https://amed-apathy.click/secondary にアクセス
   - 表示件数が以下の通りであることを確認：
     - 身体要因: 314
     - 脳神経疾患: 879
     - 精神心理環境要因: 344

---

## 📝 技術的な詳細

### なぜこの問題が発生したのか

1. **複数ソースからの統合問題**: 
   - SecondaryArticleはCSV（category_*.csv）からインポートされる
   - 複数のカテゴリCSVから同じPMIDが参照される可能性がある
   - 初期インポート時に全カテゴリフラグを同時に設定する仕組みが不十分

2. **インポートロジックの不完全性**:
   ```python
   # import_secondary_candidates.py の current_logic
   # - 1つの PMID を見て、
   # - Article テーブルの final_cat_* から推測するか、
   # - CSV filename で推測するだけ
   # → 複数ファイルからの同一PMID はカバーしきれない
   ```

3. **過去のDB混在**:
   - 過去に別DBを見ていた時期があり、その後統一したが、古いデータが残存していた可能性

### なぜ今回のアプローチが安全か

- ✅ **既存レビューを保持**: `SecondaryReview` には一切触らない
- ✅ **自動抽出を保持**: `SecondaryAutoExtraction` には一切触らない
- ✅ **Timestamps保護**: 既存 `created_at` は上書きしない
- ✅ **Dry-run確認**: 本番前に必ず確認可能
- ✅ **冪等性**: 何度実行してもOK（既に設定済みのフラグは重複更新なし）

---

## ⚠️ 注意事項

### サーバー固有パス
- **ローカル開発**: `sqlite:////Users/kuniyuki/apathy_screen_app/apathy_screening.db`
- **サーバー本番**: `sqlite:////home/yvofxbku/apathy_data/apathy_screening.db` ⚠️ **必ず正式パスを使用**

### CSV仕様
- 必須列: `pmid`
- 形式: 正の整数、またはCSVの場合は小数表記（例: `123.0`）
- NaN, None, 空値は自動スキップ

### 将来の保守

今後、新しいカテゴリCSVを追加する場合：

```bash
python -m app.scripts.reconcile_secondary_candidates \
  --physical ... \
  --brain ... \
  --psycho ... \
  --create-missing
```

と実行するだけで、新しいPMIDが自動的に追加される。

---

## 📞 サポート

問題が発生した場合：

1. `data/audit_secondary_report.json` で現在の状態を確認
2. `app/scripts/audit_secondary_candidates.py --help` で使用方法確認
3. `app/scripts/reconcile_secondary_candidates.py --dry-run` で動作確認
4. `app/scripts/verify_secondary_display.py` で結果検証

---

**完了日**: 2026-01-26  
**検証者**: 監査スクリプト  
**状態**: ✅ 本番展開可能
