-- Схема базы данных FilmRec
-- 7 таблиц: users, movies, genres, movie_genres, ratings, favorites, item_similarity

-- ============================================================================
-- Предметная область
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id    BIGSERIAL PRIMARY KEY,
    username   VARCHAR(255) UNIQUE NOT NULL,
    email      VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),  -- NULL для OAuth-аккаунтов
    oauth_provider VARCHAR(50),  -- 'google', 'github' или NULL
    oauth_id   VARCHAR(255),
    role       VARCHAR(20) NOT NULL DEFAULT 'user'
                   CHECK (role IN ('user', 'moderator', 'admin')),
    status     VARCHAR(20) NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'blocked')),
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS movies (
    movie_id   BIGSERIAL PRIMARY KEY,
    title      VARCHAR(500) NOT NULL,
    year       INTEGER,
    description TEXT,
    tmdb_id    INTEGER,
    poster_path VARCHAR(255),
    avg_rating FLOAT NOT NULL DEFAULT 0.0,
    ratings_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS genres (
    genre_id   BIGSERIAL PRIMARY KEY,
    name       VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS movie_genres (
    movie_id   BIGINT NOT NULL REFERENCES movies(movie_id) ON DELETE CASCADE,
    genre_id   BIGINT NOT NULL REFERENCES genres(genre_id) ON DELETE CASCADE,
    PRIMARY KEY (movie_id, genre_id)
);

CREATE TABLE IF NOT EXISTS ratings (
    rating_id  BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    movie_id   BIGINT NOT NULL REFERENCES movies(movie_id) ON DELETE CASCADE,
    rating     FLOAT NOT NULL CHECK (rating >= 0.5 AND rating <= 5.0),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    -- Порядок (movie_id, user_id) выбран намеренно: создаваемый PostgreSQL
    -- автоматический индекс по этому ограничению поддерживает поиск по
    -- movie_id, но не по user_id. Для запросов «оценки пользователя»
    -- (онлайн-этап рек-сервиса) необходим отдельный индекс на user_id -
    -- создаётся на итерации 1 плана оптимизации (см. §2.5).
    UNIQUE (movie_id, user_id)
);

CREATE TABLE IF NOT EXISTS favorites (
    favorite_id BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    movie_id   BIGINT NOT NULL REFERENCES movies(movie_id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (user_id, movie_id)
);

-- ============================================================================
-- Рекомендательный сервис
-- ============================================================================

CREATE TABLE IF NOT EXISTS item_similarity (
    movie_id         BIGINT NOT NULL REFERENCES movies(movie_id) ON DELETE CASCADE,
    similar_movie_id BIGINT NOT NULL REFERENCES movies(movie_id) ON DELETE CASCADE,
    similarity       FLOAT NOT NULL CHECK (similarity >= 0.0 AND similarity <= 1.0),
    updated_at       TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (movie_id, similar_movie_id)
);

-- ============================================================================
-- Индексы
-- ============================================================================

-- Индекс на ratings(user_id) намеренно НЕ создаётся в схеме итерации 0 -
-- его создание относится к итерации 1 плана оптимизации (см. §2.5).
-- Поиск по movie_id обеспечивается автоматическим индексом по UNIQUE
-- (movie_id, user_id), отдельный idx_ratings_movie_id не требуется.
CREATE INDEX IF NOT EXISTS idx_favorites_user_id ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_item_similarity_movie_id ON item_similarity(movie_id);
CREATE INDEX IF NOT EXISTS idx_movies_tmdb_id ON movies(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
