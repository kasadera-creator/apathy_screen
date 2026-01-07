from pathlib import Path
from typing import Optional
import math

import pandas as pd
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy import delete

from .models import ScaleArticle

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "apathy_screening.db"
DB_URL = f"sqlite:///{DB_PATH}"

# データファイルの候補
DATA_FILES = [
    BASE_DIR / "data" / "PubMED_scales_with_abstracts_ja_Gemini_screening.xlsx",
    BASE_DIR / "data" / "PubMED_scales_with_abstracts_ja_Gemini_screening.xlsx - Sheet1.csv",
    BASE_DIR / "PubMED_scales_with_abstracts_ja_Gemini_screening.csv",
]

N_GROUPS = 4  # 4グループで均等割り

def to_int_or_none(val) -> Optional[int]:
    """PMID や Publication Year 用の安全な int 変換"""
    if pd.isna(val):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None

def clean_str(val) -> Optional[str]:
    """NaN を None にする、あるいは空文字にする"""
    if pd.isna(val):
        return None
    s = str(val).strip()
    return s if s else None

def read_data_file(path: Path) -> Optional[pd.DataFrame]:
    """拡張子に応じて読み込み。CSVの場合はエンコーディングを自動試行"""
    if path.suffix.lower() == ".csv":
        try:
            # まず標準的な UTF-8 で試す
            print(f"Reading CSV (utf-8): {path}")
            return pd.read_csv(path, encoding="utf-8")
        except UnicodeDecodeError:
            # 失敗したら Windows系 (cp932) で試す
            print(f"Reading CSV (cp932): {path}")
            try:
                return pd.read_csv(path, encoding="cp932")
            except Exception as e:
                print(f"Error reading CSV with cp932: {e}")
                return None
    else:
        # Excel
        print(f"Reading Excel: {path}")
        return pd.read_excel(path)

def main() -> None:
    print("[prepare_scale_db] 尺度データの読み込みを開始します...")
    
    df = None
    for p in DATA_FILES:
        if p.exists():
            df = read_data_file(p)
            if df is not None:
                break
    
    if df is None:
        raise FileNotFoundError(f"データファイルが見つかりません。以下の場所を確認しました: {[str(f) for f in DATA_FILES]}")

    # =========================================================
    # 追加修正: 列名の空白削除 (例: "Abstract " -> "Abstract")
    # =========================================================
    df.columns = df.columns.str.strip()
    print(f"[DEBUG] Detected columns: {list(df.columns)}")

    # =========================================================
    # PMIDが空の行を削除
    # =========================================================
    if "PMID" in df.columns:
        original_count = len(df)
        df = df.dropna(subset=["PMID"])
        cleaned_count = len(df)
        print(f"データクリーニング完了: {original_count} 件 -> {cleaned_count} 件 (空行 {original_count - cleaned_count} 件削除)")
    else:
        print("[WARNING] 'PMID' 列が見つかりません。列名を確認してください。")

    engine = create_engine(DB_URL)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        print("既存の ScaleArticle を削除しています...")
        statement = delete(ScaleArticle)
        session.exec(statement)
        session.commit()

        # PMID順でソート
        if "PMID" in df.columns:
            df = df.sort_values("PMID")
        
        total_rows = len(df)
        print(f"登録対象: {total_rows} 件")

        inserted = 0
        for i, row in df.iterrows():
            pmid_val = to_int_or_none(row.get("PMID"))
            group_no = (i * N_GROUPS // total_rows) + 1
            
            # DOI の取得 (DOI または DOI.1)
            doi_val = clean_str(row.get("DOI"))
            if not doi_val and "DOI.1" in row:
                doi_val = clean_str(row.get("DOI.1"))

            # データの取得（存在しない列は None になる）
            art = ScaleArticle(
                pmid=pmid_val,
                title_en=clean_str(row.get("Title")),
                abstract_en=clean_str(row.get("Abstract")),
                title_ja=clean_str(row.get("Title_ja")),
                abstract_ja=clean_str(row.get("Abstract_ja")),
                citation=clean_str(row.get("Citation")),
                journal=clean_str(row.get("Journal/Book")),
                year=to_int_or_none(row.get("Publication Year")),
                pubmed_url=clean_str(row.get("PubMed")),
                doi=doi_val,
                gemini_judgement=clean_str(row.get("Scale_Judgement")),
                gemini_summary_ja=clean_str(row.get("Scale_Summary_ja")),
                gemini_reason_ja=clean_str(row.get("Scale_Reason_ja")),
                gemini_tools=clean_str(row.get("Scale_Tools")),
                group_no=group_no,
            )

            session.add(art)
            inserted += 1

        session.commit()
        print(f"[prepare_scale_db] ScaleArticle への登録が完了しました（{inserted} 件）。")

        # 確認用ログ
        sample = session.exec(select(ScaleArticle).limit(1)).first()
        if sample:
            print("-" * 40)
            print(f"サンプル確認 (ID: {sample.id})")
            print(f"  PMID: {sample.pmid}")
            print(f"  Title_ja: {sample.title_ja[:30]}..." if sample.title_ja else "  Title_ja: None")
            print(f"  Abstract_en: {sample.abstract_en[:30]}..." if sample.abstract_en else "  Abstract_en: None")
            print(f"  Abstract_ja: {sample.abstract_ja[:30]}..." if sample.abstract_ja else "  Abstract_ja: None")
            print("-" * 40)

if __name__ == "__main__":
    main()