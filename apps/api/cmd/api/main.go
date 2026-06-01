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
	"github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"
	"github.com/joho/godotenv"

	agenthandler "github.com/enkyuan/alloy/apps/api/internal/agent"
	obshandler "github.com/enkyuan/alloy/apps/api/internal/observability"
	paymenthandler "github.com/enkyuan/alloy/apps/api/internal/payment"
	"github.com/enkyuan/alloy/apps/api/internal/store"
	wallethandler "github.com/enkyuan/alloy/apps/api/internal/wallet"
)

func main() {
	_ = godotenv.Load()

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	ctx := context.Background()
	s, err := store.New(ctx, os.Getenv("DATABASE_URL"), os.Getenv("REDIS_URL"))
	if err != nil {
		slog.Error("failed to connect to store", "err", err)
		os.Exit(1)
	}
	defer s.Close()

	port := os.Getenv("PORT")
	if port == "" {
		port = "8090"
	}

	r := chi.NewRouter()

	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(30 * time.Second))
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{os.Getenv("STUDIO_ORIGIN")},
		AllowedMethods:   []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type"},
		AllowCredentials: true,
	}))

	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"ok"}`)
	})

	// /v1/agents — create, configure, list agents
	r.Mount("/v1/agents", agenthandler.Router(s.DB))

	// /v1/payments — payment provider config, workflow setup
	r.Mount("/v1/payments", paymenthandler.Router(s.DB))

	// /v1/wallet — wallet create / auto-configure
	r.Mount("/v1/wallet", wallethandler.Router(s.DB))

	// /v1/observability — session logs, event stream
	r.Mount("/v1/observability", obshandler.Router())

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
