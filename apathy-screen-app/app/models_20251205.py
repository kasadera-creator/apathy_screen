from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship


class Article(SQLModel, table=True):
    """
    病態スクリーニング対象のメイン文献テーブル（3416件）
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    pmid: int
    title_en: str = ""
    abstract_en: str = ""
    authors: str = ""
    citation: str = ""
    journal: str = ""
    year: Optional[int] = None

    title_ja: str = ""
    abstract_ja: str = ""
    doi: Optional[str] = None

    # LLM 判定関連
    gpt_reason: str = ""
    condition_list_gpt: str = ""
    condition_list_gemini: str = ""

    age_focus_gpt: str = ""
    direction_gpt: Optional[int] = None
    apathy_centrality_gpt: str = ""
    judgement_gpt: str = ""

    age_focus_gemini: str = ""
    direction_gemini: Optional[int] = None
    apathy_centrality_gemini: str = ""
    judgement_gemini: str = ""

    # グループ番号（1〜4）
    group_no: int

    # 病態スクリーニング結果（ユーザーごと）
    screenings: List["ScreeningDecision"] = Relationship(back_populates="article")

    # ★スケール関連カラム（Gemini 2.5 Pro による自動判定）
    scale_summary_ja: Optional[str] = Field(default=None, description="Scale_Summary_ja")
    scale_judgement: Optional[str] = Field(default=None, description="Scale_Judgement")
    scale_reason_ja: Optional[str] = Field(default=None, description="Scale_Reason_ja")
    scale_tools: Optional[str] = Field(default=None, description="Scale_Tools")


class User(SQLModel, table=True):
    """
    スクリーニング実施者
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    username: str
    password_hash: str
    group_no: int  # 1〜4

    # 病態用の一次スクリーニング結果
    decisions: List["ScreeningDecision"] = Relationship(back_populates="user")
    # 尺度用の一次スクリーニング結果
    scale_decisions: List["ScaleScreeningDecision"] = Relationship(back_populates="user")


class ScreeningDecision(SQLModel, table=True):
    """
    病態スクリーニングの一次判定（1ユーザー × 1論文で最大1行）
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(foreign_key="user.id")
    article_id: int = Field(foreign_key="article.id")

    # 判定（1:採用 / 0:保留 / -1:除外 などの予定）
    decision: int
    comment: Optional[str] = None

    # 研究目的フラグ
    flag_cause: bool = Field(default=False)      # 原因病態リストに使えそう
    flag_treatment: bool = Field(default=False)  # 治療・対応リストに使えそう

    user: Optional[User] = Relationship(back_populates="decisions")
    article: Optional[Article] = Relationship(back_populates="screenings")


class AppConfig(SQLModel, table=True):
    """
    アプリ全体の設定（例：year_min）
    """
    id: int = Field(default=1, primary_key=True)
    year_min: Optional[int] = Field(default=2015)


class ScaleArticle(SQLModel, table=True):
    """
    評価尺度用の文献テーブル（731件）
    - group_no: 1〜4 のいずれか（prepare_scale_db.py で割り当て）
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    pmid: int
    title_en: str = ""
    abstract_en: str = ""
    title_ja: str = ""
    abstract_ja: str = ""
    citation: str = ""
    journal: str = ""
    year: Optional[int] = None

    pubmed_url: str = ""
    doi_url: str = ""

    gemini_judgement: str = ""     # Scale_Judgement
    gemini_summary_ja: str = ""    # Scale_Summary_ja
    gemini_reason_ja: str = ""     # Scale_Reason_ja
    gemini_tools: str = ""         # Scale_Tools

    group_no: int

    # この論文に対する尺度用一次スクリーニング結果（ユーザーごと）
    scale_screenings: List["ScaleScreeningDecision"] = Relationship(
        back_populates="article"
    )


class ScaleScreeningDecision(SQLModel, table=True):
    """
    評価尺度用の一次スクリーニング結果
    - 1ユーザー × 1論文 で最大1行
    - 各論文を2人が評価する構造
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    user_id: int = Field(foreign_key="user.id")
    scale_article_id: int = Field(foreign_key="scalearticle.id")

    # ３段階評価のラベル
    #   "採用" / "要検討" / "除外" / None
    rating: Optional[str] = None
    comment: Optional[str] = None

    user: Optional[User] = Relationship(back_populates="scale_decisions")
    article: Optional[ScaleArticle] = Relationship(back_populates="scale_screenings")
