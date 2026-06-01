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

	agenthandler "github.com/enkyuan/alloy/apps/api/internal/agent"
	"github.com/enkyuan/alloy/apps/api/internal/middleware"
	obshandler "github.com/enkyuan/alloy/apps/api/internal/observability"
	paymenthandler "github.com/enkyuan/alloy/apps/api/internal/payment"
	"github.com/enkyuan/alloy/apps/api/internal/store"
	wallethandler "github.com/enkyuan/alloy/apps/api/internal/wallet"
)

func main() {
	_ = godotenv.Load()

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	ctx := context.Background()

	s, err := store.New(ctx, mustEnv("DATABASE_URL"), mustEnv("REDIS_URL"))
	if err != nil {
		slog.Error("init store", "err", err)
		os.Exit(1)
	}
	defer s.Close()

	authSecret := mustEnv("BETTER_AUTH_SECRET")
	port := envOr("PORT", "8080")

	r := chi.NewRouter()
	r.Use(chimiddleware.RequestID)
	r.Use(chimiddleware.RealIP)
	r.Use(chimiddleware.Logger)
	r.Use(chimiddleware.Recoverer)
	r.Use(chimiddleware.Timeout(30 * time.Second))
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{envOr("STUDIO_ORIGIN", "http://localhost:5173")},
		AllowedMethods:   []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type"},
		AllowCredentials: true,
	}))

	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"ok"}`)
	})

	r.Group(func(r chi.Router) {
		r.Use(middleware.Auth(authSecret))
		r.Mount("/v1/agents", agenthandler.Router(s.DB))
		r.Mount("/v1/payments", paymenthandler.Router(s.DB))
		r.Mount("/v1/wallet", wallethandler.Router(s.DB))
		r.Mount("/v1/observability", obshandler.Router())
	})

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	go func() {
		slog.Info("api listening", "port", port)
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
	slog.Info("api stopped")
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
