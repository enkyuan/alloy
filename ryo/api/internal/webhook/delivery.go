package webhook

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"log/slog"
	"net/http"
	"time"
)

// SignPayload returns the HMAC-SHA256 hex signature of payload using secret.
// Format: "sha256=<hex>", matching the X-Ryo-Signature header value.
func SignPayload(payload []byte, secret string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(payload)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}

// DeliverOnce POSTs payload to url, signing with secret.
// Returns the HTTP status code and any transport-level error.
// A non-2xx HTTP status is NOT an error — callers must check the status code.
func DeliverOnce(url, secret string, payload []byte) (int, error) {
	sig := SignPayload(payload, secret)
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return 0, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Ryo-Signature", sig)

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return 0, fmt.Errorf("post: %w", err)
	}
	resp.Body.Close()
	return resp.StatusCode, nil
}

// Worker polls webhook_deliveries every interval and dispatches pending rows.
// Call in a goroutine; cancel ctx to stop.
func Worker(ctx context.Context, store *Store, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := runBatch(ctx, store); err != nil {
				slog.Error("webhook delivery batch", "err", err)
			}
		}
	}
}

func runBatch(ctx context.Context, store *Store) error {
	deliveries, err := store.PollPending(ctx, 50)
	if err != nil {
		return err
	}
	for _, d := range deliveries {
		go dispatchOne(ctx, store, d)
	}
	return nil
}

func dispatchOne(ctx context.Context, store *Store, d Delivery) {
	wh, err := store.GetByID(ctx, d.WebhookID)
	if err != nil {
		slog.Error("webhook lookup", "webhook_id", d.WebhookID, "err", err)
		return
	}

	attempts := d.Attempts + 1
	statusCode, deliveryErr := DeliverOnce(wh.URL, wh.Secret, d.Payload)
	if deliveryErr != nil {
		slog.Warn("webhook delivery transport error", "id", d.ID, "err", deliveryErr)
		if err := store.MarkFailed(ctx, d.ID, nil, attempts); err != nil {
			slog.Error("mark failed", "id", d.ID, "err", err)
		}
		return
	}
	if statusCode >= 200 && statusCode < 300 {
		slog.Info("webhook delivered", "id", d.ID, "status", statusCode)
		if err := store.MarkDelivered(ctx, d.ID, statusCode); err != nil {
			slog.Error("mark delivered", "id", d.ID, "err", err)
		}
		return
	}
	slog.Warn("webhook delivery failed", "id", d.ID, "status", statusCode, "attempts", attempts)
	if err := store.MarkFailed(ctx, d.ID, &statusCode, attempts); err != nil {
		slog.Error("mark failed", "id", d.ID, "err", err)
	}
}
