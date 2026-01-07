from pathlib import Path
from typing import Optional

import pandas as pd
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy import delete

from .models import ScaleArticle


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "apathy_screening.db"
DB_URL = f"sqlite:///{DB_PATH}"

EXCEL_PATH = BASE_DIR / "data" / "PubMED_scales_with_abstracts_ja_Gemini_screening.xlsx"

N_GROUPS = 4  # ユーザーと同じ 4 グループで均等割り


def to_int_or_none(val) -> Optional[int]:
    """PMID や Publication Year 用の安全な int 変換"""
    if pd.isna(val):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def clean_str(val) -> str:
    """NaN を空文字にするヘルパー"""
    if pd.isna(val):
        return ""
    return str(val).strip()


def main() -> None:
    print("[prepare_scale_db] 尺度 Excel を読み込みます...")
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"Excel ファイルが見つかりません: {EXCEL_PATH}")

    df = pd.read_excel(EXCEL_PATH)

    required_cols = [
        "PMID",
        "Title",
        "Title_ja",
        "Abstract",
        "Abstract_ja",
        "Citation",
        "Journal/Book",
        "Publication Year",
        "PubMed",
        # DOI は DOI.1 優先, 無ければ DOI を使うのでここは必須リストには入れない
        "Scale_Judgement",
        "Scale_Summary_ja",
        "Scale_Reason_ja",
        "Scale_Tools",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Excel に必要な列が見つかりません: {missing}\n実際の列: {list(df.columns)}")

    # PMID が欠損している行は除外
    df = df[~df["PMID"].isna()].copy().reset_index(drop=True)
    n = len(df)
    print(f"[prepare_scale_db] 有効な行数: {n}")

    # group_no を均等割りで付与
    # 1〜N_GROUPS にほぼ同数ずつ振り分ける
    group_list = [(i * N_GROUPS) // n + 1 for i in range(n)]
    df["group_no"] = group_list

    print("[prepare_scale_db] DB 接続 & テーブル作成...")
    engine = create_engine(DB_URL, echo=False)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        # 既存の ScaleArticle は一旦全削除
        print("[prepare_scale_db] 既存の ScaleArticle を削除します...")
        session.exec(delete(ScaleArticle))
        session.commit()

        print("[prepare_scale_db] ScaleArticle へデータを投入します...")
        inserted = 0

        for _, row in df.iterrows():
            pmid_val = to_int_or_none(row.get("PMID"))
            if pmid_val is None:
                continue

            # DOI URL は DOI.1 優先, 無ければ DOI
            doi_url = ""
            if "DOI.1" in df.columns and not pd.isna(row.get("DOI.1")):
                doi_url = clean_str(row.get("DOI.1"))
            elif "DOI" in df.columns and not pd.isna(row.get("DOI")):
                doi_url = clean_str(row.get("DOI"))

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
                doi_url=doi_url,
                gemini_judgement=clean_str(row.get("Scale_Judgement")),
                gemini_summary_ja=clean_str(row.get("Scale_Summary_ja")),
                gemini_reason_ja=clean_str(row.get("Scale_Reason_ja")),
                gemini_tools=clean_str(row.get("Scale_Tools")),
                group_no=int(row.get("group_no", 1)),
            )

            session.add(art)
            inserted += 1

        session.commit()
        print(f"[prepare_scale_db] ScaleArticle への登録が完了しました（{inserted} 件）。")

        # デバッグ用: 先頭数件の内容を確認
        sample = session.exec(
            select(ScaleArticle).order_by(ScaleArticle.id).limit(3)
        ).all()
        print("[prepare_scale_db] サンプル：")
        for a in sample:
            print(
                f"  id={a.id}, pmid={a.pmid}, "
                f"judgement={a.gemini_judgement}, "
                f"summary_head={a.gemini_summary_ja[:30]!r}"
            )


if __name__ == "__main__":
    main()
