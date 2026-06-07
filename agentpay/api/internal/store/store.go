package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type Store struct {
	DB    *pgxpool.Pool
	Redis *redis.Client
}

func New(ctx context.Context, dbDSN, redisURL string) (*Store, error) {
	pool, err := newPool(ctx, dbDSN)
	if err != nil {
		return nil, fmt.Errorf("store db: %w", err)
	}
	rdb, err := newRedis(ctx, redisURL)
	if err != nil {
		pool.Close()
		return nil, fmt.Errorf("store redis: %w", err)
	}
	return &Store{DB: pool, Redis: rdb}, nil
}

func (s *Store) Close() {
	s.DB.Close()
	s.Redis.Close()
}
