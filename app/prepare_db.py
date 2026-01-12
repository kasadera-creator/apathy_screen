# app/prepare_db.py

"""
PubMED_with_abstracts_ja_LLM3.xlsx から Article テーブルを作り直すスクリプト。

 病態システマティックレビュー用の 3416 件を対象
 英語/日本語アブストラクト、GPT/Gemini の判定結果などを Article に格納
 年度フィルタとグループ数は YEAR_MIN, N_GROUPS で制御
"""

from pathlib import Path
from typing import Optional

import pandas as pd
from sqlmodel import SQLModel, create_engine, Session

from .models import Article  # テーブル定義を読み込むだけで十分


# ==============================
# 設定：ここだけ変えればコントロール可能
# ==============================
# 何年以降の論文を対象とするか
#   - 以前「1人あたり ~470件」だったときは YEAR_MIN=2015 + N_GROUPS=4 くらいの設定だったはずです
YEAR_MIN: Optional[int] = 2015  # 例: 2015 / 2010 / None (Noneだと年による絞り込みなし)

# グループ数（= ユーザーグループ数）
#   user1,2 → group_no=1
#   user3,4 → group_no=2
#   user5,6 → group_no=3
#   user7,8 → group_no=4
N_GROUPS: int = 4


BASE_DIR = Path(__file__).resolve().parent.parent
# Require DATABASE_URL from environment; do not fall back to repository or other defaults.
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("DATABASE_URL environment variable is required for prepare_db.py")

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
    n_groups: int = 4,
) -> pd.DataFrame:
    """
    （任意で year_min 以降に絞ったうえで）
    Authors アルファベット順に並べ、上から順に n_groups グループに
    できるだけ均等に割り振る。

    year_min を None にすると年によるフィルタ無し。
    """

    # --- 年によるフィルタ（Publication Year 列を使用） ---
    if year_min is not None and "Publication Year" in df.columns:
        before = len(df)
        df = df[df["Publication Year"].fillna(0) >= year_min].copy()
        after = len(df)
        print(f"[prepare_db] YEAR_MIN = {year_min} で {before} → {after} 件に絞り込みました。")
    elif year_min is not None and "Publication Year" not in df.columns:
        print("[prepare_db] YEAR_MIN が指定されていますが 'Publication Year' 列が見つからないため、年フィルタはスキップされました。")

    # --- Authors でソート（なければ PMID） ---
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

    # 0〜n-1 のインデックスを 1〜n_groups に均等割り
    group_list = []
    for i in range(n):
        g = (i * n_groups) // n + 1  # 1〜n_groups の整数
        group_list.append(g)

    df["group_no"] = group_list
    print(f"[prepare_db] {n} 件を {n_groups} グループに割り当てました。")
    return df


def main():
    # 既存 DB を一度消して作り直す（※ Screening 結果も消えるので注意）
    if DB_URL.startswith("sqlite://"):
        db_path_str = DB_URL.split("sqlite://", 1)[1]
        db_path = Path(db_path_str).expanduser()
        if db_path.exists():
            print(f"[prepare_db] Existing DB file detected: {db_path}")
            print("[prepare_db] It will be overwritten by this script.")
            try:
                db_path.unlink()
                print(f"[prepare_db] Deleted {db_path}")
            except Exception as e:
                print(f"[prepare_db] Failed to delete {db_path}: {e}")

    engine = create_engine(DB_URL, echo=False)

    # models.py に定義されたテーブルをすべて作成
    SQLModel.metadata.create_all(engine)

    # Excel 読み込み
    print(f"[prepare_db] Excel 読み込み中: {EXCEL_PATH}")
    df = pd.read_excel(EXCEL_PATH)

    # グループ割り当て（YEAR_MIN と N_GROUPS を使用）
    df = assign_groups_by_authors(df, year_min=YEAR_MIN, n_groups=N_GROUPS)

    with Session(engine) as session:
        for _, row in df.iterrows():
            # year
            year_raw = row.get("Publication Year")
            try:
                year_val = int(year_raw) if pd.notna(year_raw) else None
            except (ValueError, TypeError):
                year_val = None

            # DOI
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
                # ★ LLM 判定関連（old 版と同じ列名を使用）
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
                # Article.group_no は今は使っていないが、念のため保持
                group_no=int(row["group_no"]),
            )
            session.add(art)

        session.commit()
        print("[prepare_db] Article テーブルへの登録が完了しました。")


if __name__ == "__main__":
    main()
