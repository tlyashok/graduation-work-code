"""Подключение к базе данных и модели SQLAlchemy."""

from sqlalchemy import (
    create_engine, Column, BigInteger, String, Float, Integer,
    Text, DateTime, ForeignKey, UniqueConstraint, CheckConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "users"

    user_id = Column(BigInteger, primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    oauth_provider = Column(String(50), nullable=True)
    oauth_id = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False, default="user")
    status = Column(String(20), nullable=False, default="active")
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    ratings = relationship("Rating", back_populates="user")
    favorites = relationship("Favorite", back_populates="user")


class Movie(Base):
    __tablename__ = "movies"

    movie_id = Column(BigInteger, primary_key=True)
    title = Column(String(500), nullable=False)
    year = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    tmdb_id = Column(Integer, nullable=True)
    poster_path = Column(String(255), nullable=True)
    avg_rating = Column(Float, nullable=False, default=0.0)
    ratings_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    genres = relationship("Genre", secondary="movie_genres", back_populates="movies")
    ratings = relationship("Rating", back_populates="movie")


class Genre(Base):
    __tablename__ = "genres"

    genre_id = Column(BigInteger, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)

    movies = relationship("Movie", secondary="movie_genres", back_populates="genres")


class MovieGenre(Base):
    __tablename__ = "movie_genres"

    movie_id = Column(BigInteger, ForeignKey("movies.movie_id", ondelete="CASCADE"), primary_key=True)
    genre_id = Column(BigInteger, ForeignKey("genres.genre_id", ondelete="CASCADE"), primary_key=True)


class Rating(Base):
    __tablename__ = "ratings"

    rating_id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(BigInteger, ForeignKey("movies.movie_id", ondelete="CASCADE"), nullable=False)
    rating = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("movie_id", "user_id"),)

    user = relationship("User", back_populates="ratings")
    movie = relationship("Movie", back_populates="ratings")


class Favorite(Base):
    __tablename__ = "favorites"

    favorite_id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    movie_id = Column(BigInteger, ForeignKey("movies.movie_id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("movie_id", "user_id"),)

    user = relationship("User", back_populates="favorites")
    movie = relationship("Movie")
