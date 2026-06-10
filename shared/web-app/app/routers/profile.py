"""Маршруты профиля пользователя: оценки, избранное, действия с оценками и избранным."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.middleware import get_current_user
from app.models import get_db, User, Rating, Favorite, Movie

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/profile", response_class=HTMLResponse)
def profile(
    request: Request,
    tab: str = "ratings",
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    ratings = (
        db.query(Rating, Movie)
        .join(Movie, Rating.movie_id == Movie.movie_id)
        .filter(Rating.user_id == user.user_id)
        .order_by(Rating.created_at.desc())
        .all()
    )

    favorites = (
        db.query(Favorite, Movie)
        .join(Movie, Favorite.movie_id == Movie.movie_id)
        .filter(Favorite.user_id == user.user_id)
        .order_by(Favorite.created_at.desc())
        .all()
    )

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "ratings": ratings,
        "favorites": favorites,
        "tab": tab,
        "ratings_count": len(ratings),
        "favorites_count": len(favorites),
    })


@router.post("/rate/{movie_id}")
def rate_movie(
    request: Request,
    movie_id: int,
    rating: float = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rating = max(1.0, min(5.0, rating))

    existing = (
        db.query(Rating)
        .filter(Rating.user_id == user.user_id, Rating.movie_id == movie_id)
        .first()
    )
    if existing:
        existing.rating = rating
    else:
        db.add(Rating(user_id=user.user_id, movie_id=movie_id, rating=rating))

    db.commit()

    # Пересчёт среднего рейтинга фильма
    result = db.query(
        func.avg(Rating.rating), func.count(Rating.rating_id)
    ).filter(Rating.movie_id == movie_id).first()

    movie = db.query(Movie).filter(Movie.movie_id == movie_id).first()
    if movie and result[0]:
        movie.avg_rating = float(result[0])
        movie.ratings_count = result[1]
        db.commit()

    return RedirectResponse(url=f"/movie/{movie_id}", status_code=302)


@router.post("/favorite/{movie_id}")
def toggle_favorite(
    request: Request,
    movie_id: int,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    existing = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.user_id, Favorite.movie_id == movie_id)
        .first()
    )
    if existing:
        db.delete(existing)
    else:
        db.add(Favorite(user_id=user.user_id, movie_id=movie_id))

    db.commit()
    return RedirectResponse(url=f"/movie/{movie_id}", status_code=302)
