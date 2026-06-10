package handler

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"rec-service/internal/config"
	"rec-service/internal/database"
	"rec-service/internal/model"
	"rec-service/internal/recommender"
)

type Handler struct {
	Cfg   *config.Config
	Model *model.SimilarityModel
}

func New(cfg *config.Config, sim *model.SimilarityModel) *Handler {
	return &Handler{Cfg: cfg, Model: sim}
}

func (h *Handler) GetRecommendations(c *gin.Context) {
	userID, err := strconv.Atoi(c.Param("user_id"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "некорректный user_id"})
		return
	}

	n, _ := strconv.Atoi(c.DefaultQuery("n", strconv.Itoa(h.Cfg.RecNDefault)))
	if n < 1 || n > 100 {
		n = 10
	}

	results, err := recommender.Recommend(h.Model, userID, n)
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

	n, _ := strconv.Atoi(c.DefaultQuery("n", strconv.Itoa(h.Cfg.RecNDefault)))
	if n < 1 || n > 100 {
		n = 10
	}

	results, err := recommender.RecommendPopular(userID, n, nil)
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

	// Получаем названия фильмов
	movieIDs := make([]int, len(neighbors))
	for i, nb := range neighbors {
		movieIDs[i] = nb.MovieID
	}
	titles, err := database.FetchMovieTitles(movieIDs)
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
