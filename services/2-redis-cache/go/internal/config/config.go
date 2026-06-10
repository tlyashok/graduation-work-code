package config

import (
	"os"
	"strconv"
)

type Config struct {
	DatabaseURL    string
	Host           string
	Port           string
	RecNDefault    int
	RecMinRatings  int
	DBPoolMinConns int32
	DBPoolMaxConns int32
	// Кэш Redis (итерация 2, §2.5).
	RedisURL        string
	CacheTTLSeconds int
}

func Load() *Config {
	return &Config{
		DatabaseURL:     getEnv("DATABASE_URL", "postgresql://filmrec:filmrec@localhost:5432/filmrec"),
		Host:            getEnv("HOST", "0.0.0.0"),
		Port:            getEnv("PORT", "8000"),
		RecNDefault:     getEnvInt("REC_N_DEFAULT", 10),
		RecMinRatings:   getEnvInt("REC_MIN_RATINGS", 5),
		DBPoolMinConns:  int32(getEnvInt("DB_POOL_MIN_SIZE", 10)),
		DBPoolMaxConns:  int32(getEnvInt("DB_POOL_MAX_SIZE", 10)),
		RedisURL:        getEnv("REDIS_URL", "redis://localhost:6379/0"),
		CacheTTLSeconds: getEnvInt("CACHE_TTL_SECONDS", 60),
	}
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}
