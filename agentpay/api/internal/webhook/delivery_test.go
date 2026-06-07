package webhook_test

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/enkyuan/alloy/agentpay/api/internal/webhook"
)

func TestSignPayload(t *testing.T) {
	payload := []byte(`{"event":"payment.completed"}`)
	secret := "mysecret"
	sig := webhook.SignPayload(payload, secret)
	if sig == "" {
		t.Fatal("expected non-empty signature")
	}
	// same inputs must produce same output (deterministic HMAC)
	sig2 := webhook.SignPayload(payload, secret)
	if sig != sig2 {
		t.Errorf("signatures differ: %q vs %q", sig, sig2)
	}
	// different secret must produce different signature
	sigOther := webhook.SignPayload(payload, "other")
	if sig == sigOther {
		t.Error("different secret produced same signature")
	}
}

func TestDeliverOnce_Success(t *testing.T) {
	var got string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Header.Get("X-Agentpay-Signature")
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	payload := []byte(`{"event":"payment.completed"}`)
	status, err := webhook.DeliverOnce(srv.URL, "sec", payload)
	if err != nil {
		t.Fatalf("deliver: %v", err)
	}
	if status != http.StatusOK {
		t.Errorf("status: got %d, want 200", status)
	}
	if got == "" {
		t.Error("X-Agentpay-Signature header not set")
	}
}

func TestDeliverOnce_NonSuccess(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	status, err := webhook.DeliverOnce(srv.URL, "sec", []byte(`{}`))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if status != http.StatusInternalServerError {
		t.Errorf("expected 500, got %d", status)
	}
}
