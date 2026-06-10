"""Панель администратора: роли пользователей, управление фильмами, метрики."""

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.middleware import require_role
from app.models import get_db, User, Movie, Genre, MovieGenre
from app.routers.catalog import GENRE_RU

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def admin_panel(
    request: Request,
    tab: str = "users",
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    movies = db.query(Movie).order_by(Movie.movie_id.desc()).limit(50).all()
    genres = db.query(Genre).order_by(Genre.name).all()
    for g in genres:
        g.name_ru = GENRE_RU.get(g.name, g.name)
    for m in movies:
        for g in m.genres:
            g.name_ru = GENRE_RU.get(g.name, g.name)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "users": users,
        "movies": movies,
        "genres": genres,
        "tab": tab,
    })


@router.post("/role/{target_id}")
def change_role(
    request: Request,
    target_id: int,
    role: str = Form(...),
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if role not in ("user", "moderator", "admin"):
        return RedirectResponse(url="/admin/?tab=users", status_code=302)

    target = db.query(User).filter(User.user_id == target_id).first()
    if target and target.user_id != user.user_id:
        target.role = role
        db.commit()

    return RedirectResponse(url="/admin/?tab=users", status_code=302)


@router.post("/movie/add")
def add_movie(
    request: Request,
    title: str = Form(...),
    year: int | None = Form(None),
    description: str | None = Form(None),
    tmdb_id: int | None = Form(None),
    genre_ids: list[int] = Form(default=[]),
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    movie = Movie(title=title, year=year, description=description, tmdb_id=tmdb_id)
    db.add(movie)
    db.flush()

    for gid in genre_ids:
        db.add(MovieGenre(movie_id=movie.movie_id, genre_id=gid))

    db.commit()
    return RedirectResponse(url="/admin/?tab=movies", status_code=302)


@router.get("/movie/edit/{movie_id}")
def edit_movie_form(
    request: Request,
    movie_id: int,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    movie = db.query(Movie).filter(Movie.movie_id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404)
    genres = db.query(Genre).order_by(Genre.name).all()
    movie_genre_ids = [g.genre_id for g in movie.genres]
    return templates.TemplateResponse("admin_edit_movie.html", {
        "request": request, "user": user, "movie": movie,
        "genres": genres, "movie_genre_ids": movie_genre_ids,
    })


@router.post("/movie/edit/{movie_id}")
def edit_movie(
    request: Request,
    movie_id: int,
    title: str = Form(...),
    year: int = Form(None),
    description: str = Form(""),
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    movie = db.query(Movie).filter(Movie.movie_id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404)
    movie.title = title
    movie.year = year
    movie.description = description
    db.commit()
    return RedirectResponse(url="/admin/?tab=movies", status_code=302)


@router.post("/movie/delete/{movie_id}")
def delete_movie(
    request: Request,
    movie_id: int,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    movie = db.query(Movie).filter(Movie.movie_id == movie_id).first()
    if movie:
        db.delete(movie)
        db.commit()
    return RedirectResponse(url="/admin/?tab=movies", status_code=302)
