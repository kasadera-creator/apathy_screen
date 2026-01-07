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

from .models import Article, ScreeningDecision, User, AppConfig

# ---------------------------------------------------------
# 基本設定
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "apathy_screening.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

N_GROUPS = 4  # グループ数

engine = create_engine(DATABASE_URL, echo=False)

# テーブル作成（存在しなければ）
SQLModel.metadata.create_all(engine)

TEMPLATE_DIR = BASE_DIR / "templates"

app = FastAPI()

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.add_middleware(SessionMiddleware, secret_key="very-secret-key-for-apathy-app")

# パスワードハッシュ：過去の sha256_crypt も一応読めるようにしておく
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "sha256_crypt"],
    deprecated="auto",
)


# ---------------------------------------------------------
# ヘルパー：現在ログイン中ユーザー
# ---------------------------------------------------------
def get_current_user(request: Request) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with Session(engine) as session:
        return session.exec(select(User).where(User.id == user_id)).first()


# ---------------------------------------------------------
# ヘルパー：AppConfig（year_min）の取得・更新
# ---------------------------------------------------------
def get_year_min(session: Session) -> Optional[int]:
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


# ---------------------------------------------------------
# ユーザーの初期投入（空のときだけ）
# ---------------------------------------------------------
def ensure_default_users():
    with Session(engine) as session:
        count = session.exec(select(func.count(User.id))).one()
        if count and count > 0:
            # 既にユーザーが存在する場合は何もしない
            return

        # 初期ユーザーとパスワード
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
    # ユーザーテーブルが空のときだけデフォルトユーザーを作成
    ensure_default_users()


# ---------------------------------------------------------
# 動的グループ割り当てロジック
#   - year_min で絞り込んだ Article を Authors / PMID でソート
#   - それを均等に N_GROUPS へ割振り
# ---------------------------------------------------------
def get_group_article_ids(
    session: Session,
    year_min: Optional[int],
    user_group_no: int,
) -> List[int]:
    stmt = select(Article.id, Article.authors, Article.pmid, Article.year)
    if year_min is not None:
        stmt = stmt.where(Article.year >= year_min)

    rows = list(session.exec(stmt))
    # Authors（なければ pmid）でソート
    rows.sort(key=lambda r: (r[1] or "", r[2] or 0))

    n = len(rows)
    if n == 0:
        return []

    id_list: List[int] = []
    for i, row in enumerate(rows):
        aid = row[0]
        g = (i * N_GROUPS) // n + 1  # 1〜N_GROUPS
        if g == user_group_no:
            id_list.append(aid)
    return id_list


# ---------------------------------------------------------
# トップ / データベース
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
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


# ---------------------------------------------------------
# 設定画面（year_min）
# ---------------------------------------------------------
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    is_admin = (user.username == "user1")  # ★ ここで管理者判定

    with Session(engine) as session:
        year_min = get_year_min(session)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "username": user.username,
            "group_no": user.group_no,
            "year_min": year_min,
            "is_admin": is_admin,        # ★ テンプレートへ渡す
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

    # ★ 管理者以外は変更させない（URL直叩き対策）
    if user.username != "user1":
        return RedirectResponse(url="/settings", status_code=303)

    with Session(engine) as session:
        set_year_min(session, year_min if year_min else None)

    return RedirectResponse(url="/settings", status_code=303)


# ---------------------------------------------------------
# ログイン / ログアウト
# ---------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None, "current_page": "login"},
    )


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == username)
        ).first()

        if not user:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "ユーザー名またはパスワードが違います"},
            )

        try:
            ok = pwd_context.verify(password, user.password_hash)
        except UnknownHashError:
            ok = False

        if not ok:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "ユーザー名またはパスワードが違います"},
            )

        request.session["user_id"] = user.id

    return RedirectResponse(url="/screen", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------
# パスワード変更
# ---------------------------------------------------------
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
@app.get("/screen", response_class=HTMLResponse)
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


# ---------------------------------------------------------
# 一次スクリーニング保存（POST）
#   nav = prev / jump / next
# ---------------------------------------------------------
@app.post("/screen", response_class=HTMLResponse)
def submit_screen(
    request: Request,
    article_id: int = Form(...),
    decision: Optional[int] = Form(None),
    comment: str = Form(""),
    flag_cause: Optional[str] = Form(None),
    flag_treatment: Optional[str] = Form(None),
    nav: str = Form("next"),
    # ★ 空文字が飛んでくるので str として受け取る
    jump_index: Optional[str] = Form(None),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user.id
    group_no = user.group_no

    fc = bool(flag_cause)
    ft = bool(flag_treatment)

    with Session(engine) as session:
        year_min = get_year_min(session)
        id_list = get_group_article_ids(session, year_min, group_no)
        total = len(id_list)

        # いまの article がリストの何番目か
        try:
            current_index = id_list.index(article_id) + 1
        except ValueError:
            current_index = 1

        # 判定を保存（decision が送られてきたときだけ）
        if decision is not None:
            existing = session.exec(
                select(ScreeningDecision).where(
                    (ScreeningDecision.user_id == user_id)
                    & (ScreeningDecision.article_id == article_id)
                )
            ).first()

            if existing:
                existing.decision = decision
                existing.comment = comment
                if hasattr(existing, "flag_cause"):
                    existing.flag_cause = fc
                if hasattr(existing, "flag_treatment"):
                    existing.flag_treatment = ft
                session.add(existing)
            else:
                sd = ScreeningDecision(
                    user_id=user_id,
                    article_id=article_id,
                    decision=decision,
                    comment=comment,
                )
                if hasattr(sd, "flag_cause"):
                    sd.flag_cause = fc
                if hasattr(sd, "flag_treatment"):
                    sd.flag_treatment = ft
                session.add(sd)

            session.commit()

    # --- ここからナビゲーション処理（DB外） ---

    # １つ前へ
    if nav == "prev":
        target = max(1, current_index - 1)
        return RedirectResponse(
            url=f"/screen?article_index={target}", status_code=303
        )

    # 指定番号へジャンプ
    if nav == "jump":
        if not jump_index:  # None または "" の場合
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

    # 通常は「次へ」
    if total > 0:
        target = min(current_index + 1, total)
        return RedirectResponse(
            url=f"/screen?article_index={target}", status_code=303
        )
    else:
        return RedirectResponse(url="/screen", status_code=303)


# ---------------------------------------------------------
# 全体進捗ダッシュボード
# ---------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    with Session(engine) as session:
        year_min = get_year_min(session)
        users: List[User] = session.exec(select(User)).all()

        rows = []
        for u in users:
            id_list = get_group_article_ids(session, year_min, u.group_no)
            total = len(id_list)
            if id_list:
                rated = session.exec(
                    select(func.count(ScreeningDecision.id)).where(
                        (ScreeningDecision.user_id == u.id)
                        & (ScreeningDecision.article_id.in_(id_list))
                        & (ScreeningDecision.decision.is_not(None))
                    )
                ).one()
            else:
                rated = 0

            pct = (rated / total * 100.0) if total > 0 else 0.0

            rows.append(
                {
                    "username": u.username,
                    "group_no": u.group_no,
                    "rated": rated,
                    "total": total,
                    "pct": pct,
                }
            )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "rows": rows,
            "username": user.username,
            "group_no": user.group_no,
            "current_page": "dashboard",
        },
    )


# ---------------------------------------------------------
# 個人進捗一覧（/my_index）
# ---------------------------------------------------------
@app.get("/my_index", response_class=HTMLResponse)
def my_index(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # テンプレ側が request.state.user を参照しても良いように
    request.state.user = user

    user_id = user.id
    group_no = user.group_no

    with Session(engine) as session:
        year_min = get_year_min(session)

        stmt = (
            select(Article, ScreeningDecision)
            .join(
                ScreeningDecision,
                (ScreeningDecision.article_id == Article.id)
                & (ScreeningDecision.user_id == user_id),
                isouter=True,
            )
            .where(Article.group_no == group_no)
            .where(Article.year >= year_min)
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
        },
    )


# ---------------------------------------------------------
# 結果 CSV/XLSX エクスポート（進捗ボード用）および二次配布用エクスポート
# ---------------------------------------------------------
def _sd_categories(sd: ScreeningDecision):
    cats = []
    if getattr(sd, "cat_physical", False):
        cats.append("physical")
    if getattr(sd, "cat_brain", False):
        cats.append("brain")
    if getattr(sd, "cat_psycho", False):
        cats.append("psycho")
    if getattr(sd, "cat_drug", False):
        cats.append("drug")
    return cats


@app.get("/export", response_class=StreamingResponse)
def export_csv(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    from collections import OrderedDict

    with Session(engine) as session:
        stmt = (
            select(ScreeningDecision, Article, User)
            .join(Article, Article.id == ScreeningDecision.article_id)
            .join(User, User.id == ScreeningDecision.user_id)
            .order_by(Article.id, User.username)
        )
        rows = session.exec(stmt).all()

    # group by article
    articles = OrderedDict()
    for sd, art, usr in rows:
        if art.id not in articles:
            articles[art.id] = {"article": art, "decisions": []}
        articles[art.id]["decisions"].append((sd, usr))

    output = io.StringIO()
    output.write("\ufeff")  # BOM
    writer = csv.writer(output)

    writer.writerow(
        [
            "article_id",
            "pmid",
            "title_en",
            "title_ja",
            "r1_username",
            "r1_decision",
            "r1_category",
            "r1_comment",
            "r2_username",
            "r2_decision",
            "r2_category",
            "r2_comment",
            "final_decision",
            "final_category",
            "decision_mismatch",
            "category_mismatch",
            "finalized_by",
            "finalized_at",
            "year",
            "journal",
            "doi",
        ]
    )

    for art_id, data in articles.items():
        art = data["article"]
        decs = data["decisions"]

        r1 = decs[0] if len(decs) > 0 else (None, None)
        r2 = decs[1] if len(decs) > 1 else (None, None)
        sd1, usr1 = r1
        sd2, usr2 = r2

        r1_dec = sd1.decision if sd1 is not None else ""
        r2_dec = sd2.decision if sd2 is not None else ""

        r1_cats = _sd_categories(sd1) if sd1 is not None else []
        r2_cats = _sd_categories(sd2) if sd2 is not None else []

        # final: prefer stored final in Article; otherwise infer only when r1==r2
        final_dec = getattr(art, "final_decision", None)
        if final_dec is None:
            if sd1 is not None and sd2 is not None and r1_dec == r2_dec:
                final_dec = r1_dec
            else:
                final_dec = ""

        # final categories: prefer Article final_* flags if present
        final_cats = []
        if getattr(art, "final_cat_physical", False):
            final_cats.append("physical")
        if getattr(art, "final_cat_brain", False):
            final_cats.append("brain")
        if getattr(art, "final_cat_psycho", False):
            final_cats.append("psycho")
        if getattr(art, "final_cat_drug", False):
            final_cats.append("drug")
        if not final_cats:
            # fallback: intersection of r1/r2 if both present and equal
            if sd1 is not None and sd2 is not None and set(r1_cats) == set(r2_cats):
                final_cats = r1_cats

        decision_mismatch = False
        if sd1 is not None and sd2 is not None:
            decision_mismatch = (r1_dec != r2_dec)

        category_mismatch = False
        if sd1 is not None and sd2 is not None:
            category_mismatch = (set(r1_cats) != set(r2_cats))

        writer.writerow(
            [
                art.id,
                art.pmid,
                art.title_en or "",
                art.title_ja or "",
                usr1.username if usr1 is not None else "",
                r1_dec,
                "|".join(r1_cats) if r1_cats else "",
                sd1.comment if sd1 is not None else "",
                usr2.username if usr2 is not None else "",
                r2_dec,
                "|".join(r2_cats) if r2_cats else "",
                sd2.comment if sd2 is not None else "",
                final_dec,
                "|".join(final_cats) if final_cats else "",
                1 if decision_mismatch else 0,
                1 if category_mismatch else 0,
                getattr(art, "finalized_by", ""),
                getattr(art, "finalized_at", ""),
                art.year if art.year is not None else "",
                art.journal or "",
                art.doi or "",
            ]
        )

    output.seek(0)
    filename = "apathy_screening_results.csv"

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/secondary", response_class=StreamingResponse)
def export_secondary(request: Request, category: Optional[str] = None, decision: Optional[str] = None, final_only: int = 1, include_unfinal_but_r_any_adopt: int = 0, format: str = "csv"):
    """二次スクリーニング配布用エクスポート
    query params:
      - category: physical|brain|psycho|drug
      - decision: adopt|exclude|hold
      - final_only: 1 (default) or 0
      - include_unfinal_but_r_any_adopt: 1/0
      - format: csv (only csv supported currently)
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    if format != "csv":
        return Response(content="Only csv format supported", status_code=400)

    decision_map = {"exclude": 0, "adopt": 1, "hold": 2}
    target_dec = decision_map.get(decision) if decision is not None else None

    def article_matches(art, sd_list):
        # determine final_dec
        final_dec = getattr(art, "final_decision", None)
        if final_dec is None:
            if len(sd_list) >= 2 and sd_list[0][0].decision == sd_list[1][0].decision:
                final_dec = sd_list[0][0].decision
        # final-only filter
        if final_only and final_dec is None:
            # optionally include when some reviewer adopted/hold
            if include_unfinal_but_r_any_adopt:
                has_adopt = any(sd.decision in (1, 2) for sd, _ in sd_list)
                if not has_adopt:
                    return False
            else:
                return False

        if target_dec is not None and final_dec is not None:
            if final_dec != target_dec:
                return False

        # category filter: check final category flags first, otherwise any reviewer
        if category:
            cat_field = f"final_cat_{category}"
            if getattr(art, cat_field, False):
                return True
            # fallback: any reviewer has the category
            for sd, _ in sd_list:
                if category == "physical" and sd.cat_physical:
                    return True
                if category == "brain" and sd.cat_brain:
                    return True
                if category == "psycho" and sd.cat_psycho:
                    return True
                if category == "drug" and sd.cat_drug:
                    return True
            return False

        return True

    from collections import OrderedDict

    with Session(engine) as session:
        stmt = (
            select(ScreeningDecision, Article, User)
            .join(Article, Article.id == ScreeningDecision.article_id)
            .join(User, User.id == ScreeningDecision.user_id)
            .order_by(Article.id, User.username)
        )
        rows = session.exec(stmt).all()

    articles = OrderedDict()
    for sd, art, usr in rows:
        if art.id not in articles:
            articles[art.id] = {"article": art, "decisions": []}
        articles[art.id]["decisions"].append((sd, usr))

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)

    writer.writerow(["article_id", "pmid", "title_en", "title_ja", "abstract_en", "r1_decision", "r2_decision", "final_decision", "final_category", "pmid_url"])

    for art_id, data in articles.items():
        art = data["article"]
        sd_list = data["decisions"]
        if not article_matches(art, sd_list):
            continue

        r1 = sd_list[0] if len(sd_list) > 0 else (None, None)
        r2 = sd_list[1] if len(sd_list) > 1 else (None, None)
        sd1, usr1 = r1
        sd2, usr2 = r2

        final_dec = getattr(art, "final_decision", None)
        if final_dec is None and sd1 is not None and sd2 is not None and sd1.decision == sd2.decision:
            final_dec = sd1.decision

        final_cats = []
        if getattr(art, "final_cat_physical", False):
            final_cats.append("physical")
        if getattr(art, "final_cat_brain", False):
            final_cats.append("brain")
        if getattr(art, "final_cat_psycho", False):
            final_cats.append("psycho")
        if getattr(art, "final_cat_drug", False):
            final_cats.append("drug")
        if not final_cats and sd1 is not None:
            # fallback to union of reviewers
            final_cats = _sd_categories(sd1)
            if sd2 is not None:
                final_cats = list(set(final_cats) | set(_sd_categories(sd2)))

        pmid_url = f"https://pubmed.ncbi.nlm.nih.gov/{art.pmid}/" if art.pmid else ""

        writer.writerow([
            art.id,
            art.pmid,
            art.title_en or "",
            art.title_ja or "",
            art.abstract_en or "",
            sd1.decision if sd1 is not None else "",
            sd2.decision if sd2 is not None else "",
            final_dec if final_dec is not None else "",
            "|".join(final_cats) if final_cats else "",
            pmid_url,
        ])

    output.seek(0)
    filename = "apathy_secondary_screening.csv"

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
