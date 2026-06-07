package middleware

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/golang-jwt/jwt/v5"
)

type contextKey string

const (
	ctxUserID contextKey = "userID"
	ctxOrgID  contextKey = "orgID"
)

type claims struct {
	OrgID string `json:"orgId"`
	jwt.RegisteredClaims
}

// Auth returns a middleware that validates a Bearer JWT signed with secret.
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

			ctx := context.WithValue(r.Context(), ctxUserID, c.Subject)
			ctx = context.WithValue(ctx, ctxOrgID, c.OrgID)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// UserID extracts the authenticated user ID from ctx. Returns "" if not set.
func UserID(ctx context.Context) string {
	v, _ := ctx.Value(ctxUserID).(string)
	return v
}

// OrgID extracts the authenticated org ID from ctx. Returns "" if not set.
func OrgID(ctx context.Context) string {
	v, _ := ctx.Value(ctxOrgID).(string)
	return v
}

func writeUnauth(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
