from typing import Optional, List
from pathlib import Path
import csv
import io

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy import func

from starlette.middleware.sessions import SessionMiddleware

from passlib.context import CryptContext
from passlib.exc import UnknownHashError

from .models import (
    Article,
    ScreeningDecision,
    User,
    AppConfig,
    ScaleArticle,
    ScaleScreeningDecision,
)


# =========================================================
# 基本設定
# =========================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "apathy_screening.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

N_GROUPS = 4  # グループ数

engine = create_engine(DATABASE_URL, echo=False)
SQLModel.metadata.create_all(engine)

TEMPLATE_DIR = BASE_DIR / "templates"

app = FastAPI()
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.add_middleware(SessionMiddleware, secret_key="very-secret-key-for-apathy-app")

# パスワードハッシュ（過去の sha256_crypt にも一応対応）
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "sha256_crypt"],
    deprecated="auto",
)


# =========================================================
# ヘルパー
# =========================================================
def get_current_user(request: Request) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with Session(engine) as session:
        return session.exec(select(User).where(User.id == user_id)).first()


def get_year_min(session: Session) -> Optional[int]:
    """
    AppConfig から year_min を取得（なければ 2015 で作成）
    """
    cfg = session.get(AppConfig, 1)
    if cfg is None:
        cfg = AppConfig(id=1, year_min=2015)
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg.year_min


def set_year_min(session: Session, year_min: Optional[int]):
    cfg = session.get(AppConfig, 1)
    if cfg is None:
        cfg = AppConfig(id=1, year_min=year_min)
        session.add(cfg)
    else:
        cfg.year_min = year_min
    session.commit()


def ensure_default_users():
    """
    ユーザーテーブルが空のときだけデフォルトユーザーを作成
    """
    with Session(engine) as session:
        count = session.exec(select(func.count(User.id))).one()
        if count and count > 0:
            return

        users = [
            ("user1", "password1", 1),
            ("user2", "password2", 1),
            ("user3", "password3", 2),
            ("user4", "password4", 2),
            ("user5", "password5", 3),
            ("user6", "password6", 3),
            ("user7", "password7", 4),
            ("user8", "password8", 4),
        ]

        for uname, pw, grp in users:
            u = User(
                username=uname,
                password_hash=pwd_context.hash(pw),
                group_no=grp,
            )
            session.add(u)

        session.commit()


@app.on_event("startup")
def on_startup():
    ensure_default_users()


def get_group_article_ids(
    session: Session,
    year_min: Optional[int],
    user_group_no: int,
) -> List[int]:
    """
    ユーザーの group_no に対応する Article.id のリストを返す。

    - まず全件を取得し、year_min でフィルタ
    - もし year_min フィルタ後に 0 件なら、「とりあえず全件」を使う
    - 著者名（なければ pmid）でソートして N_GROUPS 個に均等分割
    """
    # まず全件取得
    all_rows = list(session.exec(select(Article.id, Article.authors, Article.pmid, Article.year)))

    if not all_rows:
        return []

    # year_min でフィルタ（year が None のものは除外）
    rows = all_rows
    if year_min is not None:
        filtered = [r for r in all_rows if (r[3] is not None and r[3] >= year_min)]
        # フィルタ後に 1 件以上あればそれを採用、0 件なら year_min を無視して全件
        if filtered:
            rows = filtered

    # Authors（なければ pmid）でソート
    rows.sort(key=lambda r: (r[1] or "", r[2] or 0))

    n = len(rows)
    if n == 0:
        return []

    id_list: List[int] = []
    for i, row in enumerate(rows):
        aid = row[0]
        g = (i * N_GROUPS) // n + 1  # 1〜N_GROUPS に均等割り
        if g == user_group_no:
            id_list.append(aid)

    return id_list


def get_group_scale_article_ids(
    session: Session,
    user_group_no: int,
) -> List[int]:
    """
    ログインユーザーの group_no に対応する ScaleArticle.id のリストを返す。
    """
    # まず group_no カラムを信用して探す
    rows = session.exec(
        select(ScaleArticle.id)
        .where(ScaleArticle.group_no == user_group_no)
        .order_by(ScaleArticle.id)
    ).all()

    ids: List[int] = [int(r) for r in rows] if rows else []

    if ids:
        return ids

    # フォールバック：pmid で全 ScaleArticle を均等割り
    all_rows = list(
        session.exec(select(ScaleArticle.id, ScaleArticle.pmid))
    )
    if not all_rows:
        return []

    # pmid でソート（無い場合は 0）
    all_rows.sort(key=lambda r: (r[1] or 0))

    n = len(all_rows)
    id_list: List[int] = []
    for i, row in enumerate(all_rows):
        aid = row[0]
        g = (i * N_GROUPS) // n + 1  # 1〜N_GROUPS
        if g == user_group_no:
            id_list.append(aid)

    return id_list


# =========================================================
# トップ / データベース
# =========================================================
@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "username": user.username if user else None,
            "group_no": user.group_no if user else None,
            "current_page": "home",
        },
    )


@app.get("/database", response_class=HTMLResponse)
def database(request: Request):
    user = get_current_user(request)
    with Session(engine) as session:
        articles = session.exec(select(Article).order_by(Article.id)).all()

    return templates.TemplateResponse(
        "database.html",
        {
            "request": request,
            "articles": articles,
            "username": user.username if user else None,
            "group_no": user.group_no if user else None,
            "current_page": "database",
        },
    )


# =========================================================
# 設定画面（year_min）
# =========================================================
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    is_admin = (user.username == "user1")

    with Session(engine) as session:
        year_min = get_year_min(session)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "username": user.username,
            "group_no": user.group_no,
            "year_min": year_min,
            "is_admin": is_admin,
            "current_page": "settings",
        },
    )


@app.post("/settings", response_class=HTMLResponse)
def settings_submit(
    request: Request,
    year_min: Optional[int] = Form(None),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if user.username != "user1":
        # 管理者以外は year_min を変更させない
        return RedirectResponse(url="/settings", status_code=303)

    with Session(engine) as session:
        set_year_min(session, year_min if year_min else None)

    return RedirectResponse(url="/settings", status_code=303)


# =========================================================
# ログイン / ログアウト / パスワード変更
# =========================================================
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = Query("screen")):
    """
    next: "screen" または "scale"
    """
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "next": next,
            "current_page": "login",
        },
    )


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("screen"),
):
    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == username)
        ).first()

        if not user:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "ユーザー名またはパスワードが違います",
                    "next": next,
                },
            )

        try:
            ok = pwd_context.verify(password, user.password_hash)
        except UnknownHashError:
            ok = False

        if not ok:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "ユーザー名またはパスワードが違います",
                    "next": next,
                },
            )

        request.session["user_id"] = user.id

    redirect_url = "/scale_screen" if next == "scale" else "/screen"
    return RedirectResponse(url=redirect_url, status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/change_password", response_class=HTMLResponse)
def change_password_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    return templates.TemplateResponse(
        "change_password.html",
        {
            "request": request,
            "error": None,
            "success": None,
            "username": user.username,
            "group_no": user.group_no,
            "current_page": "change_password",
        },
    )


@app.post("/change_password", response_class=HTMLResponse)
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    if new_password != new_password_confirm:
        return templates.TemplateResponse(
            "change_password.html",
            {
                "request": request,
                "error": "新しいパスワードが一致しません。",
                "success": None,
                "username": user.username,
                "group_no": user.group_no,
                "current_page": "change_password",
            },
        )

    if len(new_password) < 6:
        return templates.TemplateResponse(
            "change_password.html",
            {
                "request": request,
                "error": "新しいパスワードは6文字以上にしてください。",
                "success": None,
                "username": user.username,
                "group_no": user.group_no,
                "current_page": "change_password",
            },
        )

    with Session(engine) as session:
        db_user = session.exec(
            select(User).where(User.id == user.id)
        ).first()
        if not db_user or not pwd_context.verify(
            current_password, db_user.password_hash
        ):
            return templates.TemplateResponse(
                "change_password.html",
                {
                    "request": request,
                    "error": "現在のパスワードが違います。",
                    "success": None,
                    "username": user.username,
                    "group_no": user.group_no,
                    "current_page": "change_password",
                },
            )

        db_user.password_hash = pwd_context.hash(new_password)
        session.add(db_user)
        session.commit()

    return templates.TemplateResponse(
        "change_password.html",
        {
            "request": request,
            "error": None,
            "success": "パスワードを変更しました。",
            "username": user.username,
            "group_no": user.group_no,
            "current_page": "change_password",
        },
    )


# ---------------------------------------------------------
# 一次スクリーニング画面（GET）
# ---------------------------------------------------------
@app.get("/screen", response_class=HTMLResponse, name="screen_page")
def screen_page(
    request: Request,
    group_no: int = Query(None),
    article_index: int = Query(None),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user.id
    group_no = user.group_no if group_no is None else group_no

    with Session(engine) as session:
        year_min = get_year_min(session)
        id_list = get_group_article_ids(session, year_min, group_no)
        total = len(id_list)

        # 進捗（自分が判定した件数）
        if id_list:
            rated = session.exec(
                select(func.count(ScreeningDecision.id)).where(
                    (ScreeningDecision.user_id == user_id)
                    & (ScreeningDecision.article_id.in_(id_list))
                    & (ScreeningDecision.decision.is_not(None))
                )
            ).one()
        else:
            rated = 0

        direction_memo = None

        if not id_list:
            return templates.TemplateResponse(
                "screen.html",
                {
                    "request": request,
                    "group_no": group_no,
                    "username": user.username,
                    "article": None,
                    "direction_memo": direction_memo,
                    "progress_done": 0,
                    "progress_total": 0,
                    "current_index": None,
                    "current_page": "screen",
                },
            )

        article = None
        current_index: Optional[int] = None

        if article_index is not None:
            idx = max(1, min(article_index, total))
            article_id = id_list[idx - 1]
            article = session.get(Article, article_id)
            current_index = idx
        else:
            decided_ids = session.exec(
                select(ScreeningDecision.article_id)
                .where(ScreeningDecision.user_id == user_id)
            ).all()
            decided_set = set(decided_ids) if decided_ids else set()

            for i, aid in enumerate(id_list):
                if aid not in decided_set:
                    article = session.get(Article, aid)
                    current_index = i + 1
                    break

            if article is None:
                article_id = id_list[-1]
                article = session.get(Article, article_id)
                current_index = total

        prev_decision: Optional[int] = None
        prev_comment: str = ""
        prev_flag_cause: bool = False
        prev_flag_treatment: bool = False

        if article is not None:
            existing = session.exec(
                select(ScreeningDecision).where(
                    (ScreeningDecision.user_id == user_id)
                    & (ScreeningDecision.article_id == article.id)
                )
            ).first()
            if existing:
                prev_decision = existing.decision
                prev_comment = existing.comment or ""
                prev_flag_cause = bool(getattr(existing, "flag_cause", False))
                prev_flag_treatment = bool(
                    getattr(existing, "flag_treatment", False)
                )

    return templates.TemplateResponse(
        "screen.html",
        {
            "request": request,
            "group_no": group_no,
            "username": user.username,
            "article": article,
            "direction_memo": direction_memo,
            "progress_done": rated,
            "progress_total": total,
            "current_index": current_index,
            "current_page": "screen",
            "prev_decision": prev_decision,
            "prev_comment": prev_comment,
            "prev_flag_cause": prev_flag_cause,
            "prev_flag_treatment": prev_flag_treatment,
        },
    )


# =========================================================
# 病態 一次スクリーニング保存 /screen (POST)
# =========================================================
@app.post("/screen", response_class=HTMLResponse, name="submit_screen")
def submit_screen(
    request: Request,
    article_id: int = Form(...),
    decision: Optional[int] = Form(None), # ★修正: Optional[int] = Form(None) に変更
    flag_cause: int = Form(0),
    flag_treatment: int = Form(0),
    nav: str = Form("next"),
    jump_index: str | None = Form(None),
    comment: str = Form(""),
):
    """
    病態スクリーニングの結果を保存してから、
    「前へ」「次へ」「ジャンプ」のいずれかにリダイレクトする。
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user.id
    group_no = user.group_no or 1

    with Session(engine) as session:
        # 担当論文一覧
        year_min = get_year_min(session)
        stmt_ids = (
            select(Article.id)
            .where(
                Article.group_no == group_no,
                Article.year >= year_min,
            )
            .order_by(Article.id)
        )
        id_list = session.exec(stmt_ids).all()
        total = len(id_list)

        # 今の論文が何番目か
        try:
            current_index = id_list.index(article_id) + 1
        except ValueError:
            current_index = 1

        # 既存レコードを検索
        existing = session.exec(
            select(ScreeningDecision).where(
                (ScreeningDecision.user_id == user_id)
                & (ScreeningDecision.article_id == article_id)
            )
        ).first()

        # decisionがNoneの場合（ラジオボタン未選択で戻る場合など）は保存しない、
        # あるいは既存データを維持する
        if existing:
            if decision is not None:
                existing.decision = decision
            
            # コメントなどは常に更新（空文字でも）
            existing.comment = comment or ""
            existing.flag_cause = bool(flag_cause)
            existing.flag_treatment = bool(flag_treatment)
            session.add(existing)
        else:
            # 新規で、かつdecisionがある場合のみ保存（あるいは決定なしでも保存したい場合は条件外す）
            # ここでは決定がされたときのみレコードを作る
            if decision is not None:
                sd = ScreeningDecision(
                    user_id=user_id,
                    article_id=article_id,
                    decision=decision,
                    comment=comment or "",
                    flag_cause=bool(flag_cause),
                    flag_treatment=bool(flag_treatment),
                )
                session.add(sd)

        session.commit()

    # --------- ナビゲーション決定 ---------
    if nav == "prev":
        target = max(1, current_index - 1)
        return RedirectResponse(
            url=f"/screen?article_index={target}", status_code=303
        )

    if nav == "jump":
        if not jump_index:
            target = current_index
        else:
            try:
                ji = int(jump_index)
            except ValueError:
                ji = current_index

            if total > 0:
                target = max(1, min(ji, total))
            else:
                target = 1

        return RedirectResponse(
            url=f"/screen?article_index={target}", status_code=303
        )

    # デフォルトは「次へ」
    if total > 0:
        target = min(current_index + 1, total)
        return RedirectResponse(
            url=f"/screen?article_index={target}", status_code=303
        )
    else:
        return RedirectResponse(url="/screen", status_code=303)


# =========================================================
# 病態 個人進捗 /my_index
# =========================================================
@app.get("/my_index", response_class=HTMLResponse, name="disease_progress_my")
def my_index(request: Request):
    """
    個人進捗（病態スクリーニング）
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    request.state.user = user
    user_id = user.id
    group_no = user.group_no

    with Session(engine) as session:
        year_min = get_year_min(session)
        id_list = get_group_article_ids(session, year_min, group_no)

        # 進捗計算
        if id_list:
            done_count = session.exec(
                select(func.count(ScreeningDecision.id)).where(
                    (ScreeningDecision.user_id == user_id)
                    & (ScreeningDecision.article_id.in_(id_list))
                    & (ScreeningDecision.decision.is_not(None))
                )
            ).one()
        else:
            done_count = 0

        total = len(id_list)
        progress_pct = int(done_count * 100 / total) if total else 0

        # 自分の担当記事 + 自分の決定（LEFT JOIN）
        stmt = (
            select(Article, ScreeningDecision)
            .join(
                ScreeningDecision,
                (ScreeningDecision.article_id == Article.id)
                & (ScreeningDecision.user_id == user_id),
                isouter=True,
            )
            .where(Article.id.in_(id_list))
            .order_by(Article.id)
        )
        rows = session.exec(stmt).all()

    return templates.TemplateResponse(
        "my_index.html",
        {
            "request": request,
            "rows": rows,
            "username": user.username,
            "group_no": group_no,
            "current_page": "my_index",
            "progress_done": done_count,
            "progress_total": total,
            "progress_pct": progress_pct,
        },
    )


# =========================================================
# 尺度 一次スクリーニング /scale_screen
# =========================================================
@app.get("/scale_screen", response_class=HTMLResponse, name="scale_screen_page")
def scale_screen_page(
    request: Request,
    article_index: int = Query(1, ge=1),
    group_no: Optional[int] = Query(None),
):
    """
    評価尺度用の一次スクリーニング画面。
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login?next=scale", status_code=303)

    user_id = user.id
    group_no = user.group_no

    with Session(engine) as session:
        # このユーザーが担当する尺度論文（フォールバック付き）
        id_list = get_group_scale_article_ids(session, group_no)
        total = len(id_list)

        # 個人進捗（尺度）
        if id_list:
            my_done = session.exec(
                select(func.count(ScaleScreeningDecision.id)).where(
                    (ScaleScreeningDecision.user_id == user_id)
                    & (ScaleScreeningDecision.scale_article_id.in_(id_list))
                    & (ScaleScreeningDecision.rating.is_not(None))
                )
            ).one()
        else:
            my_done = 0

        # 全体進捗（尺度）
        total_all = session.exec(select(func.count(ScaleArticle.id))).one()
        all_done = session.exec(
            select(func.count(func.distinct(ScaleScreeningDecision.scale_article_id))).where(
                ScaleScreeningDecision.rating.is_not(None)
            )
        ).one()

        article = None
        current_index: Optional[int] = None

        if not id_list:
            return templates.TemplateResponse(
                "scale_screen.html",
                {
                    "request": request,
                    "username": user.username,
                    "group_no": group_no,
                    "article": None,
                    "progress_done": my_done,
                    "progress_total": total,
                    "current_index": None,
                    "scale_all_done": all_done,
                    "scale_total_all": total_all,
                    "my_rating": None,
                    "my_comment": "",
                    "current_page": "scale_screen",
                },
            )

        if article_index is not None:
            idx = max(1, min(article_index, total))
            article_id = id_list[idx - 1]
            article = session.get(ScaleArticle, article_id)
            current_index = idx
        else:
            decided_ids = session.exec(
                select(ScaleScreeningDecision.scale_article_id)
                .where(ScaleScreeningDecision.user_id == user_id)
            ).all()
            decided_set = set(decided_ids) if decided_ids else set()

            for i, aid in enumerate(id_list):
                if aid not in decided_set:
                    article = session.get(ScaleArticle, aid)
                    current_index = i + 1
                    break

            if article is None:
                article_id = id_list[-1]
                article = session.get(ScaleArticle, article_id)
                current_index = total

        my_rating = None
        my_comment = ""
        if article is not None:
            existing = session.exec(
                select(ScaleScreeningDecision).where(
                    (ScaleScreeningDecision.user_id == user_id)
                    & (ScaleScreeningDecision.scale_article_id == article.id)
                )
            ).first()
            if existing:
                my_rating = existing.rating
                my_comment = existing.comment or ""

    return templates.TemplateResponse(
        "scale_screen.html",
        {
            "request": request,
            "username": user.username,
            "group_no": group_no,
            "article": article,
            "progress_done": my_done,
            "progress_total": total,
            "current_index": current_index,
            "scale_all_done": all_done,
            "scale_total_all": total_all,
            "my_rating": my_rating,
            "my_comment": my_comment,
            "current_page": "scale_screen",
        },
    )


# =========================================================
# 尺度 一次スクリーニング保存 /scale_screen (POST)
# =========================================================
@app.post("/scale_screen", response_class=HTMLResponse, name="submit_scale_screen")
def submit_scale_screen(
    request: Request,
    article_id: int = Form(...),
    decision: Optional[int] = Form(None),   # ★修正: Optional[int] = Form(None)
    comment: str = Form(""),
    nav: str = Form("next"),
    jump_index: Optional[str] = Form(None),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login?next=scale", status_code=303)

    user_id = user.id
    group_no = user.group_no

    with Session(engine) as session:
        # このユーザーの担当論文リスト
        id_list = get_group_scale_article_ids(session, group_no)
        total = len(id_list)

        # いまの article が何番目か
        try:
            current_index = id_list.index(article_id) + 1
        except ValueError:
            current_index = 1

        existing = session.exec(
            select(ScaleScreeningDecision).where(
                (ScaleScreeningDecision.user_id == user_id)
                & (ScaleScreeningDecision.scale_article_id == article_id)
            )
        ).first()

        # decisionがNoneの場合のハンドリング
        if existing:
            if decision is not None:
                existing.rating = decision
            if comment is not None:
                existing.comment = comment
            session.add(existing)
        else:
            if decision is not None:
                sd = ScaleScreeningDecision(
                    user_id=user_id,
                    scale_article_id=article_id,
                    rating=decision,
                    comment=comment or "",
                )
                session.add(sd)

        session.commit()

    # ナビゲーション
    if nav == "prev":
        target = max(1, current_index - 1)
        return RedirectResponse(
            url=f"/scale_screen?article_index={target}", status_code=303
        )

    if nav == "jump":
        if not jump_index:
            target = current_index
        else:
            try:
                ji = int(jump_index)
            except ValueError:
                ji = current_index

            if total > 0:
                target = max(1, min(ji, total))
            else:
                target = 1

        return RedirectResponse(
            url=f"/scale_screen?article_index={target}", status_code=303
        )

    # next
    if total > 0:
        target = min(current_index + 1, total)
        return RedirectResponse(
            url=f"/scale_screen?article_index={target}", status_code=303
        )
    else:
        return RedirectResponse(url="/scale_screen", status_code=303)


# =========================================================
# 尺度 個人進捗 /scale_my_index
# =========================================================
@app.get("/scale_my_index", response_class=HTMLResponse, name="scale_progress_my")
def scale_my_index(request: Request):
    """
    個人進捗（尺度スクリーニング）
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login?next=scale", status_code=303)

    user_id = user.id
    group_no = user.group_no

    with Session(engine) as session:
        # 担当する尺度論文の ID リスト
        id_list = get_group_scale_article_ids(session, group_no)
        total = len(id_list)

        # 自分の評価済み件数
        if id_list:
            done_count = session.exec(
                select(func.count(ScaleScreeningDecision.id)).where(
                    (ScaleScreeningDecision.user_id == user_id)
                    & (ScaleScreeningDecision.scale_article_id.in_(id_list))
                    & (ScaleScreeningDecision.rating.is_not(None))
                )
            ).one()
        else:
            done_count = 0

        progress_pct = int(done_count * 100 / total) if total else 0

        # 自分担当の記事 + 自分の評価（LEFT JOIN）
        stmt = (
            select(ScaleArticle, ScaleScreeningDecision)
            .join(
                ScaleScreeningDecision,
                (ScaleScreeningDecision.scale_article_id == ScaleArticle.id)
                & (ScaleScreeningDecision.user_id == user_id),
                isouter=True,
            )
            .where(ScaleArticle.id.in_(id_list))
            .order_by(ScaleArticle.id)
        )
        rows = session.exec(stmt).all()

    return templates.TemplateResponse(
        "scale_my_index.html",
        {
            "request": request,
            "rows": rows,
            "username": user.username,
            "group_no": group_no,
            "current_page": "scale_my_index",
            "progress_done": done_count,
            "progress_total": total,
            "progress_pct": progress_pct,
        },
    )


# =========================================================
# 共通 全体進捗ダッシュボード /dashboard
# =========================================================
@app.get("/dashboard", response_class=HTMLResponse, name="dashboard")
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        year_min = get_year_min(session)
        users: List[User] = session.exec(select(User)).all()

        rows = []

        # 全体集計
        overall_dis_total = 0
        overall_dis_rated = 0
        overall_scale_total = 0
        overall_scale_rated = 0

        for u in users:
            # 1) 病態スクリーニング
            dis_id_list = get_group_article_ids(session, year_min, u.group_no)
            dis_total = len(dis_id_list)

            if dis_id_list:
                dis_rated = session.exec(
                    select(func.count(ScreeningDecision.id)).where(
                        (ScreeningDecision.user_id == u.id)
                        & (ScreeningDecision.article_id.in_(dis_id_list))
                        & (ScreeningDecision.decision.is_not(None))
                    )
                ).one()
            else:
                dis_rated = 0

            dis_pct = (dis_rated / dis_total * 100.0) if dis_total > 0 else 0.0

            overall_dis_total += dis_total
            overall_dis_rated += dis_rated

            # 2) 尺度スクリーニング
            scale_id_list = session.exec(
                select(ScaleArticle.id)
                .where(ScaleArticle.group_no == u.group_no)
                .order_by(ScaleArticle.id)
            ).all()
            scale_total = len(scale_id_list)

            if scale_id_list:
                scale_rated = session.exec(
                    select(func.count(ScaleScreeningDecision.id)).where(
                        (ScaleScreeningDecision.user_id == u.id)
                        & (ScaleScreeningDecision.scale_article_id.in_(scale_id_list))
                        & (ScaleScreeningDecision.rating.is_not(None))
                    )
                ).one()
            else:
                scale_rated = 0

            scale_pct = (scale_rated / scale_total * 100.0) if scale_total > 0 else 0.0

            overall_scale_total += scale_total
            overall_scale_rated += scale_rated

            rows.append(
                {
                    "username": u.username,
                    "group_no": u.group_no,
                    "dis_rated": dis_rated,
                    "dis_total": dis_total,
                    "dis_pct": dis_pct,
                    "scale_rated": scale_rated,
                    "scale_total": scale_total,
                    "scale_pct": scale_pct,
                }
            )

        overall_dis_pct = (
            overall_dis_rated / overall_dis_total * 100.0
            if overall_dis_total > 0
            else 0.0
        )
        overall_scale_pct = (
            overall_scale_rated / overall_scale_total * 100.0
            if overall_scale_total > 0
            else 0.0
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "rows": rows,
            "username": user.username,
            "group_no": user.group_no,
            "current_page": "dashboard",
            "overall_dis_total": overall_dis_total,
            "overall_dis_rated": overall_dis_rated,
            "overall_dis_pct": overall_dis_pct,
            "overall_scale_total": overall_scale_total,
            "overall_scale_rated": overall_scale_rated,
            "overall_scale_pct": overall_scale_pct,
        },
    )

# =========================================================
# 結果 CSV エクスポート
# =========================================================
@app.get("/export_disease", response_class=StreamingResponse, name="download_disease")
@app.get("/export", response_class=StreamingResponse)
def export_disease_csv(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with Session(engine) as session:
        stmt = (
            select(ScreeningDecision, Article, User)
            .join(Article, Article.id == ScreeningDecision.article_id)
            .join(User, User.id == ScreeningDecision.user_id)
            .order_by(Article.id, User.username)
        )
        rows = session.exec(stmt).all()

    output = io.StringIO()
    output.write("\ufeff")

    writer = csv.writer(output)
    writer.writerow(
        [
            "article_id",
            "pmid",
            "title_en",
            "title_ja",
            "username",
            "decision",
            "comment",
            "flag_cause",
            "flag_treatment",
            "direction_gpt",
            "direction_gemini",
            "condition_list_gpt",
            "condition_list_gemini",
            "year",
        ]
    )

    for sd, art, usr in rows:
        writer.writerow(
            [
                art.id,
                art.pmid,
                art.title_en or "",
                art.title_ja or "",
                usr.username,
                sd.decision,
                sd.comment or "",
                1 if getattr(sd, "flag_cause", False) else 0,
                1 if getattr(sd, "flag_treatment", False) else 0,
                art.direction_gpt if art.direction_gpt is not None else "",
                art.direction_gemini if art.direction_gemini is not None else "",
                art.condition_list_gpt or "",
                art.condition_list_gemini or "",
                art.year if art.year is not None else "",
            ]
        )

    output.seek(0)
    filename = "apathy_disease_screening_results.csv"

    return StreamingResponse(
    output,
    media_type="text/csv",
    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
)


@app.get("/export_scale", response_class=StreamingResponse, name="download_scale")
def export_scale_csv(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with Session(engine) as session:
        stmt = (
            select(ScaleScreeningDecision, ScaleArticle, User)
            .join(ScaleArticle, ScaleArticle.id == ScaleScreeningDecision.scale_article_id)
            .join(User, User.id == ScaleScreeningDecision.user_id)
            .order_by(ScaleArticle.id, User.username)
        )
        rows = session.exec(stmt).all()

    output = io.StringIO()
    output.write("\ufeff")

    writer = csv.writer(output)
    writer.writerow(
        [
            "scale_article_id",
            "pmid",
            "title_en",
            "title_ja",
            "username",
            "rating",
            "comment",
            "gemini_judgement",
            "gemini_summary_ja",
            "gemini_reason_ja",
            "gemini_tools",
            "year",
        ]
    )

    for sd, art, usr in rows:
        writer.writerow(
            [
                art.id,
                art.pmid,
                art.title_en or "",
                art.title_ja or "",
                usr.username,
                sd.rating or "",
                sd.comment or "",
                art.gemini_judgement or "",
                art.gemini_summary_ja or "",
                art.gemini_reason_ja or "",
                art.gemini_tools or "",
                art.year if art.year is not None else "",
            ]
        )

    output.seek(0)
    filename = "apathy_scale_screening_results.csv"

    return StreamingResponse(
    output,
    media_type="text/csv",
    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
)