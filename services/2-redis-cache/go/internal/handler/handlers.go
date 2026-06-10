// Пакет handler - HTTP-обработчики, использующие переданный pgxpool
// и кэш Redis (итерация 2, §2.5).
package handler

import (
	"net/http"
	"strconv"
	"sync"
	"sync/atomic"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"rec-service/internal/cache"
	"rec-service/internal/config"
	"rec-service/internal/database"
	"rec-service/internal/model"
	"rec-service/internal/recommender"
)

// Уникальные пользователи, попавшие в запросы за прогон. Считается так же, как
// кэш-хиты: счётчик в приложении, отдаётся через /metrics и снимается Prometheus.
// Показывает концентрацию нагрузки и объясняет эффективность кэша (§3.4).
var (
	uniqueUsers int64
	seenUsers   sync.Map
	_           = promauto.NewGaugeFunc(prometheus.GaugeOpts{
		Name: "rec_unique_users",
		Help: "Уникальных пользователей в запросах за прогон",
	}, func() float64 { return float64(atomic.LoadInt64(&uniqueUsers)) })
)

// observeUser учитывает пользователя в метрике уникальных (идемпотентно, без блокировок).
func observeUser(userID int) {
	if _, loaded := seenUsers.LoadOrStore(userID, struct{}{}); !loaded {
		atomic.AddInt64(&uniqueUsers, 1)
	}
}

type Handler struct {
	Cfg   *config.Config
	Pool  *pgxpool.Pool
	Cache *cache.Cache
	Model *model.SimilarityModel
}

func New(cfg *config.Config, pool *pgxpool.Pool, c *cache.Cache, sim *model.SimilarityModel) *Handler {
	return &Handler{Cfg: cfg, Pool: pool, Cache: c, Model: sim}
}

func (h *Handler) GetRecommendations(c *gin.Context) {
	userID, err := strconv.Atoi(c.Param("user_id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "некорректный user_id"})
		return
	}
	observeUser(userID)

	n, _ := strconv.Atoi(c.DefaultQuery("n", strconv.Itoa(h.Cfg.RecNDefault)))
	if n < 1 || n > 100 {
		n = 10
	}

	results, err := recommender.Recommend(c.Request.Context(), h.Pool, h.Cache, h.Model, userID, n)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	c.JSON(http.StatusOK, results)
}

func (h *Handler) GetPopular(c *gin.Context) {
	userID, err := strconv.Atoi(c.Param("user_id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "некорректный user_id"})
		return
	}
	observeUser(userID)

	n, _ := strconv.Atoi(c.DefaultQuery("n", strconv.Itoa(h.Cfg.RecNDefault)))
	if n < 1 || n > 100 {
		n = 10
	}

	results, err := recommender.RecommendPopular(c.Request.Context(), h.Pool, h.Cache, userID, n, nil)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	c.JSON(http.StatusOK, results)
}

type SimilarMovieResponse struct {
	MovieID    int     `json:"movie_id"`
	Title      string  `json:"title"`
	Similarity float64 `json:"similarity"`
}

func (h *Handler) GetSimilar(c *gin.Context) {
	movieID, err := strconv.Atoi(c.Param("movie_id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "некорректный movie_id"})
		return
	}

	n, _ := strconv.Atoi(c.DefaultQuery("n", "6"))
	if n < 1 {
		n = 6
	}
	if n > 100 {
		n = 100
	}

	if !h.Model.HasMovie(movieID) {
		c.JSON(http.StatusNotFound, gin.H{"detail": "Фильм не найден в модели сходства"})
		return
	}

	neighbors := h.Model.GetNeighbors(movieID)
	if len(neighbors) > n {
		neighbors = neighbors[:n]
	}

	movieIDs := make([]int, len(neighbors))
	for i, nb := range neighbors {
		movieIDs[i] = nb.MovieID
	}
	titles, err := database.FetchMovieTitles(c.Request.Context(), h.Pool, movieIDs)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}

	results := make([]SimilarMovieResponse, len(neighbors))
	for i, nb := range neighbors {
		results[i] = SimilarMovieResponse{
			MovieID:    nb.MovieID,
			Title:      titles[nb.MovieID],
			Similarity: nb.Similarity,
		}
	}

	c.JSON(http.StatusOK, results)
}

func (h *Handler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":       "ok",
		"model_loaded": h.Model.IsLoaded(),
	})
}

func (h *Handler) Metrics() gin.HandlerFunc {
	return gin.WrapH(promhttp.Handler())
}
