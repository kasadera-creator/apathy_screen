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
# 結果 CSV エクスポート
# ---------------------------------------------------------
@app.get("/export", response_class=StreamingResponse)
def export_csv(request: Request):
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
    output.write("\ufeff")  # BOM

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
                1 if (getattr(sd, "flag_cause", False)) else 0,
                1 if (getattr(sd, "flag_treatment", False)) else 0,
                art.direction_gpt if art.direction_gpt is not None else "",
                art.direction_gemini if art.direction_gemini is not None else "",
                art.condition_list_gpt or "",
                art.condition_list_gemini or "",
                art.year if art.year is not None else "",
            ]
        )

    output.seek(0)
    filename = "apathy_screening_results.csv"

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
