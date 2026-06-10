// Пакет recommender: алгоритм коллаборативной фильтрации (item-based).
//
// Алгоритм идентичен этапу 0; единственное отличие в том, что обращения
// к БД идут через переданный pgxpool, а не открывают новое соединение.
package recommender

import (
	"context"
	"math"
	"sort"

	"github.com/jackc/pgx/v5/pgxpool"

	"rec-service/internal/database"
	"rec-service/internal/model"
)

var MinRatingsForPersonal = 5

type Recommendation struct {
	MovieID         int     `json:"movie_id"`
	Title           string  `json:"title"`
	PredictedRating float64 `json:"predicted_rating"`
}

func Recommend(ctx context.Context, pool *pgxpool.Pool, sim *model.SimilarityModel, userID, n int) ([]Recommendation, error) {
	ratings, err := database.FetchUserRatings(ctx, pool, userID)
	if err != nil {
		return nil, err
	}

	if len(ratings) < MinRatingsForPersonal {
		return RecommendPopular(ctx, pool, userID, n, ratings)
	}

	return itemBasedCF(ctx, pool, sim, ratings, n)
}

func RecommendPopular(ctx context.Context, pool *pgxpool.Pool, userID, n int, ratings []database.Rating) ([]Recommendation, error) {
	if ratings == nil {
		var err error
		ratings, err = database.FetchUserRatings(ctx, pool, userID)
		if err != nil {
			return nil, err
		}
	}

	excludeIDs := make(map[int]bool)
	for _, r := range ratings {
		excludeIDs[r.MovieID] = true
	}

	popular, err := database.FetchPopularMovies(ctx, pool, excludeIDs, n)
	if err != nil {
		return nil, err
	}

	results := make([]Recommendation, 0, len(popular))
	for _, m := range popular {
		results = append(results, Recommendation{
			MovieID:         m.MovieID,
			Title:           m.Title,
			PredictedRating: math.Round(m.AvgRating*100) / 100,
		})
	}
	return results, nil
}

type candidate struct {
	movieID   int
	score     float64
	weightSum float64
}

func itemBasedCF(ctx context.Context, pool *pgxpool.Pool, sim *model.SimilarityModel, ratings []database.Rating, n int) ([]Recommendation, error) {
	ratedIDs := make(map[int]bool)
	for _, r := range ratings {
		ratedIDs[r.MovieID] = true
	}

	candidates := make(map[int]*candidate)

	for _, r := range ratings {
		neighbors := sim.GetNeighbors(r.MovieID)
		for _, nb := range neighbors {
			if ratedIDs[nb.MovieID] {
				continue
			}
			c, ok := candidates[nb.MovieID]
			if !ok {
				c = &candidate{movieID: nb.MovieID}
				candidates[nb.MovieID] = c
			}
			c.score += r.Rating * nb.Similarity
			c.weightSum += nb.Similarity
		}
	}

	// Нормализация и ограничение [1, 5]
	sorted := make([]candidate, 0, len(candidates))
	for _, c := range candidates {
		if c.weightSum == 0 {
			continue
		}
		predicted := c.score / c.weightSum
		predicted = math.Max(1.0, math.Min(5.0, predicted))
		c.score = predicted
		sorted = append(sorted, *c)
	}

	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].score > sorted[j].score
	})

	if len(sorted) > n {
		sorted = sorted[:n]
	}

	// Загрузить названия
	movieIDs := make([]int, len(sorted))
	for i, c := range sorted {
		movieIDs[i] = c.movieID
	}
	titles, err := database.FetchMovieTitles(ctx, pool, movieIDs)
	if err != nil {
		return nil, err
	}

	results := make([]Recommendation, len(sorted))
	for i, c := range sorted {
		results[i] = Recommendation{
			MovieID:         c.movieID,
			Title:           titles[c.movieID],
			PredictedRating: math.Round(c.score*100) / 100,
		}
	}
	return results, nil
}
