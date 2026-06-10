"""Промежуточный слой аутентификации для шаблонов Jinja2."""

from datetime import datetime, timezone

from fastapi import Request, Depends
from sqlalchemy.orm import Session

from app.auth.jwt import decode_token
from app.models import get_db, User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Извлекает текущего пользователя из JWT в cookie. Возвращает None, если вход не выполнен."""
    token = request.cookies.get("access_token")
    if not token:
        return None

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None

    user_id = int(payload["sub"])
    user = db.query(User).filter(User.user_id == user_id).first()

    if user and user.status == "blocked":
        return None

    return user


def require_role(*roles: str):
    """Зависимость, требующая определённой роли (ролей)."""
    def dependency(request: Request, db: Session = Depends(get_db)) -> User:
        user = get_current_user(request, db)
        if user is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Вход не выполнен")
        if user.role not in roles:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user
    return dependency
