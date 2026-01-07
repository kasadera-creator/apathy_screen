from typing import Optional, List
from pathlib import Path
import csv
import io

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from sqlmodel import Session, create_engine, select
from sqlalchemy import func

from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

from .models import Article, ScreeningDecision, User


# ---------------------------------------------------------
# DB 接続設定（プロジェクト直下に apathy_screening.db がある前提）
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "apathy_screening.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DATABASE_URL, echo=False)

# ---------------------------------------------------------
# テンプレート設定（絶対パス）
# ---------------------------------------------------------
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# ---------------------------------------------------------
# パスワードハッシュ設定
# ---------------------------------------------------------
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# ---------------------------------------------------------
# 研究方向コードのメモ（screen.html で使う）
# ---------------------------------------------------------
direction_memo = {
    1: "アパシー・意欲低下の原因となる病態・状態のリスト作成に関連",
    2: "アパシー・意欲低下の治療法・対応法のリスト作成に関連",
    3: "アパシー・意欲低下以外が主目的だが、関連情報を含む可能性あり",
    4: "アパシー・意欲低下とは無関係、またはごく周辺的な話題",
}

# ---------------------------------------------------------
# FastAPI アプリ本体 + セッションミドルウェア
# ---------------------------------------------------------
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="very-secret-key-for-apathy-app")


# ---------------------------------------------------------
# ヘルパー：現在ログイン中の User を取得
# ---------------------------------------------------------
def get_current_user(request: Request) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with Session(engine) as session:
        user = session.exec(select(User).where(User.id == user_id)).first()
        return user


def ensure_default_users():
    """Userテーブルが空なら、user1〜user10 を自動作成する"""
    with Session(engine) as session:
        # 既にユーザーがいれば何もしない
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
# ヘルパー：ユーザーの担当グループで次の未評価 Article を返す
# ---------------------------------------------------------
def get_next_article_for_group(group_no: int, user_id: int) -> Optional[Article]:
    with Session(engine) as session:
        # そのユーザーが既に評価した article_id の集合
        decided_ids = session.exec(
            select(ScreeningDecision.article_id).where(
                ScreeningDecision.user_id == user_id
            )
        ).all()
        decided_ids = set(decided_ids) if decided_ids else set()

        stmt = (
            select(Article)
            .where(Article.group_no == group_no)
            .order_by(Article.id)
        )

        for art in session.exec(stmt):
            if art.id not in decided_ids:
                return art

    return None


# ---------------------------------------------------------
# ルート：ログインしていなければ /login へ
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/screen")


# ---------------------------------------------------------
# ログイン画面（GET）
# ---------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # ここでユーザーがいなければ user1〜user10 を自動作成
    ensure_default_users()

    # login.html では base.html を継承していても username を渡さないので
    # ナビバーは表示されません（base.html の {% if username %} 判定）
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
        },
    )


# ---------------------------------------------------------
# ログイン処理（POST）
# ---------------------------------------------------------
@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == username)
        ).first()

        if not user or not pwd_context.verify(password, user.password_hash):
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "ユーザー名またはパスワードが違います",
                },
            )

        # ログイン成功
        request.session["user_id"] = user.id

    return RedirectResponse(url="/screen", status_code=303)


# ---------------------------------------------------------
# ログアウト
# ---------------------------------------------------------
@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ---------------------------------------------------------
# 一次スクリーニング画面（GET）
# ---------------------------------------------------------
@app.get("/screen", response_class=HTMLResponse)
def screen_page(request: Request, article_index: Optional[int] = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    group_no = user.group_no
    user_id = user.id

    with Session(engine) as session:
        # グループ内の全 Article.id を順番に取得
        id_stmt = (
            select(Article.id)
            .where(Article.group_no == group_no)
            .order_by(Article.id)
        )
        id_list = list(session.exec(id_stmt))
        total = len(id_list)

        # 評価済み件数
        rated = session.exec(
            select(func.count(ScreeningDecision.id))
            .join(Article, Article.id == ScreeningDecision.article_id)
            .where(ScreeningDecision.user_id == user_id)
            .where(Article.group_no == group_no)
        ).one()

        if total == 0:
            # そもそも論文がない場合の保険
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
            # 指定された番号の文献を表示
            idx = max(1, min(article_index, total))
            article_id = id_list[idx - 1]
            article = session.get(Article, article_id)
            current_index = idx
        else:
            # まだ評価していないもののうち最初の1件を探す
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
            # 全件評価済み
            return templates.TemplateResponse(
                "done.html",
                {
                    "request": request,
                    "group_no": group_no,
                    "username": user.username,
                    "progress_done": rated,
                    "progress_total": total,
                    "current_page": "screen",
                },
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
        },
    )


# ---------------------------------------------------------
# 一次スクリーニング結果の保存（POST）
# ---------------------------------------------------------
@app.post("/screen", response_class=HTMLResponse)
def submit_screen(
    request: Request,
    article_id: int = Form(...),
    decision: int = Form(...),  # 0,1,2
    comment: str = Form(""),
    flag_cause: Optional[str] = Form(None),
    flag_treatment: Optional[str] = Form(None),
    nav: str = Form("next"),
    jump_index: Optional[int] = Form(None),
):
        user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    group_no = user.group_no
    user_id = user.id

    fc = bool(flag_cause)
    ft = bool(flag_treatment)

    with Session(engine) as session:
        # まず保存処理
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

        # ナビゲーション用の index 計算
        id_stmt = (
            select(Article.id)
            .where(Article.group_no == group_no)
            .order_by(Article.id)
        )
        id_list = list(session.exec(id_stmt))
        total = len(id_list)
        current_idx = id_list.index(article_id) + 1 if article_id in id_list else 1

    # nav に応じてリダイレクト先を決定
    if nav == "prev":
        target_idx = max(1, current_idx - 1)
        return RedirectResponse(
            url=f"/screen?article_index={target_idx}", status_code=303
        )
    elif nav == "jump" and jump_index is not None:
        # 入力値を 1〜total にクランプ
        target_idx = max(1, min(jump_index, total))
        return RedirectResponse(
            url=f"/screen?article_index={target_idx}", status_code=303
        )
    else:
        # 通常は「保存して次へ」→ 未評価の次の文献へ（/screen のロジックに任せる）
        return RedirectResponse(url="/screen", status_code=303)


# ---------------------------------------------------------
# ダッシュボード（全ユーザーの進捗一覧）
# ---------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with Session(engine) as session:
        users: List[User] = session.exec(select(User)).all()

        # グループ別の総数
        group_totals = {}
        for g in range(1, 6):
            total_g = session.exec(
                select(func.count(Article.id)).where(Article.group_no == g)
            ).one()
            group_totals[g] = total_g

        rows = []
        for u in users:
            total = group_totals.get(u.group_no, 0)
            rated = session.exec(
                select(func.count(ScreeningDecision.id))
                .join(Article, Article.id == ScreeningDecision.article_id)
                .where(ScreeningDecision.user_id == u.id)
                .where(Article.group_no == u.group_no)
            ).one()
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
# 結果を CSV でエクスポート
# ---------------------------------------------------------
@app.get("/export", response_class=StreamingResponse)
def export_csv(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with Session(engine) as session:
        stmt = (
            select(
                Article.group_no,
                Article.id,
                Article.pmid,
                Article.title_en,
                Article.title_ja,
                User.username,
                ScreeningDecision.decision,
                ScreeningDecision.comment,
                Article.direction_gpt,
                Article.direction_gemini,
                Article.condition_list_gpt,
                Article.condition_list_gemini,
            )
            .join(ScreeningDecision, Article.id == ScreeningDecision.article_id)
            .join(User, User.id == ScreeningDecision.user_id)
            .order_by(Article.group_no, Article.id, User.username)
        )
        rows = session.exec(stmt).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "group_no",
            "article_id",
            "pmid",
            "title_en",
            "title_ja",
            "username",
            "decision",
            "comment",
            "direction_gpt",
            "direction_gemini",
            "condition_list_gpt",
            "condition_list_gemini",
        ]
    )

    for (
        group_no,
        article_id,
        pmid,
        title_en,
        title_ja,
        username,
        decision,
        comment,
        direction_gpt,
        direction_gemini,
        condition_gpt,
        condition_gemini,
    ) in rows:
        writer.writerow(
            [
                group_no,
                article_id,
                pmid,
                title_en or "",
                title_ja or "",
                username,
                decision,
                comment or "",
                direction_gpt if direction_gpt is not None else "",
                direction_gemini if direction_gemini is not None else "",
                condition_gpt or "",
                condition_gemini or "",
            ]
        )

    output.seek(0)
    filename = "apathy_screening_results.csv"

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


# ---------------------------------------------------------
# パスワード変更（GET）
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


# ---------------------------------------------------------
# パスワード変更（POST）
# ---------------------------------------------------------
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
