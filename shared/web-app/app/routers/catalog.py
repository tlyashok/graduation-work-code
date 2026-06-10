"""Маршруты каталога фильмов: главная страница, каталог, карточка фильма."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.middleware import get_current_user
from app.models import get_db, Movie, Genre, MovieGenre, Rating, Favorite, User

GENRE_RU = {
    "Action": "Боевик", "Adventure": "Приключения", "Animation": "Анимация",
    "Children": "Детский", "Comedy": "Комедия", "Crime": "Криминал",
    "Documentary": "Документальный", "Drama": "Драма", "Fantasy": "Фэнтези",
    "Film-Noir": "Нуар", "Horror": "Ужасы", "IMAX": "IMAX",
    "Musical": "Мюзикл", "Mystery": "Детектив", "Romance": "Мелодрама",
    "Sci-Fi": "Фантастика", "Thriller": "Триллер", "War": "Военный",
    "Western": "Вестерн",
}
from app.services.rec_client import get_recommendations, get_popular, get_similar

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)

    recommendations = []
    if user:
        raw_recs = await get_recommendations(user.user_id, n=12)
        if raw_recs:
            rec_ids = [r["movie_id"] for r in raw_recs]
            movies_map = {m.movie_id: m for m in db.query(Movie).filter(Movie.movie_id.in_(rec_ids)).all()}
            for r in raw_recs:
                movie = movies_map.get(r["movie_id"])
                if movie:
                    r["poster_path"] = movie.poster_path
                    r["year"] = movie.year
            recommendations = raw_recs

    # Популярные фильмы (через рекомендательный сервис; для анонимов user_id=0)
    popular = []
    raw_popular = await get_popular(user.user_id if user else 0, n=12)
    if raw_popular:
        pop_ids = [r["movie_id"] for r in raw_popular]
        movies_map = {m.movie_id: m for m in db.query(Movie).filter(Movie.movie_id.in_(pop_ids)).all()}
        for r in raw_popular:
            movie = movies_map.get(r["movie_id"])
            if movie:
                r["poster_path"] = movie.poster_path
                r["year"] = movie.year
        popular = raw_popular

    # Лучшие по рейтингу
    top_rated = (
        db.query(Movie)
        .filter(Movie.ratings_count >= 50)
        .order_by(Movie.avg_rating.desc())
        .limit(12)
        .all()
    )

    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "recommendations": recommendations,
        "popular": popular,
        "top_rated": top_rated,
    })


def _to_int(val: str | None) -> int | None:
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None

def _to_float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


@router.get("/catalog", response_class=HTMLResponse)
def catalog(
    request: Request,
    page: str = "1",
    genre: list[str] = Query(default=[]),
    year_from: str = "",
    year_to: str = "",
    min_rating: str = "",
    sort: str = "popular",
    q: str = "",
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    per_page = 24

    page_num = _to_int(page) or 1
    genre_ids = [int(g) for g in genre if g.isdigit()]
    year_from_val = _to_int(year_from)
    year_to_val = _to_int(year_to)
    min_rating_val = _to_float(min_rating)

    query = db.query(Movie).filter(Movie.ratings_count > 0)

    if q:
        query = query.filter(Movie.title.ilike(f"%{q}%"))
    if genre_ids:
        query = query.join(MovieGenre).filter(MovieGenre.genre_id.in_(genre_ids))
    if year_from_val:
        query = query.filter(Movie.year >= year_from_val)
    if year_to_val:
        query = query.filter(Movie.year <= year_to_val)
    if min_rating_val:
        query = query.filter(Movie.avg_rating >= min_rating_val)

    total = query.count()

    if sort == "rating":
        query = query.order_by(Movie.avg_rating.desc())
    elif sort == "year":
        query = query.order_by(Movie.year.desc().nullslast())
    else:  # по популярности
        query = query.order_by(
            (Movie.avg_rating * func.ln(func.greatest(Movie.ratings_count, 1))).desc()
        )

    movies = query.offset((page_num - 1) * per_page).limit(per_page).all()
    genres = db.query(Genre).filter(Genre.name != "(no genres listed)").order_by(Genre.name).all()
    total_pages = (total + per_page - 1) // per_page

    # Добавить русские названия жанров
    for g in genres:
        g.name_ru = GENRE_RU.get(g.name, g.name)

    return templates.TemplateResponse("catalog.html", {
        "request": request,
        "user": user,
        "movies": movies,
        "genres": genres,
        "page": page_num,
        "total_pages": total_pages,
        "total": total,
        "genre_ids": genre_ids,
        "year_from": year_from_val,
        "year_to": year_to_val,
        "min_rating": min_rating_val,
        "sort": sort,
        "q": q,
    })


@router.get("/movie/{movie_id}", response_class=HTMLResponse)
async def movie_detail(
    request: Request,
    movie_id: int,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    movie = db.query(Movie).filter(Movie.movie_id == movie_id).first()
    if not movie:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    genres = (
        db.query(Genre)
        .join(MovieGenre)
        .filter(MovieGenre.movie_id == movie_id)
        .all()
    )
    for g in genres:
        g.name_ru = GENRE_RU.get(g.name, g.name)

    user_rating = None
    is_favorite = False
    similar_movies = []

    if user:
        rating_obj = (
            db.query(Rating)
            .filter(Rating.user_id == user.user_id, Rating.movie_id == movie_id)
            .first()
        )
        user_rating = rating_obj.rating if rating_obj else None

        fav = (
            db.query(Favorite)
            .filter(Favorite.user_id == user.user_id, Favorite.movie_id == movie_id)
            .first()
        )
        is_favorite = fav is not None

    # Похожие фильмы - из item_similarity, не зависят от пользователя
    raw_similar = await get_similar(movie_id, n=6)
    if raw_similar:
        sim_ids = [s["movie_id"] for s in raw_similar]
        sim_map = {m.movie_id: m for m in db.query(Movie).filter(Movie.movie_id.in_(sim_ids)).all()}
        for s in raw_similar:
            movie_obj = sim_map.get(s["movie_id"])
            if movie_obj:
                s["poster_path"] = movie_obj.poster_path
                s["year"] = movie_obj.year
        similar_movies = raw_similar

    return templates.TemplateResponse("movie.html", {
        "request": request,
        "user": user,
        "movie": movie,
        "genres": genres,
        "user_rating": user_rating,
        "is_favorite": is_favorite,
        "similar_movies": similar_movies,
    })
