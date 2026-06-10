// Пакет cache - обёртка над Redis для итерации 2 (§2.5).
//
// Стратегия - ленивая загрузка (cache-aside):
//   - Get возвращает закэшированное значение либо ошибку redis.Nil
//     при промахе;
//   - Set сохраняет значение с заданным TTL.
//
// Сериализация - JSON (тот же формат, в котором сервис отдаёт ответ
// клиенту), чтобы попадание в кэш можно было отдать без пересборки.
package cache

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/redis/go-redis/v9"
)

var (
	cacheHits = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "rec_cache_hits_total",
		Help: "Попадания в кэш",
	}, []string{"kind"})
	cacheMisses = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "rec_cache_misses_total",
		Help: "Промахи кэша",
	}, []string{"kind"})
)

type Cache struct {
	client *redis.Client
	ttl    time.Duration
}

// New создаёт клиента Redis по DSN-строке (redis://host:port/db).
// Делает Ping для проверки соединения на старте.
func New(ctx context.Context, redisURL string, ttlSeconds int) (*Cache, error) {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, fmt.Errorf("разбор адреса Redis: %w", err)
	}
	client := redis.NewClient(opts)
	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("проверка доступности Redis: %w", err)
	}
	return &Cache{
		client: client,
		ttl:    time.Duration(ttlSeconds) * time.Second,
	}, nil
}

func (c *Cache) Close() error {
	return c.client.Close()
}

func key(prefix string, userID, n int) string {
	return fmt.Sprintf("%s:%d:n=%d", prefix, userID, n)
}

// Get десериализует JSON-значение в out. Возвращает true при попадании
// в кэш, false при промахе (включая ошибку redis.Nil). Любая другая
// ошибка возвращается явно.
func (c *Cache) Get(ctx context.Context, prefix string, userID, n int, out any) (bool, error) {
	raw, err := c.client.Get(ctx, key(prefix, userID, n)).Bytes()
	if err == redis.Nil {
		cacheMisses.WithLabelValues(prefix).Inc()
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return false, err
	}
	cacheHits.WithLabelValues(prefix).Inc()
	return true, nil
}

// Set сериализует value в JSON и сохраняет с TTL.
func (c *Cache) Set(ctx context.Context, prefix string, userID, n int, value any) error {
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}
	return c.client.Set(ctx, key(prefix, userID, n), raw, c.ttl).Err()
}
