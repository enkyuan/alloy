package middleware_test

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/enkyuan/alloy/ryo/consumer/internal/middleware"
)

func makeToken(secret, consumerID, role string) string {
	claims := jwt.MapClaims{
		"sub":  consumerID,
		"role": role,
		"exp":  time.Now().Add(time.Hour).Unix(),
	}
	tok, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
	return tok
}

func TestAuth_ValidToken(t *testing.T) {
	secret := "testsecret"
	var gotID string
	handler := middleware.Auth(secret)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotID = middleware.ConsumerID(r.Context())
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken(secret, "consumer-1", "consumer"))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", rr.Code)
	}
	if gotID != "consumer-1" {
		t.Errorf("consumer id: got %q, want consumer-1", gotID)
	}
}

func TestAuth_MissingToken(t *testing.T) {
	handler := middleware.Auth("secret")(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Errorf("expected 401, got %d", rr.Code)
	}
}

func TestAuth_WrongRole(t *testing.T) {
	secret := "testsecret"
	handler := middleware.Auth(secret)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken(secret, "user-1", "merchant"))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Errorf("expected 401 for wrong role, got %d", rr.Code)
	}
}

func TestAuth_InvalidToken(t *testing.T) {
	handler := middleware.Auth("correct-secret")(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken("wrong-secret", "user-1", "consumer"))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Errorf("expected 401 for invalid token, got %d", rr.Code)
	}
}
