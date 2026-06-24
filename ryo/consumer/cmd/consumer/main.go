package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	chimiddleware "github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"
	"github.com/joho/godotenv"

	authhandler "github.com/enkyuan/alloy/ryo/consumer/internal/auth"
	internalhandler "github.com/enkyuan/alloy/ryo/consumer/internal/internalapi"
	jwtmiddleware "github.com/enkyuan/alloy/ryo/consumer/internal/middleware"
	"github.com/enkyuan/alloy/ryo/consumer/internal/store"
	txhandler "github.com/enkyuan/alloy/ryo/consumer/internal/transaction"
	wallethandler "github.com/enkyuan/alloy/ryo/consumer/internal/wallet"
)

func main() {
	_ = godotenv.Load()

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	ctx := context.Background()

	db, err := store.New(ctx, mustEnv("DATABASE_URL"))
	if err != nil {
		slog.Error("init db", "err", err)
		os.Exit(1)
	}
	defer db.Close()

	jwtSecret := mustEnv("JWT_SECRET")
	stripeKey := mustEnv("STRIPE_SECRET_KEY")
	internalSecret := mustEnv("INTERNAL_SECRET")
	port := envOr("PORT", "8091")

	r := chi.NewRouter()
	r.Use(chimiddleware.RequestID)
	r.Use(chimiddleware.RealIP)
	r.Use(chimiddleware.Logger)
	r.Use(chimiddleware.Recoverer)
	r.Use(chimiddleware.Timeout(30 * time.Second))
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{envOr("APP_ORIGIN", "http://localhost:5173")},
		AllowedMethods:   []string{"GET", "POST", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type"},
		AllowCredentials: true,
	}))

	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"ok"}`)
	})

	// Public auth routes
	r.Mount("/v1/auth", authhandler.Router(db, jwtSecret))

	// Internal routes (service-to-service, no consumer JWT)
	r.Mount("/internal", internalhandler.Router(db, internalSecret))

	// Protected consumer routes
	r.Group(func(r chi.Router) {
		r.Use(jwtmiddleware.Auth(jwtSecret))
		r.Mount("/v1/wallet", wallethandler.Router(db, stripeKey))
		r.Mount("/v1/transactions", txhandler.Router(db))
		r.Mount("/v1/activity", txhandler.ActivityRouter(db))
	})

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	go func() {
		slog.Info("consumer service listening", "port", port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server error", "err", err)
			os.Exit(1)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	shutCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutCtx); err != nil {
		slog.Error("shutdown error", "err", err)
	}
	slog.Info("consumer service stopped")
}

func mustEnv(key string) string {
	v := os.Getenv(key)
	if v == "" {
		slog.Error("required env var not set", "key", key)
		os.Exit(1)
	}
	return v
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
