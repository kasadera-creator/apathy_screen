from typing import Optional
from sqlmodel import SQLModel, Field

# ==========================================
# 共通 / ユーザー
# ==========================================
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    group_no: int = Field(default=1)  # 1..4
    is_admin: bool = Field(default=False)

class AppConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    year_min: Optional[int] = Field(default=2015)

# ==========================================
# 病態スクリーニング用
# ==========================================
class Article(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pmid: Optional[int] = Field(index=True)
    
    title_en: Optional[str] = None
    title_ja: Optional[str] = None
    abstract_en: Optional[str] = None
    abstract_ja: Optional[str] = None
    
    authors: Optional[str] = None
    citation: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[int] = None
    doi: Optional[str] = None

    # LLM 判定関連
    gpt_reason: Optional[str] = None
    condition_list_gpt: Optional[str] = None
    condition_list_gemini: Optional[str] = None
    
    age_focus_gpt: Optional[str] = None
    direction_gpt: Optional[int] = None
    apathy_centrality_gpt: Optional[str] = None
    judgement_gpt: Optional[str] = None
    
    age_focus_gemini: Optional[str] = None
    direction_gemini: Optional[int] = None
    apathy_centrality_gemini: Optional[str] = None
    judgement_gemini: Optional[str] = None

    # 二次スクリーニング用要約
    fulltext_summary_ja: Optional[str] = None

    group_no: int = Field(default=1)

    # 最終確定結果（ペアすり合わせ後）
    final_decision: Optional[int] = None  # 0=除外,1=採用,2=保留

    final_cat_physical: bool = Field(default=False)
    final_cat_brain: bool = Field(default=False)
    final_cat_psycho: bool = Field(default=False)
    final_cat_drug: bool = Field(default=False)

    finalized_by: Optional[int] = Field(default=None, foreign_key="user.id")
    finalized_at: Optional[str] = None

class ScreeningDecision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    article_id: int = Field(foreign_key="article.id")
    
    decision: Optional[int] = None  # 0,1,2
    comment: Optional[str] = None
    
    flag_cause: bool = Field(default=False)
    flag_treatment: bool = Field(default=False)
    
    # カテゴリー分類
    cat_physical: bool = Field(default=False)      # ①身体的要因
    cat_brain: bool = Field(default=False)         # ②脳器質的要因
    cat_psycho: bool = Field(default=False)        # ③心理・環境要因
    cat_drug: bool = Field(default=False)          # ④薬剤 ★追加
    
    created_at: Optional[str] = None

# ==========================================
# 尺度スクリーニング用
# ==========================================
class ScaleArticle(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pmid: Optional[int] = Field(index=True)

    title_en: Optional[str] = None
    title_ja: Optional[str] = None
    abstract_en: Optional[str] = None
    abstract_ja: Optional[str] = None

    citation: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[int] = None
    
    pubmed_url: Optional[str] = None
    doi: Optional[str] = None

    gemini_judgement: Optional[str] = None
    gemini_summary_ja: Optional[str] = None
    gemini_reason_ja: Optional[str] = None
    gemini_tools: Optional[str] = None
    
    group_no: int = Field(default=1)

    @property
    def abstract(self):
        return self.abstract_en

class ScaleScreeningDecision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    scale_article_id: int = Field(foreign_key="scalearticle.id")
    
    rating: Optional[int] = None  # 0,1,2
    comment: Optional[str] = None
    
    created_at: Optional[str] = None


# ==========================================
# 二次スクリーニング用モデル
# ==========================================
class SecondaryArticle(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pmid: int = Field(index=True, unique=True)

    is_physical: bool = Field(default=False)
    is_brain: bool = Field(default=False)
    is_psycho: bool = Field(default=False)
    is_drug: bool = Field(default=False)

    pdf_exists: bool = Field(default=False)

    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SecondaryAutoExtraction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pmid: int = Field(index=True, unique=True)

    auto_citation: Optional[str] = None
    auto_apathy_terms: Optional[str] = None
    auto_target_condition: Optional[str] = None
    auto_population_N: Optional[str] = None
    auto_prevalence: Optional[str] = None
    auto_intervention: Optional[str] = None
    auto_confidence: Optional[str] = None
    auto_needs_review: Optional[bool] = Field(default=False)

    updated_at: Optional[str] = None


class SecondaryReview(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pmid: int = Field(index=True)
    group: str = Field(index=True)
    reviewer_id: int = Field(foreign_key="user.id")

    decision: Optional[str] = Field(default="pending")  # include/exclude/pending

    final_citation: Optional[str] = None
    final_apathy_terms: Optional[str] = None
    final_target_condition: Optional[str] = None
    final_population_n: Optional[str] = None
    final_prevalence: Optional[str] = None
    final_intervention: Optional[str] = None
    comment: Optional[str] = None

    updated_at: Optional[str] = None

    class Config:
        # unique constraint not enforced here; handled via upsert logic in app
        arbitrary_types_allowed = True