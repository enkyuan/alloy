package middleware

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/golang-jwt/jwt/v5"
)

type contextKey string

const ctxConsumerID contextKey = "consumerID"

type claims struct {
	Role string `json:"role"`
	jwt.RegisteredClaims
}

// Auth validates a Bearer JWT and requires role=consumer.
func Auth(secret string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			raw := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
			if raw == "" {
				writeUnauth(w, "missing token")
				return
			}
			var c claims
			_, err := jwt.ParseWithClaims(raw, &c, func(t *jwt.Token) (any, error) {
				if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
					return nil, jwt.ErrSignatureInvalid
				}
				return []byte(secret), nil
			})
			if err != nil {
				writeUnauth(w, "invalid token")
				return
			}
			if c.Role != "consumer" {
				writeUnauth(w, "forbidden")
				return
			}
			ctx := context.WithValue(r.Context(), ctxConsumerID, c.Subject)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// ConsumerID extracts the consumer ID from the request context.
func ConsumerID(ctx context.Context) string {
	v, _ := ctx.Value(ctxConsumerID).(string)
	return v
}

func writeUnauth(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	json.NewEncoder(w).Encode(map[string]string{"error": msg}) //nolint:errcheck
}
