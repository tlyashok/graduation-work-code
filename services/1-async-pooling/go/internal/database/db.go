// Пакет database - итерация 1: pgxpool, переиспользование соединений.
//
// Глобальный пул создаётся в main.go и передаётся в обработчики через DI.
// Размер пула фиксирован (MinConns=MaxConns=10), см. §2.5.
package database

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Rating struct {
	MovieID int
	Rating  float64
}

type PopularMovie struct {
	MovieID   int
	Title     string
	AvgRating float64
}

// NewPool создаёт пул соединений с заданными MinConns/MaxConns
// и обеспечивает наличие индекса по ratings.user_id (см. §3.3).
func NewPool(ctx context.Context, dbURL string, minConns, maxConns int32) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(dbURL)
	if err != nil {
		return nil, fmt.Errorf("разбор конфигурации: %w", err)
	}
	cfg.MinConns = minConns
	cfg.MaxConns = maxConns
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("создание пула: %w", err)
	}
	// Индекс по ratings.user_id - часть итерации 1 по объединённому плану §2.5.
	// Без него пул из 10 соединений упирается в последовательный скан таблицы
	// ratings (25 млн строк), и устранение накладных расходов на установление
	// соединения не даёт прироста пропускной способности.
	if _, err := pool.Exec(ctx,
		"CREATE INDEX IF NOT EXISTS idx_ratings_user_id ON ratings(user_id)"); err != nil {
		pool.Close()
		return nil, fmt.Errorf("создание индекса: %w", err)
	}
	// Индекс под /popular: ранжирование по популярности было seq scan'ом всех 62К
	// фильмов на каждый запрос (узкое место БД при высоком RPS Go). Частичный
	// индекс по выражению превращает ORDER BY ... LIMIT в index scan.
	if _, err := pool.Exec(ctx,
		"CREATE INDEX IF NOT EXISTS idx_movies_popularity ON movies "+
			"((avg_rating * ln(ratings_count + 1)) DESC) WHERE ratings_count > 0"); err != nil {
		pool.Close()
		return nil, fmt.Errorf("создание индекса популярности: %w", err)
	}
	return pool, nil
}

func FetchUserRatings(ctx context.Context, pool *pgxpool.Pool, userID int) ([]Rating, error) {
	rows, err := pool.Query(ctx,
		"SELECT movie_id, rating FROM ratings WHERE user_id = $1", userID)
	if err != nil {
		return nil, fmt.Errorf("запрос оценок: %w", err)
	}
	defer rows.Close()

	var ratings []Rating
	for rows.Next() {
		var r Rating
		if err := rows.Scan(&r.MovieID, &r.Rating); err != nil {
			return nil, fmt.Errorf("чтение строки: %w", err)
		}
		ratings = append(ratings, r)
	}
	return ratings, rows.Err()
}

func FetchPopularMovies(ctx context.Context, pool *pgxpool.Pool, excludeIDs map[int]bool, n int) ([]PopularMovie, error) {
	// Сортировка по avg * ln(count + 1), но в выдачу идёт avg_rating -
	// для согласованной шкалы [0, 5] в поле predicted_rating ответа.
	rows, err := pool.Query(ctx, `
		SELECT movie_id, title, avg_rating
		FROM movies
		WHERE ratings_count > 0
		ORDER BY avg_rating * ln(ratings_count + 1) DESC
		LIMIT $1`, n+len(excludeIDs))
	if err != nil {
		return nil, fmt.Errorf("запрос популярных фильмов: %w", err)
	}
	defer rows.Close()

	var results []PopularMovie
	for rows.Next() {
		var m PopularMovie
		if err := rows.Scan(&m.MovieID, &m.Title, &m.AvgRating); err != nil {
			return nil, fmt.Errorf("чтение строки: %w", err)
		}
		if !excludeIDs[m.MovieID] && len(results) < n {
			results = append(results, m)
		}
	}
	return results, rows.Err()
}

func FetchMovieTitles(ctx context.Context, pool *pgxpool.Pool, movieIDs []int) (map[int]string, error) {
	if len(movieIDs) == 0 {
		return map[int]string{}, nil
	}
	rows, err := pool.Query(ctx,
		"SELECT movie_id, title FROM movies WHERE movie_id = ANY($1)", movieIDs)
	if err != nil {
		return nil, fmt.Errorf("запрос названий фильмов: %w", err)
	}
	defer rows.Close()

	titles := make(map[int]string)
	for rows.Next() {
		var id int
		var title string
		if err := rows.Scan(&id, &title); err != nil {
			return nil, fmt.Errorf("чтение строки: %w", err)
		}
		titles[id] = title
	}
	return titles, rows.Err()
}
