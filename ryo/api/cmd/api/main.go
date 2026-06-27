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

	agenthandler "github.com/enkyuan/alloy/ryo/api/internal/agent"
	"github.com/enkyuan/alloy/ryo/api/internal/middleware"
	obshandler "github.com/enkyuan/alloy/ryo/api/internal/observability"
	paymenthandler "github.com/enkyuan/alloy/ryo/api/internal/payment"
	sessionhandler "github.com/enkyuan/alloy/ryo/api/internal/session"
	"github.com/enkyuan/alloy/ryo/api/internal/store"
	stripehandler "github.com/enkyuan/alloy/ryo/api/internal/stripe"
	wallethandler "github.com/enkyuan/alloy/ryo/api/internal/wallet"
	webhookhandler "github.com/enkyuan/alloy/ryo/api/internal/webhook"
)

func main() {
	_ = godotenv.Load()

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	s, err := store.New(ctx, mustEnv("DATABASE_URL"), mustEnv("REDIS_URL"))
	if err != nil {
		slog.Error("init store", "err", err)
		os.Exit(1)
	}
	defer s.Close()

	authSecret := mustEnv("BETTER_AUTH_SECRET")
	stripeKey := mustEnv("STRIPE_SECRET_KEY")
	stripeWebhookSecret := mustEnv("STRIPE_WEBHOOK_SECRET")
	port := envOr("PORT", "8080")

	// Start webhook delivery worker
	whStore := webhookhandler.NewStore(s.DB)
	go webhookhandler.Worker(ctx, whStore, 2*time.Second)

	sessStore := sessionhandler.NewStore(s.DB)

	r := chi.NewRouter()
	r.Use(chimiddleware.RequestID)
	r.Use(chimiddleware.RealIP)
	r.Use(chimiddleware.Logger)
	r.Use(chimiddleware.Recoverer)
	r.Use(chimiddleware.Timeout(30 * time.Second))
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{envOr("STUDIO_ORIGIN", "http://localhost:5173")},
		AllowedMethods:   []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type", "Idempotency-Key"},
		AllowCredentials: true,
	}))

	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"ok"}`)
	})

	// Stripe webhook — no JWT auth, verified by Stripe signature
	r.Post("/stripe/webhook", stripehandler.New(stripeWebhookSecret, sessStore, whStore, s.DB).ServeHTTP)

	r.Group(func(r chi.Router) {
		r.Use(middleware.Auth(authSecret))
		r.Mount("/v1/agents", agenthandler.Router(s.DB))
		r.Mount("/v1/payments", paymenthandler.Router(s.DB))
		r.Mount("/v1/wallet", wallethandler.Router(s.DB))
		r.Mount("/v1/observability", obshandler.Router())
		r.Mount("/v1/sessions", sessionhandler.Router(s.DB, stripeKey))
		r.Mount("/v1/webhooks", webhookhandler.Router(s.DB))
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

	cancel() // stop delivery worker
	shutCtx, shutCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutCancel()
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
