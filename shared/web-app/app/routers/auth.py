"""Маршруты аутентификации: вход, регистрация, выход, OAuth (GitHub, Google)."""

import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token, create_refresh_token
from app.auth.password import hash_password, verify_password
from app.config import (
    MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES,
    GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET,
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
)
from app.models import get_db, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _set_auth_cookies(user: User) -> RedirectResponse:
    access_token = create_access_token(user.user_id, user.role)
    refresh_token = create_refresh_token(user.user_id)
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie("access_token", access_token, httponly=True, max_age=900)
    resp.set_cookie("refresh_token", refresh_token, httponly=True, max_age=604800)
    return resp


# Вход и регистрация по email

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()

    error = None
    if not user:
        error = "Неверный email или пароль"
    elif user.status == "blocked":
        error = "Аккаунт заблокирован"
    elif user.locked_until and user.locked_until > datetime.now(timezone.utc):
        error = "Аккаунт временно заблокирован. Попробуйте позже."
    elif not user.password_hash:
        error = "Используйте OAuth для входа"
    elif not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_attempts = 0
        db.commit()
        error = "Неверный email или пароль"

    if error:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": error}, status_code=400
        )

    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    return _set_auth_cookies(user)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if len(password) < 8:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Пароль должен содержать минимум 8 символов"},
            status_code=400,
        )

    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Email уже занят"},
            status_code=400,
        )

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _set_auth_cookies(user)


@router.get("/logout")
def logout():
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp


# GitHub OAuth

@router.get("/auth/github")
def github_login(request: Request):
    if not GITHUB_CLIENT_ID:
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "GitHub OAuth не настроен (GITHUB_CLIENT_ID пуст)"
        }, status_code=400)
    redirect_uri = str(request.url_for("github_callback"))
    return RedirectResponse(
        f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}&redirect_uri={redirect_uri}&scope=user:email"
    )


@router.get("/auth/github/callback")
async def github_callback(request: Request, code: str, db: Session = Depends(get_db)):
    # Обмен кода авторизации на токен доступа
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return templates.TemplateResponse("login.html", {
                "request": request, "error": "Ошибка GitHub OAuth"
            }, status_code=400)

        # Получить данные пользователя
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        gh_user = user_resp.json()

        # Получить email (может быть приватным)
        emails_resp = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        emails = emails_resp.json()
        primary_email = next(
            (e["email"] for e in emails if e.get("primary")),
            gh_user.get("email"),
        )

    if not primary_email:
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Не удалось получить email из GitHub"
        }, status_code=400)

    gh_id = str(gh_user["id"])
    username = gh_user.get("login", primary_email.split("@")[0])

    # Найти или создать пользователя
    user = db.query(User).filter(
        (User.oauth_provider == "github") & (User.oauth_id == gh_id)
    ).first()
    if not user:
        user = db.query(User).filter(User.email == primary_email).first()
    if not user:
        user = User(
            username=username,
            email=primary_email,
            oauth_provider="github",
            oauth_id=gh_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.oauth_provider:
        user.oauth_provider = "github"
        user.oauth_id = gh_id
        db.commit()

    return _set_auth_cookies(user)


# Google OAuth

@router.get("/auth/google")
def google_login(request: Request):
    if not GOOGLE_CLIENT_ID:
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Google OAuth не настроен (GOOGLE_CLIENT_ID пуст)"
        }, status_code=400)
    redirect_uri = str(request.url_for("google_callback"))
    return RedirectResponse(
        f"https://accounts.google.com/o/oauth2/v2/auth?client_id={GOOGLE_CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code&scope=openid+email+profile"
    )


@router.get("/auth/google/callback")
async def google_callback(request: Request, code: str, db: Session = Depends(get_db)):
    redirect_uri = str(request.url_for("google_callback"))
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return templates.TemplateResponse("login.html", {
                "request": request, "error": "Ошибка Google OAuth"
            }, status_code=400)

        user_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        g_user = user_resp.json()

    email = g_user.get("email")
    if not email:
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Не удалось получить email из Google"
        }, status_code=400)

    g_id = str(g_user["id"])
    username = g_user.get("name", email.split("@")[0])

    user = db.query(User).filter(
        (User.oauth_provider == "google") & (User.oauth_id == g_id)
    ).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            username=username,
            email=email,
            oauth_provider="google",
            oauth_id=g_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.oauth_provider:
        user.oauth_provider = "google"
        user.oauth_id = g_id
        db.commit()

    return _set_auth_cookies(user)
