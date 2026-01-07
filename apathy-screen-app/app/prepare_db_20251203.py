from pathlib import Path
from typing import Optional

import pandas as pd
from sqlmodel import SQLModel, create_engine, Session

from .models import Article, ScreeningDecision, User  # テーブル定義を全部読み込む


# =========================================================
# 設定：ここだけ変えれば「何年以降」にでも自由に変更できます
# =========================================================
YEAR_MIN: Optional[int] = 2015  # 例: 2015 などに変更して再実行すればOK
N_GROUPS: int = 4               # グループ数（基本は 5 のままで良いと思います）


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "apathy_screening.db"
DB_URL = f"sqlite:///{DB_PATH}"
EXCEL_PATH = BASE_DIR / "data" / "PubMED_with_abstracts_ja_LLM3.xlsx"


def to_int_or_none(val) -> Optional[int]:
    """NaN や '保留' などを安全に None にしてくれるヘルパー。"""
    if pd.isna(val):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def assign_groups_by_authors(
    df: pd.DataFrame,
    year_min: Optional[int] = None,
    n_groups: int = 5,
) -> pd.DataFrame:
    """
    （任意で year_min 以降に絞ったうえで）
    Authors アルファベット順に並べ、上から順に n_groups グループに
    できるだけ均等に割り振る。

    year_min を None にすると年によるフィルタ無しでそのまま使います。
    """

    # -------------------------
    # 年によるフィルタ（Publication Year 列を使用）
    # -------------------------
    if year_min is not None and "Publication Year" in df.columns:
        before = len(df)
        df = df[df["Publication Year"].fillna(0) >= year_min].copy()
        after = len(df)
        print(f"[prepare_db] YEAR_MIN = {year_min} で {before} → {after} 件に絞り込みました。")
    elif year_min is not None and "Publication Year" not in df.columns:
        print("[prepare_db] YEAR_MIN が指定されていますが 'Publication Year' 列が見つからないため、年フィルタはスキップされました。")

    # -------------------------
    # Authors でソート（なければ PMID）
    # -------------------------
    if "Authors" in df.columns:
        df = df.sort_values(by="Authors", kind="mergesort")
    else:
        df = df.sort_values(by="PMID", kind="mergesort")

    df = df.reset_index(drop=True)
    n = len(df)
    if n == 0:
        print("[prepare_db] フィルタ後のレコード数が 0 件です。YEAR_MIN の設定や元データを確認してください。")
        df["group_no"] = []
        return df

    # 0〜n-1 のインデックスを 1〜n_groups に均等割りする簡単なトリック
    group_list = []
    for i in range(n):
        g = (i * n_groups) // n + 1  # 1〜n_groups の整数
        group_list.append(g)

    df["group_no"] = group_list
    print(f"[prepare_db] {n} 件を {n_groups} グループに割り当てました。")
    return df


def main():
    # 既存 DB を一度消して作り直す（※ここで一旦 Screening の結果も消えます）
    if DB_PATH.exists():
        print(f"[prepare_db] 既存 DB を削除します: {DB_PATH}")
        DB_PATH.unlink()

    engine = create_engine(DB_URL, echo=False)

    # Article / ScreeningDecision / User テーブルを作成
    SQLModel.metadata.create_all(engine)

    # Excel 読み込み
    print(f"[prepare_db] Excel 読み込み中: {EXCEL_PATH}")
    df = pd.read_excel(EXCEL_PATH)

    # グループ割り当て（YEAR_MIN と N_GROUPS を使用）
    df = assign_groups_by_authors(df, year_min=YEAR_MIN, n_groups=N_GROUPS)

    with Session(engine) as session:
        for _, row in df.iterrows():
            year_raw = row.get("Publication Year")
            year_val: Optional[int]
            try:
                year_val = int(year_raw) if pd.notna(year_raw) else None
            except (ValueError, TypeError):
                year_val = None

            doi_raw = row.get("DOI")
            doi_val = None
            if isinstance(doi_raw, str) and doi_raw.strip():
                doi_val = doi_raw.strip()

            art = Article(
                pmid=int(row["PMID"]),
                title_en=str(row.get("Title", "")),
                abstract_en=str(row.get("Abstract", "")),
                authors=str(row.get("Authors", "")),
                citation=str(row.get("Citation", "")),
                journal=str(row.get("Journal/Book", "")),
                year=year_val,
                title_ja=str(row.get("タイトル", "")),
                abstract_ja=str(row.get("アブストラクト", "")),
                doi=doi_val,
                gpt_reason=str(row.get("GPT5.1「アパシー」判断根拠", "")),
                condition_list_gpt=str(row.get("ChatGPT5.1が見つけた病態・状態", "")),
                condition_list_gemini=str(row.get("Gemini2.5proが見つけた病態・状態", "")),
                age_focus_gpt=str(row.get("Age_focus_GPT", "")),
                direction_gpt=to_int_or_none(row.get("Direction_GPT")),
                apathy_centrality_gpt=str(row.get("Apathy_centrality_GPT", "")),
                judgement_gpt=str(row.get("Judgement_GPT", "")),
                age_focus_gemini=str(row.get("Age_focus_Gemini", "")),
                direction_gemini=to_int_or_none(row.get("Direction_Gemini")),
                apathy_centrality_gemini=str(row.get("Apathy_centrality_Gemini", "")),
                judgement_gemini=str(row.get("Judgement_Gemini", "")),
                group_no=int(row["group_no"]),
            )
            session.add(art)

        session.commit()
        print("[prepare_db] Article テーブルへの登録が完了しました。")


if __name__ == "__main__":
    main()
