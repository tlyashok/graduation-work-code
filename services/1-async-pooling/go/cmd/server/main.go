package main

import (
	"context"
	"log"
	"time"

	"github.com/gin-contrib/pprof"
	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	"rec-service/internal/config"
	"rec-service/internal/database"
	"rec-service/internal/handler"
	"rec-service/internal/model"
	"rec-service/internal/recommender"
)

var (
	requestCount = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "rec_requests_total",
		Help: "Общее число запросов",
	}, []string{"method", "endpoint", "status"})

	requestDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "rec_request_duration_seconds",
		Help:    "Длительность обработки запроса, секунды",
		Buckets: []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0},
	}, []string{"method", "endpoint"})

	requestErrors = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "rec_errors_total",
		Help: "Общее число ошибок",
	}, []string{"method", "endpoint"})

	modelLoadTime = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "rec_model_load_time_seconds",
		Help: "Время загрузки модели сходства, секунды",
	})
)

func metricsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		duration := time.Since(start).Seconds()

		endpoint := c.FullPath()
		if endpoint == "" {
			endpoint = c.Request.URL.Path
		}
		method := c.Request.Method
		status := string(rune('0'+c.Writer.Status()/100)) + "xx"

		requestCount.WithLabelValues(method, endpoint, status).Inc()
		requestDuration.WithLabelValues(method, endpoint).Observe(duration)
		if c.Writer.Status() >= 500 {
			requestErrors.WithLabelValues(method, endpoint).Inc()
		}
	}
}

func main() {
	cfg := config.Load()

	// Пул соединений к PostgreSQL (итерация 1, §2.5).
	ctx := context.Background()
	pool, err := database.NewPool(ctx, cfg.DatabaseURL, cfg.DBPoolMinConns, cfg.DBPoolMaxConns)
	if err != nil {
		log.Fatalf("Ошибка создания пула: %v", err)
	}
	defer pool.Close()

	// Загрузка модели сходства (через тот же пул)
	sim := model.New()
	if err := sim.Load(ctx, pool); err != nil {
		log.Fatalf("Ошибка загрузки модели: %v", err)
	}
	modelLoadTime.Set(sim.LoadTime())

	recommender.MinRatingsForPersonal = cfg.RecMinRatings
	h := handler.New(cfg, pool, sim)

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(metricsMiddleware())

	r.GET("/recommendations/:user_id", h.GetRecommendations)
	r.GET("/recommendations/:user_id/popular", h.GetPopular)
	r.GET("/similar/:movie_id", h.GetSimilar)
	r.GET("/health", h.Health)
	r.GET("/metrics", h.Metrics())

	// pprof: /debug/pprof/profile, /heap, /goroutine - для отдельных
	// профилировочных прогонов (§3.1).
	pprof.Register(r)

	addr := cfg.Host + ":" + cfg.Port
	log.Printf("Сервер запущен: %s (пул: %d-%d соединений)", addr, cfg.DBPoolMinConns, cfg.DBPoolMaxConns)
	if err := r.Run(addr); err != nil {
		log.Fatalf("Ошибка запуска сервера: %v", err)
	}
}
