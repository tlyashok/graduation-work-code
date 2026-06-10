package database

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Итерация 0: pgxpool с фиксированным размером 5.

var pool *pgxpool.Pool

// InitPool создаёт пул соединений (вызывается из main на старте).
func InitPool(dbURL string) error {
	cfg, err := pgxpool.ParseConfig(dbURL)
	if err != nil {
		return fmt.Errorf("разбор конфигурации: %w", err)
	}
	cfg.MinConns = 5
	cfg.MaxConns = 5

	p, err := pgxpool.NewWithConfig(context.Background(), cfg)
	if err != nil {
		return fmt.Errorf("создание пула: %w", err)
	}
	pool = p
	return nil
}

// ClosePool закрывает пул (вызывается при остановке).
func ClosePool() {
	if pool != nil {
		pool.Close()
		pool = nil
	}
}

type Rating struct {
	MovieID int
	Rating  float64
}

type PopularMovie struct {
	MovieID   int
	Title     string
	AvgRating float64
}

func FetchUserRatings(userID int) ([]Rating, error) {
	rows, err := pool.Query(context.Background(),
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

func FetchPopularMovies(excludeIDs map[int]bool, n int) ([]PopularMovie, error) {
	rows, err := pool.Query(context.Background(), `
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

func FetchMovieTitles(movieIDs []int) (map[int]string, error) {
	if len(movieIDs) == 0 {
		return map[int]string{}, nil
	}
	rows, err := pool.Query(context.Background(),
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
