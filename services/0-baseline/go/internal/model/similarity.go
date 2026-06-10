package model

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
)

type Neighbor struct {
	MovieID    int
	Similarity float64
}

type SimilarityModel struct {
	mu          sync.RWMutex
	data        map[int][]Neighbor // movie_id -> отсортированные соседи
	loaded      bool
	loadTimeSec float64
}

func New() *SimilarityModel {
	return &SimilarityModel{
		data: make(map[int][]Neighbor),
	}
}

func (m *SimilarityModel) Load(dbURL string) error {
	start := time.Now()

	conn, err := pgx.Connect(context.Background(), dbURL)
	if err != nil {
		return fmt.Errorf("подключение: %w", err)
	}
	defer conn.Close(context.Background())

	rows, err := conn.Query(context.Background(),
		"SELECT movie_id, similar_movie_id, similarity FROM item_similarity ORDER BY movie_id, similarity DESC")
	if err != nil {
		return fmt.Errorf("запрос: %w", err)
	}
	defer rows.Close()

	data := make(map[int][]Neighbor)
	count := 0
	for rows.Next() {
		var movieID, similarID int
		var sim float64
		if err := rows.Scan(&movieID, &similarID, &sim); err != nil {
			return fmt.Errorf("чтение строки: %w", err)
		}
		data[movieID] = append(data[movieID], Neighbor{MovieID: similarID, Similarity: sim})
		count++
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("перебор строк: %w", err)
	}

	m.mu.Lock()
	m.data = data
	m.loaded = true
	m.loadTimeSec = time.Since(start).Seconds()
	m.mu.Unlock()

	log.Printf("Модель загружена: %d фильмов, %d пар, %.1fс", len(data), count, m.loadTimeSec)
	return nil
}

func (m *SimilarityModel) GetNeighbors(movieID int) []Neighbor {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.data[movieID]
}

func (m *SimilarityModel) HasMovie(movieID int) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	_, ok := m.data[movieID]
	return ok
}

func (m *SimilarityModel) IsLoaded() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.loaded
}

func (m *SimilarityModel) LoadTime() float64 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.loadTimeSec
}
