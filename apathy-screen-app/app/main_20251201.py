from typing import Optional, List, Dict
from pathlib import Path
import csv
import io

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy import func

from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

from .models import Article, ScreeningDecision, User, AppConfig

# ---------------------------------------------------------
# 定数
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "/home/yvofxbku/app/db/apathy_screen.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

N_GROUPS = 5  # グループ数（user1,2 -> G1 / user3,4 -> G2 ... と対応）

engine = create_engine(DATABASE_URL, echo=False)

# 新しいテーブル（AppConfig 等）があればここで自動作成
SQLModel.metadata.create_all(engine)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

direction_memo = {
    1: "アパシー・意欲低下の原因となる病態・状態のリスト作成に関連",
    2: "アパシー・意欲低下の治療法・対応法のリスト作成に関連",
    3: "アパシー・意欲低下以外が主目的だが、関連情報を含む可能性あり",
    4: "アパシー・意欲低下とは無関係、またはごく周辺的な話題",
}

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="very-secret-key-for-apathy-app")


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
def get_or_create_config(session: Session) -> AppConfig:
    cfg = session.get(AppConfig, 1)
    if not cfg:
        cfg = AppConfig(id=1, year_min=1990)
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg


def get_year_min(session: Session) -> Optional[int]:
    cfg = get_or_create_config(session)
    return cfg.year_min


def set_year_min(session: Session, new_year: Optional[int]) -> None:
    cfg = get_or_create_config(session)
    cfg.year_min = new_year
    session.add(cfg)
    session.commit()


# ---------------------------------------------------------
# ヘルパー：ユーザー作成（初回）
# ---------------------------------------------------------
def ensure_default_users():
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
            ("user9", "password9", 5),
            ("user10", "password10", 5),
        ]

        for uname, pw, grp in users:
            u = User(
                username=uname,
                password_hash=pwd_context.hash(pw),
                group_no=grp,
            )
            session.add(u)

        session.commit()


# ---------------------------------------------------------
# 動的グループ割り当てロジック
#   - year_min で絞り込んだ Article を Authors順に並べる
#   - 全体を N_GROUPS に均等割り
#   - 各 user.group_no に対応する article_id リストを返す
# ---------------------------------------------------------
def get_group_article_ids(
    session: Session,
    year_min: Optional[int],
    user_group_no: int,
) -> List[int]:
    # 対象となる全 Article を取得
    stmt = select(Article.id, Article.authors, Article.pmid, Article.year)

    if year_min is not None:
        stmt = stmt.where(Article.year >= year_min)

    rows = list(session.exec(stmt))

    # Authors で sort（なければ pmid）
    rows.sort(key=lambda r: (r[1] or "", r[2] or 0))  # (authors, pmid)

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
# ルート
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/screen")


# ---------------------------------------------------------
# ログイン
# ---------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    ensure_default_users()
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == username)
        ).first()

        if not user or not pwd_context.verify(password, user.password_hash):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "ユーザー名またはパスワードが違います"},
            )

        request.session["user_id"] = user.id

    return RedirectResponse(url="/screen", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ---------------------------------------------------------
# 一次スクリーニング画面（GET）
#   ?article_index= で文献番号ジャンプ
# ---------------------------------------------------------
@app.get("/screen", response_class=HTMLResponse)
def screen_page(request: Request, article_index: Optional[int] = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    user_id = user.id
    group_no = user.group_no

    with Session(engine) as session:
        year_min = get_year_min(session)
        id_list = get_group_article_ids(session, year_min, group_no)
        total = len(id_list)

        # このユーザーがこのグループで評価済みの件数
        if id_list:
            rated = session.exec(
                select(func.count(ScreeningDecision.id))
                .where(ScreeningDecision.user_id == user_id)
                .where(ScreeningDecision.article_id.in_(id_list))
            ).one()
        else:
            rated = 0

        if total == 0:
            return templates.TemplateResponse(
                "done.html",
                {
                    "request": request,
                    "group_no": group_no,
                    "username": user.username,
                    "progress_done": 0,
                    "progress_total": 0,
                    "current_page": "screen",
                },
            )

        # 表示すべき article を決める
        article = None
        current_index: Optional[int] = None

        if article_index is not None:
            # 指定番号にジャンプ
            idx = max(1, min(article_index, total))
            article_id = id_list[idx - 1]
            article = session.get(Article, article_id)
            current_index = idx
        else:
            # 未評価のもののうち最初の1件
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

            # 全部評価済みなら最後の文献を表示（修正用）
            if article is None:
                last_id = id_list[-1]
                article = session.get(Article, last_id)
                current_index = total

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
        },
    )


# ---------------------------------------------------------
# 一次スクリーニング保存（POST）
#   nav = prev / jump / next で戻る・ジャンプ・次へ
# ---------------------------------------------------------
@app.post("/screen", response_class=HTMLResponse)
def submit_screen(
    request: Request,
    article_id: int = Form(...),
    decision: Optional[int] = Form(None),  # ★ここを Optional に変更
    comment: str = Form(""),
    flag_cause: Optional[str] = Form(None),
    flag_treatment: Optional[str] = Form(None),
    nav: str = Form("next"),
    jump_index: str = Form(""),  # ここは前回の修正通り文字列でOK
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    user_id = user.id
    group_no = user.group_no

    fc = bool(flag_cause)
    ft = bool(flag_treatment)

    with Session(engine) as session:
        # まず、nav に関わらず「自分の担当リスト」と「現在の index」を計算
        year_min = get_year_min(session)
        id_list = get_group_article_ids(session, year_min, group_no)
        total = len(id_list)
        current_idx = id_list.index(article_id) + 1 if article_id in id_list else 1

        # decision が送られてきたときだけ保存処理を行う
        if decision is not None:
            stmt = select(ScreeningDecision).where(
                (ScreeningDecision.user_id == user_id)
                & (ScreeningDecision.article_id == article_id)
            )
            existing = session.exec(stmt).first()

            if existing:
                existing.decision = decision
                existing.comment = comment
                existing.flag_cause = fc
                existing.flag_treatment = ft
            else:
                sd = ScreeningDecision(
                    user_id=user_id,
                    article_id=article_id,
                    decision=decision,
                    comment=comment,
                    flag_cause=fc,
                    flag_treatment=ft,
                )
                session.add(sd)

            session.commit()

    # --- ここからナビゲーション処理（DB外） ---
    if nav == "prev":
        target_idx = max(1, current_idx - 1)
        return RedirectResponse(
            url=f"/screen?article_index={target_idx}", status_code=303
        )

    elif nav == "jump":
        # 空欄や不正入力に備えて安全にパース
        try:
            ji = int(jump_index) if jump_index.strip() != "" else current_idx
        except ValueError:
            ji = current_idx
        target_idx = max(1, min(ji, total))
        return RedirectResponse(
            url=f"/screen?article_index={target_idx}", status_code=303
        )

    else:
        # 通常は「保存して次へ」→ 未評価の次の文献へ（/screen 側に任せる）
        return RedirectResponse(url="/screen", status_code=303)


# ---------------------------------------------------------
# ダッシュボード（全ユーザーの進捗）
#   year_min に基づく動的グループを使用
# ---------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with Session(engine) as session:
        year_min = get_year_min(session)
        users: List[User] = session.exec(select(User)).all()

        rows = []
        for u in users:
            id_list = get_group_article_ids(session, year_min, u.group_no)
            total = len(id_list)
            if id_list:
                rated = session.exec(
                    select(func.count(ScreeningDecision.id))
                    .where(ScreeningDecision.user_id == u.id)
                    .where(ScreeningDecision.article_id.in_(id_list))
                ).one()
            else:
                rated = 0
            pct = (rated / total * 100) if total else 0.0
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
# 結果 CSV エクスポート
#   （ここでは全期間の結果を出す例。必要なら year_min で絞ることも可能）
# ---------------------------------------------------------
@app.get("/export", response_class=StreamingResponse)
def export_csv(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with Session(engine) as session:
        # ScreeningDecision, Article, User をまとめて取得
        stmt = (
            select(ScreeningDecision, Article, User)
            .join(Article, Article.id == ScreeningDecision.article_id)
            .join(User, User.id == ScreeningDecision.user_id)
            .order_by(Article.id, User.username)
        )
        rows = session.exec(stmt).all()

    output = io.StringIO()
    output.write("\ufeff")  # ★ UTF-8 BOM を先頭に書く
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
                1 if (sd.flag_cause if hasattr(sd, "flag_cause") else False) else 0,
                1 if (sd.flag_treatment if hasattr(sd, "flag_treatment") else False) else 0,
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
# 年フィルタ設定画面（簡易版）
#   - ここでは例として user1 だけが変更可能な「なんちゃって管理画面」
# ---------------------------------------------------------
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with Session(engine) as session:
        year_min = get_year_min(session)

    is_admin = (user.username == "user1")  # 簡易管理者判定

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
def settings_update(request: Request, year_min: Optional[int] = Form(None)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    if user.username != "user1":
        # 非管理者は変更不可
        return RedirectResponse(url="/settings", status_code=303)

    with Session(engine) as session:
        if year_min is None or year_min <= 0:
            set_year_min(session, None)  # 「全期間」などにしたいとき
        else:
            set_year_min(session, year_min)

    return RedirectResponse(url="/settings", status_code=303)
