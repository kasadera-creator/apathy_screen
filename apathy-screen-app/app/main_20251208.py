from typing import Optional, List, Dict
from pathlib import Path
import csv
import io
from collections import defaultdict

from fastapi import FastAPI, Request, Form, Query, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy import func

from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext

# models.py から定義をインポート
from .models import (
    Article,
    ScreeningDecision,
    User,
    AppConfig,
    ScaleArticle,
    ScaleScreeningDecision,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "apathy_screening.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

N_GROUPS = 4

# グループ名の定義
GROUP_NAMES = {
    1: "Jyunten",
    2: "Osaka",
    3: "Nagoya1",
    4: "Nagoya2",
}

engine = create_engine(DATABASE_URL, echo=False)
SQLModel.metadata.create_all(engine)

TEMPLATE_DIR = BASE_DIR / "templates"
app = FastAPI()

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["GROUP_NAMES"] = GROUP_NAMES

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "sha256_crypt"],
    deprecated="auto",
)

# --- Middleware ---
@app.middleware("http")
async def add_user_to_request(request: Request, call_next):
    user_id = request.session.get("user_id")
    if user_id:
        with Session(engine) as session:
            user = session.get(User, user_id)
            request.state.user = user
    else:
        request.state.user = None
    response = await call_next(request)
    return response

app.add_middleware(SessionMiddleware, secret_key="very-secret-key-for-apathy-app")

# --- Helpers ---
def get_current_user(request: Request) -> Optional[User]:
    return request.state.user

def get_year_min(session: Session) -> Optional[int]:
    cfg = session.get(AppConfig, 1)
    if cfg is None:
        cfg = AppConfig(id=1, year_min=2015)
        session.add(cfg)
        session.commit()
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
    with Session(engine) as session:
        if session.exec(select(func.count(User.id))).one() > 0:
            return
        users = [
            ("user1", "password1", 1, True),
            ("user2", "password2", 1, False),
            ("user3", "password3", 2, False),
            ("user4", "password4", 2, False),
            ("user5", "password5", 3, False),
            ("user6", "password6", 3, False),
            ("user7", "password7", 4, False),
            ("user8", "password8", 4, False),
        ]
        for uname, pw, grp, is_adm in users:
            u = User(username=uname, password_hash=pwd_context.hash(pw), group_no=grp, is_admin=is_adm)
            session.add(u)
        session.commit()

@app.on_event("startup")
def on_startup():
    ensure_default_users()

def get_group_article_ids(session: Session, year_min: Optional[int], user_group_no: int) -> List[int]:
    all_rows = list(session.exec(select(Article.id, Article.authors, Article.pmid, Article.year)))
    if not all_rows: return []
    rows = all_rows
    if year_min is not None:
        filtered = [r for r in all_rows if (r[3] is not None and r[3] >= year_min)]
        if filtered: rows = filtered
    rows.sort(key=lambda r: (r[1] or "", r[2] or 0))
    n = len(rows)
    id_list = []
    for i, row in enumerate(rows):
        if ((i * N_GROUPS) // n + 1) == user_group_no:
            id_list.append(row[0])
    return id_list

def get_group_scale_article_ids(session: Session, user_group_no: int) -> List[int]:
    rows = session.exec(select(ScaleArticle.id).where(ScaleArticle.group_no == user_group_no).order_by(ScaleArticle.id)).all()
    if rows: return [int(r) for r in rows]
    all_rows = list(session.exec(select(ScaleArticle.id, ScaleArticle.pmid)))
    if not all_rows: return []
    all_rows.sort(key=lambda r: (r[1] or 0))
    n = len(all_rows)
    id_list = []
    for i, row in enumerate(all_rows):
        if ((i * N_GROUPS) // n + 1) == user_group_no:
            id_list.append(row[0])
    return id_list

def check_group_status(session: Session, group_no: int, mode: str = "disease"):
    users = session.exec(select(User).where(User.group_no == group_no)).all()
    if not users: return False, False

    if mode == "disease":
        year_min = get_year_min(session)
        article_ids = get_group_article_ids(session, year_min, group_no)
        decisions = session.exec(select(ScreeningDecision).where(ScreeningDecision.article_id.in_(article_ids))).all()
        decision_map = defaultdict(dict)
        for d in decisions:
            if d.decision is not None:
                decision_map[d.article_id][d.user_id] = d.decision
    else: # scale
        article_ids = get_group_scale_article_ids(session, group_no)
        decisions = session.exec(select(ScaleScreeningDecision).where(ScaleScreeningDecision.scale_article_id.in_(article_ids))).all()
        decision_map = defaultdict(dict)
        for d in decisions:
            if d.rating is not None:
                decision_map[d.scale_article_id][d.user_id] = d.rating

    total_articles = len(article_ids)
    if total_articles == 0: return False, False

    for u in users:
        user_done_count = 0
        for aid in article_ids:
            if u.id in decision_map.get(aid, {}):
                user_done_count += 1
        if user_done_count < total_articles:
            return False, False

    has_conflicts = False
    for aid in article_ids:
        votes = decision_map.get(aid, {})
        vals = list(votes.values())
        has_2 = any(v == 2 for v in vals)
        has_1 = any(v == 1 for v in vals)
        has_0 = any(v == 0 for v in vals)
        if not has_2:
            if has_1 and has_0:
                has_conflicts = True
                break
    
    return True, has_conflicts

# --- Routes ---
@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse("index.html", {
        "request": request, "username": user.username if user else None,
        "group_no": user.group_no if user else None, "current_page": "home"
    })

@app.get("/database", response_class=HTMLResponse)
def database(request: Request):
    user = get_current_user(request)
    with Session(engine) as session:
        articles = session.exec(select(Article).order_by(Article.id)).all()
    return templates.TemplateResponse("database.html", {
        "request": request, "articles": articles,
        "username": user.username if user else None,
        "group_no": user.group_no if user else None, "current_page": "database"
    })

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login", 303)
    is_admin = user.is_admin
    
    current_step = 1
    year_min = 2015

    with Session(engine) as session:
        year_min = get_year_min(session)
        # 二次スクリーニング連携ロジックは削除
        
        # 進捗チェックのみ実施
        users = session.exec(select(User)).all()
        total_assigned = 0
        total_done = 0
        for u in users:
            ids = get_group_article_ids(session, year_min, u.group_no)
            done = session.exec(select(func.count(ScreeningDecision.id)).where(
                (ScreeningDecision.user_id == u.id) & 
                (ScreeningDecision.article_id.in_(ids)) & 
                (ScreeningDecision.decision.is_not(None))
            )).one()
            total_assigned += len(ids)
            total_done += done
        if total_assigned > 0 and (total_done / total_assigned) > 0.98:
            current_step = 2

    return templates.TemplateResponse("settings.html", {
        "request": request, "username": user.username, "group_no": user.group_no,
        "year_min": year_min, "is_admin": is_admin, 
        "current_step": current_step,
        "current_page": "settings"
    })

@app.post("/settings", response_class=HTMLResponse)
def settings_submit(request: Request, year_min: Optional[int] = Form(None)):
    user = get_current_user(request)
    if not user or not user.is_admin: return RedirectResponse("/settings", 303)
    with Session(engine) as session:
        set_year_min(session, year_min)
    return RedirectResponse("/settings", 303)

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    user = get_current_user(request)
    if not user or not user.is_admin: return RedirectResponse("/settings", 303)
    with Session(engine) as session:
        all_users = session.exec(select(User).order_by(User.id)).all()
    return templates.TemplateResponse("admin_users.html", {
        "request": request, "username": user.username, "group_no": user.group_no,
        "all_users": all_users, "current_page": "settings"
    })

@app.post("/admin/users/update", response_class=HTMLResponse)
def admin_user_update(request: Request, user_id: int = Form(...), username: str = Form(...), group_no: int = Form(...), is_admin: bool = Form(False)):
    current_user = get_current_user(request)
    if not current_user or not current_user.is_admin: return RedirectResponse("/settings", 303)
    with Session(engine) as session:
        target_user = session.get(User, user_id)
        if target_user:
            target_user.username = username
            target_user.group_no = group_no
            if target_user.id != current_user.id:
                target_user.is_admin = is_admin
            else:
                target_user.is_admin = True
            session.add(target_user)
            session.commit()
    return RedirectResponse("/admin/users", 303)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = Query("screen")):
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "next": next, "current_page": "login"})

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("screen")):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if not user or not pwd_context.verify(password, user.password_hash):
            return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials", "next": next})
        request.session["user_id"] = user.id
    if next == "scale": return RedirectResponse("/scale_screen", 303)
    if next == "conflicts": return RedirectResponse("/conflicts", 303)
    return RedirectResponse("/screen", 303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 303)

@app.get("/change_password", response_class=HTMLResponse)
def change_password_page(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login")
    return templates.TemplateResponse("change_password.html", {"request": request, "error": None, "success": None, "username": user.username, "group_no": user.group_no, "current_page": "change_password"})

@app.post("/change_password", response_class=HTMLResponse)
def change_password(request: Request, current_password: str = Form(...), new_password: str = Form(...), new_password_confirm: str = Form(...)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login")
    if new_password != new_password_confirm:
        return templates.TemplateResponse("change_password.html", {"request": request, "error": "Passwords do not match", "success": None, "username": user.username, "group_no": user.group_no, "current_page": "change_password"})
    if len(new_password) < 6:
        return templates.TemplateResponse("change_password.html", {"request": request, "error": "Password too short", "success": None, "username": user.username, "group_no": user.group_no, "current_page": "change_password"})
    with Session(engine) as session:
        db_user = session.exec(select(User).where(User.id == user.id)).first()
        if not db_user or not pwd_context.verify(current_password, db_user.password_hash):
            return templates.TemplateResponse("change_password.html", {"request": request, "error": "Incorrect current password", "success": None, "username": user.username, "group_no": user.group_no, "current_page": "change_password"})
        db_user.password_hash = pwd_context.hash(new_password)
        session.add(db_user)
        session.commit()
    return templates.TemplateResponse("change_password.html", {"request": request, "error": None, "success": "Password changed", "username": user.username, "group_no": user.group_no, "current_page": "change_password"})

# --- Screen ---
@app.get("/screen", response_class=HTMLResponse, name="screen_page")
def screen_page(request: Request, group_no: int = Query(None), article_index: int = Query(None)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login", 303)
    user_id = user.id
    group_no = user.group_no if group_no is None else group_no

    with Session(engine) as session:
        year_min = get_year_min(session)
        id_list = get_group_article_ids(session, year_min, group_no)
        total = len(id_list)
        rated = session.exec(select(func.count(ScreeningDecision.id)).where(
            (ScreeningDecision.user_id == user_id) & (ScreeningDecision.article_id.in_(id_list)) & (ScreeningDecision.decision.is_not(None))
        )).one() if id_list else 0

        article = None
        current_index = None
        if id_list:
            if article_index is not None:
                idx = max(1, min(article_index, total))
                article = session.get(Article, id_list[idx - 1])
                current_index = idx
            else:
                decided_ids = set(session.exec(select(ScreeningDecision.article_id).where(ScreeningDecision.user_id == user_id)).all())
                for i, aid in enumerate(id_list):
                    if aid not in decided_ids:
                        article = session.get(Article, aid)
                        current_index = i + 1
                        break
                if not article:
                    article = session.get(Article, id_list[-1])
                    current_index = total

        prev_decision = None
        prev_comment = ""
        prev_flag_cause = False
        prev_flag_treatment = False
        prev_cat_physical = False
        prev_cat_brain = False
        prev_cat_psycho = False

        if article:
            existing = session.exec(select(ScreeningDecision).where((ScreeningDecision.user_id == user_id) & (ScreeningDecision.article_id == article.id))).first()
            if existing:
                prev_decision = existing.decision
                prev_comment = existing.comment or ""
                prev_flag_cause = existing.flag_cause
                prev_flag_treatment = existing.flag_treatment
                prev_cat_physical = existing.cat_physical
                prev_cat_brain = existing.cat_brain
                prev_cat_psycho = existing.cat_psycho

    return templates.TemplateResponse("screen.html", {
        "request": request, "group_no": group_no, "username": user.username,
        "article": article, "direction_memo": None, "progress_done": rated, "progress_total": total,
        "current_index": current_index, "current_page": "screen",
        "prev_decision": prev_decision, "prev_comment": prev_comment,
        "prev_flag_cause": prev_flag_cause, "prev_flag_treatment": prev_flag_treatment,
        "prev_cat_physical": prev_cat_physical,
        "prev_cat_brain": prev_cat_brain,
        "prev_cat_psycho": prev_cat_psycho,
    })

@app.post("/screen", response_class=HTMLResponse, name="submit_screen")
def submit_screen(
    request: Request, article_id: int = Form(...), decision: Optional[int] = Form(None),
    flag_cause: int = Form(0), flag_treatment: int = Form(0),
    cat_physical: int = Form(0), cat_brain: int = Form(0), cat_psycho: int = Form(0),
    nav: str = Form("next"),
    jump_index: str | None = Form(None), comment: str = Form("")
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login", 303)
    
    with Session(engine) as session:
        target_article = session.get(Article, article_id)
        target_group_no = target_article.group_no if target_article else (user.group_no or 1)
        year_min = get_year_min(session)
        id_list = get_group_article_ids(session, year_min, target_group_no)
        try: current_index = id_list.index(article_id) + 1
        except ValueError: current_index = 1
        
        existing = session.exec(select(ScreeningDecision).where((ScreeningDecision.user_id == user.id) & (ScreeningDecision.article_id == article_id))).first()
        
        if existing:
            if decision is not None: existing.decision = decision
            existing.comment = comment or ""
            existing.flag_cause = bool(flag_cause)
            existing.flag_treatment = bool(flag_treatment)
            existing.cat_physical = bool(cat_physical)
            existing.cat_brain = bool(cat_brain)
            existing.cat_psycho = bool(cat_psycho)
            session.add(existing)
        elif decision is not None:
            session.add(ScreeningDecision(
                user_id=user.id, article_id=article_id, decision=decision, comment=comment or "",
                flag_cause=bool(flag_cause), flag_treatment=bool(flag_treatment),
                cat_physical=bool(cat_physical), cat_brain=bool(cat_brain), cat_psycho=bool(cat_psycho)
            ))
        session.commit()
    
    total = len(id_list)
    target = current_index
    if nav == "prev": target = max(1, current_index - 1)
    elif nav == "jump" and jump_index: 
        try: target = max(1, min(int(jump_index), total))
        except: pass
    elif nav == "next" and total > 0: target = min(current_index + 1, total)
    
    return RedirectResponse(f"/screen?article_index={target}&group_no={target_group_no}", 303)

# --- Scale Screen ---
@app.get("/scale_screen", response_class=HTMLResponse, name="scale_screen_page")
def scale_screen_page(request: Request, article_index: int = Query(1, ge=1), group_no: Optional[int] = Query(None)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login?next=scale", 303)
    user_id = user.id
    group_no = user.group_no if group_no is None else group_no

    with Session(engine) as session:
        id_list = get_group_scale_article_ids(session, group_no)
        total = len(id_list)
        my_done = session.exec(select(func.count(ScaleScreeningDecision.id)).where(
            (ScaleScreeningDecision.user_id == user_id) & (ScaleScreeningDecision.scale_article_id.in_(id_list)) & (ScaleScreeningDecision.rating.is_not(None))
        )).one() if id_list else 0
        
        total_all = session.exec(select(func.count(ScaleArticle.id))).one()
        all_done = session.exec(select(func.count(func.distinct(ScaleScreeningDecision.scale_article_id))).where(ScaleScreeningDecision.rating.is_not(None))).one()

        article = None
        current_index = None
        if id_list:
            if article_index is not None:
                idx = max(1, min(article_index, total))
                article = session.get(ScaleArticle, id_list[idx - 1])
                current_index = idx
            else:
                decided = set(session.exec(select(ScaleScreeningDecision.scale_article_id).where(ScaleScreeningDecision.user_id == user_id)).all())
                for i, aid in enumerate(id_list):
                    if aid not in decided:
                        article = session.get(ScaleArticle, aid)
                        current_index = i + 1
                        break
                if not article:
                    article = session.get(ScaleArticle, id_list[-1])
                    current_index = total

        if article:
            if not article.doi and article.pmid:
                found_doi = session.exec(select(Article.doi).where(Article.pmid == article.pmid)).first()
                if found_doi:
                    article.doi = found_doi

        my_rating = None
        my_comment = ""
        if article:
            existing = session.exec(select(ScaleScreeningDecision).where((ScaleScreeningDecision.user_id == user_id) & (ScaleScreeningDecision.scale_article_id == article.id))).first()
            if existing:
                my_rating = existing.rating
                my_comment = existing.comment or ""

    return templates.TemplateResponse("scale_screen.html", {
        "request": request, "username": user.username, "group_no": group_no,
        "article": article, "progress_done": my_done, "progress_total": total,
        "current_index": current_index, "scale_all_done": all_done, "scale_total_all": total_all,
        "my_rating": my_rating, "my_comment": my_comment, "current_page": "scale_screen"
    })

@app.post("/scale_screen", response_class=HTMLResponse, name="submit_scale_screen")
def submit_scale_screen(
    request: Request, article_id: int = Form(...), decision: Optional[int] = Form(None),
    comment: str = Form(""), nav: str = Form("next"), jump_index: Optional[str] = Form(None)
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login?next=scale", 303)
    
    with Session(engine) as session:
        target_article = session.get(ScaleArticle, article_id)
        target_group_no = target_article.group_no if target_article else user.group_no

        id_list = get_group_scale_article_ids(session, target_group_no)
        try: current_index = id_list.index(article_id) + 1
        except ValueError: current_index = 1
        
        existing = session.exec(select(ScaleScreeningDecision).where((ScaleScreeningDecision.user_id == user.id) & (ScaleScreeningDecision.scale_article_id == article_id))).first()
        if existing:
            if decision is not None: existing.rating = decision
            if comment is not None: existing.comment = comment
            session.add(existing)
        elif decision is not None:
            session.add(ScaleScreeningDecision(user_id=user.id, scale_article_id=article_id, rating=decision, comment=comment or ""))
        session.commit()

    target = current_index
    total = len(id_list)
    if nav == "prev": target = max(1, current_index - 1)
    elif nav == "jump" and jump_index:
        try: target = max(1, min(int(jump_index), total))
        except: pass
    elif nav == "next" and total > 0: target = min(current_index + 1, total)

    return RedirectResponse(f"/scale_screen?article_index={target}&group_no={target_group_no}", 303)

# --- Progress Pages ---
@app.get("/my_index", response_class=HTMLResponse, name="disease_progress_my")
def my_index(request: Request, target_user_id: Optional[int] = Query(None)):
    current_user = get_current_user(request)
    if not current_user: return RedirectResponse("/login", 303)
    view_user = current_user
    if target_user_id:
        with Session(engine) as session:
            u = session.get(User, target_user_id)
            if u: view_user = u
    request.state.user = current_user
    with Session(engine) as session:
        year_min = get_year_min(session)
        id_list = get_group_article_ids(session, year_min, view_user.group_no)
        done_count = session.exec(select(func.count(ScreeningDecision.id)).where(
            (ScreeningDecision.user_id == view_user.id) & (ScreeningDecision.article_id.in_(id_list)) & (ScreeningDecision.decision.is_not(None))
        )).one() if id_list else 0
        stmt = select(Article, ScreeningDecision).join(
            ScreeningDecision, 
            (ScreeningDecision.article_id == Article.id) & (ScreeningDecision.user_id == view_user.id), 
            isouter=True
        ).where(Article.id.in_(id_list)).order_by(Article.id)
        rows = session.exec(stmt).all()
    return templates.TemplateResponse("my_index.html", {
        "request": request, "rows": rows, "username": current_user.username, "group_no": current_user.group_no,
        "view_user": view_user, "current_page": "my_index", 
        "progress_done": done_count, "progress_total": len(id_list), "progress_pct": int(done_count * 100 / len(id_list)) if id_list else 0
    })

@app.get("/scale_my_index", response_class=HTMLResponse, name="scale_progress_my")
def scale_my_index(request: Request, target_user_id: Optional[int] = Query(None)):
    current_user = get_current_user(request)
    if not current_user: return RedirectResponse("/login?next=scale", 303)
    view_user = current_user
    if target_user_id:
        with Session(engine) as session:
            u = session.get(User, target_user_id)
            if u: view_user = u
    with Session(engine) as session:
        id_list = get_group_scale_article_ids(session, view_user.group_no)
        done_count = session.exec(select(func.count(ScaleScreeningDecision.id)).where(
            (ScaleScreeningDecision.user_id == view_user.id) & (ScaleScreeningDecision.scale_article_id.in_(id_list)) & (ScaleScreeningDecision.rating.is_not(None))
        )).one() if id_list else 0
        stmt = select(ScaleArticle, ScaleScreeningDecision).join(
            ScaleScreeningDecision, 
            (ScaleScreeningDecision.scale_article_id == ScaleArticle.id) & (ScaleScreeningDecision.user_id == view_user.id), 
            isouter=True
        ).where(ScaleArticle.id.in_(id_list)).order_by(ScaleArticle.id)
        rows = session.exec(stmt).all()
    return templates.TemplateResponse("scale_my_index.html", {
        "request": request, "rows": rows, "username": current_user.username, "group_no": current_user.group_no,
        "view_user": view_user, "current_page": "scale_my_index", 
        "progress_done": done_count, "progress_total": len(id_list), 
        "progress_pct": int(done_count * 100 / len(id_list)) if id_list else 0
    })

@app.get("/dashboard", response_class=HTMLResponse, name="dashboard")
def dashboard(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login", 303)
    with Session(engine) as session:
        year_min = get_year_min(session)
        users = session.exec(select(User)).all()
        rows, o_d_t, o_d_r, o_s_t, o_s_r = [], 0, 0, 0, 0
        group_progress = defaultdict(lambda: {"total": 0, "done": 0})
        for u in users:
            d_ids = get_group_article_ids(session, year_min, u.group_no)
            d_r = session.exec(select(func.count(ScreeningDecision.id)).where((ScreeningDecision.user_id == u.id) & (ScreeningDecision.article_id.in_(d_ids)) & (ScreeningDecision.decision.is_not(None)))).one() if d_ids else 0
            s_ids = session.exec(select(ScaleArticle.id).where(ScaleArticle.group_no == u.group_no)).all()
            s_r = session.exec(select(func.count(ScaleScreeningDecision.id)).where((ScaleScreeningDecision.user_id == u.id) & (ScaleScreeningDecision.scale_article_id.in_(s_ids)) & (ScaleScreeningDecision.rating.is_not(None)))).one() if s_ids else 0
            
            rows.append({"id": u.id, "username": u.username, "group_no": u.group_no, "dis_rated": d_r, "dis_total": len(d_ids), "dis_pct": (d_r/len(d_ids)*100) if d_ids else 0, "scale_rated": s_r, "scale_total": len(s_ids), "scale_pct": (s_r/len(s_ids)*100) if s_ids else 0})
            o_d_t += len(d_ids); o_d_r += d_r; o_s_t += len(s_ids); o_s_r += s_r
            
            group_progress[u.group_no]["total"] += len(d_ids)
            group_progress[u.group_no]["done"] += d_r
        
        my_group_stats = group_progress.get(user.group_no, {"total": 1, "done": 0})
        is_my_group_complete = (my_group_stats["total"] > 0 and my_group_stats["total"] == my_group_stats["done"])

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "rows": rows, "username": user.username, "group_no": user.group_no, "current_page": "dashboard",
        "overall_dis_total": o_d_t, "overall_dis_rated": o_d_r, "overall_dis_pct": (o_d_r/o_d_t*100) if o_d_t else 0,
        "overall_scale_total": o_s_t, "overall_scale_rated": o_s_r, "overall_scale_pct": (o_s_r/o_s_t*100) if o_s_t else 0,
        "is_my_group_complete": is_my_group_complete
    })

# --- Conflicts Resolution ---
@app.get("/conflicts", response_class=HTMLResponse, name="conflicts_page")
def conflicts_page(request: Request, mode: str = Query("disease"), group_no: Optional[int] = Query(None)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login?next=conflicts", 303)
    if group_no is None: group_no = user.group_no
    
    conflicts_list = []
    
    with Session(engine) as session:
        is_complete, has_conflicts = check_group_status(session, group_no, mode)
        
        if is_complete:
            if mode == "disease":
                year_min = get_year_min(session)
                article_ids = get_group_article_ids(session, year_min, group_no)
                decisions = session.exec(select(ScreeningDecision).where(ScreeningDecision.article_id.in_(article_ids))).all()
                art_map = defaultdict(dict)
                for d in decisions:
                    if d.decision is not None:
                        u = session.get(User, d.user_id)
                        uname = u.username if u else str(d.user_id)
                        art_map[d.article_id][uname] = d.decision
                        art_map[d.article_id]['_comment_' + uname] = d.comment
                for aid, votes in art_map.items():
                    vals = [v for k, v in votes.items() if not k.startswith('_')]
                    has_2 = any(v == 2 for v in vals)
                    has_1 = any(v == 1 for v in vals)
                    has_0 = any(v == 0 for v in vals)
                    if not has_2 and (has_1 and has_0):
                        art = session.get(Article, aid)
                        if art: conflicts_list.append({"id": art.id, "pmid": art.pmid, "title": art.title_ja or art.title_en, "abstract": art.abstract_ja or art.abstract_en, "votes": votes})
            else:
                scale_ids = get_group_scale_article_ids(session, group_no)
                decisions = session.exec(select(ScaleScreeningDecision).where(ScaleScreeningDecision.scale_article_id.in_(scale_ids))).all()
                art_map = defaultdict(dict)
                for d in decisions:
                    if d.rating is not None:
                        u = session.get(User, d.user_id)
                        uname = u.username if u else str(d.user_id)
                        art_map[d.scale_article_id][uname] = d.rating
                        art_map[d.scale_article_id]['_comment_' + uname] = d.comment
                for aid, votes in art_map.items():
                    vals = [v for k, v in votes.items() if not k.startswith('_')]
                    has_2 = any(v == 2 for v in vals)
                    has_1 = any(v == 1 for v in vals)
                    has_0 = any(v == 0 for v in vals)
                    if not has_2 and (has_1 and has_0):
                        art = session.get(ScaleArticle, aid)
                        if art: conflicts_list.append({"id": art.id, "pmid": art.pmid, "title": art.title_ja or art.title_en, "abstract": art.abstract_ja or art.abstract_en, "votes": votes})

    return templates.TemplateResponse("conflicts.html", {
        "request": request, "username": user.username, "group_no": user.group_no,
        "mode": mode, "target_group_no": group_no, "conflicts": conflicts_list,
        "is_complete": is_complete,
        "current_page": "conflicts"
    })

@app.post("/resolve_conflict", response_class=HTMLResponse)
def resolve_conflict(request: Request, mode: str = Form(...), article_id: int = Form(...), resolution: int = Form(...), target_group_no: int = Form(...)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login", 303)
    with Session(engine) as session:
        if mode == "disease":
            decisions = session.exec(select(ScreeningDecision).where(ScreeningDecision.article_id == article_id)).all()
            for d in decisions:
                d.decision = resolution
                session.add(d)
        else:
            decisions = session.exec(select(ScaleScreeningDecision).where(ScaleScreeningDecision.scale_article_id == article_id)).all()
            for d in decisions:
                d.rating = resolution
                session.add(d)
        session.commit()
    return RedirectResponse(f"/conflicts?mode={mode}&group_no={target_group_no}", 303)

@app.get("/export_secondary_candidates", response_class=StreamingResponse)
def export_secondary_candidates_txt(request: Request, mode: str = Query("disease"), group_no: Optional[int] = Query(None)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login", 303)
    target_group = group_no if group_no else user.group_no
    
    with Session(engine) as session:
        # 完了チェック (未完了ならDLさせない)
        is_complete, has_conflicts = check_group_status(session, target_group, mode)
        if not is_complete or has_conflicts:
             return HTMLResponse("Error: Screening incomplete or conflicts exist.", status_code=400)

        output = io.StringIO()
        pmids = set()
        
        if mode == "disease":
            year_min = get_year_min(session)
            article_ids = get_group_article_ids(session, year_min, target_group)
            decisions = session.exec(select(ScreeningDecision).where(ScreeningDecision.article_id.in_(article_ids))).all()
            art_votes = defaultdict(list)
            for d in decisions:
                if d.decision is not None: art_votes[d.article_id].append(d.decision)
            
            for aid, votes in art_votes.items():
                if votes and max(votes) >= 1: # 採用(2) or 保留(1)
                    art = session.get(Article, aid)
                    if art and art.pmid: pmids.add(art.pmid)
        else:
            scale_ids = get_group_scale_article_ids(session, target_group)
            decisions = session.exec(select(ScaleScreeningDecision).where(ScaleScreeningDecision.scale_article_id.in_(scale_ids))).all()
            art_votes = defaultdict(list)
            for d in decisions:
                if d.rating is not None: art_votes[d.scale_article_id].append(d.rating)
            
            for aid, votes in art_votes.items():
                if votes and max(votes) >= 1:
                    art = session.get(ScaleArticle, aid)
                    if art and art.pmid: pmids.add(art.pmid)
                    
        for pmid in sorted(list(pmids)): output.write(f"{pmid}\n")

    output.seek(0)
    filename = f"secondary_candidates_{mode}_g{target_group}.txt"
    return StreamingResponse(output, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

# --- Export ---
@app.get("/export_disease", response_class=StreamingResponse, name="download_disease")
def export_disease_csv(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login")
    with Session(engine) as session:
        rows = session.exec(select(ScreeningDecision, Article, User).join(Article, Article.id == ScreeningDecision.article_id).join(User, User.id == ScreeningDecision.user_id).order_by(Article.id, User.username)).all()
    output = io.StringIO(); output.write("\ufeff"); writer = csv.writer(output)
    writer.writerow(["article_id", "pmid", "title_en", "title_ja", "username", "decision", "comment", 
                     "flag_cause", "flag_treatment", 
                     "cat_physical", "cat_brain", "cat_psycho", # ★追加
                     "direction_gpt", "direction_gemini", "condition_list_gpt", "condition_list_gemini", "year"])
    for sd, art, usr in rows:
        writer.writerow([
            art.id, art.pmid, art.title_en, art.title_ja, usr.username, sd.decision, sd.comment, 
            int(sd.flag_cause), int(sd.flag_treatment), 
            int(sd.cat_physical), int(sd.cat_brain), int(sd.cat_psycho), # ★追加
            art.direction_gpt, art.direction_gemini, art.condition_list_gpt, art.condition_list_gemini, art.year
        ])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="apathy_disease_screening_results.csv"'})

@app.get("/export_scale", response_class=StreamingResponse, name="download_scale")
def export_scale_csv(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/login")
    with Session(engine) as session:
        rows = session.exec(select(ScaleScreeningDecision, ScaleArticle, User).join(ScaleArticle, ScaleArticle.id == ScaleScreeningDecision.scale_article_id).join(User, User.id == ScaleScreeningDecision.user_id).order_by(ScaleArticle.id, User.username)).all()
    output = io.StringIO(); output.write("\ufeff"); writer = csv.writer(output)
    writer.writerow(["scale_article_id", "pmid", "title_en", "title_ja", "username", "rating", "comment", "gemini_judgement", "gemini_summary_ja", "gemini_reason_ja", "gemini_tools", "year"])
    for sd, art, usr in rows:
        writer.writerow([art.id, art.pmid, art.title_en, art.title_ja, usr.username, sd.rating, sd.comment, art.gemini_judgement, art.gemini_summary_ja, art.gemini_reason_ja, art.gemini_tools, art.year])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="apathy_scale_screening_results.csv"'})