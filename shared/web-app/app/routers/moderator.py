"""Панель модератора: список пользователей, блокировка и разблокировка."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.middleware import require_role
from app.models import get_db, User

router = APIRouter(prefix="/moderator")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def moderator_panel(
    request: Request,
    role_filter: str | None = None,
    status_filter: str | None = None,
    q: str | None = None,
    user: User = Depends(require_role("moderator", "admin")),
    db: Session = Depends(get_db),
):
    query = db.query(User)

    if role_filter:
        query = query.filter(User.role == role_filter)
    if status_filter:
        query = query.filter(User.status == status_filter)
    if q:
        query = query.filter(
            (User.username.ilike(f"%{q}%")) | (User.email.ilike(f"%{q}%"))
        )

    users = query.order_by(User.created_at.desc()).all()

    return templates.TemplateResponse("moderator.html", {
        "request": request,
        "user": user,
        "users": users,
        "role_filter": role_filter,
        "status_filter": status_filter,
        "q": q,
    })


@router.post("/block/{target_id}")
def block_user(
    request: Request,
    target_id: int,
    user: User = Depends(require_role("moderator", "admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.user_id == target_id).first()
    if not target:
        return RedirectResponse(url="/moderator/", status_code=302)

    # Модератор не может заблокировать администратора
    if target.role == "admin" and user.role != "admin":
        return RedirectResponse(url="/moderator/", status_code=302)

    target.status = "blocked"
    db.commit()
    return RedirectResponse(url="/moderator/", status_code=302)


@router.post("/unblock/{target_id}")
def unblock_user(
    request: Request,
    target_id: int,
    user: User = Depends(require_role("moderator", "admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.user_id == target_id).first()
    if target:
        target.status = "active"
        db.commit()
    return RedirectResponse(url="/moderator/", status_code=302)
