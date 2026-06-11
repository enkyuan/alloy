// Package observability serves session logs and event streams for the Studio dashboard.
//
// Each agent session produces a sequence of events (user utterance, tool call,
// payment request, payment confirmed, error, etc.).  The Studio reads these to
// show the business owner what their agent is doing and how much it earned.
package observability

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
)

// EventKind is the type of event in a session.
type EventKind string

const (
	EventKindUserMessage    EventKind = "user_message"
	EventKindAgentMessage   EventKind = "agent_message"
	EventKindToolCall       EventKind = "tool_call"
	EventKindToolResult     EventKind = "tool_result"
	EventKindPaymentRequest EventKind = "payment_request"
	EventKindPaymentSuccess EventKind = "payment_success"
	EventKindPaymentFailed  EventKind = "payment_failed"
	EventKindSessionStart   EventKind = "session_start"
	EventKindSessionEnd     EventKind = "session_end"
)

// SessionEvent is a single event within an agent session.
type SessionEvent struct {
	ID        string         `json:"id"`
	SessionID string         `json:"session_id"`
	AgentID   string         `json:"agent_id"`
	Kind      EventKind      `json:"kind"`
	Payload   map[string]any `json:"payload,omitempty"`
	Timestamp time.Time      `json:"timestamp"`
}

// SessionSummary is the top-level view shown in the dashboard sessions list.
type SessionSummary struct {
	SessionID            string     `json:"session_id"`
	AgentID              string     `json:"agent_id"`
	StartedAt            time.Time  `json:"started_at"`
	EndedAt              *time.Time `json:"ended_at,omitempty"`
	EventCount           int        `json:"event_count"`
	AmountCollectedCents int64      `json:"amount_collected_cents"`
	Currency             string     `json:"currency"`
	Status               string     `json:"status"` // "active" | "completed" | "abandoned"
}

func Router() http.Handler {
	r := chi.NewRouter()
	// Session list + detail
	r.Get("/sessions", listSessions)
	r.Get("/sessions/{session_id}", getSession)
	r.Get("/sessions/{session_id}/events", listSessionEvents)
	// Aggregate stats (for the dashboard header cards)
	r.Get("/stats", getStats)
	// Server-Sent Events stream for live sessions
	r.Get("/stream", streamEvents)
	return r
}

func listSessions(w http.ResponseWriter, r *http.Request) {
	agentID := r.URL.Query().Get("agent_id")
	_ = agentID
	// TODO: query store with pagination (cursor-based)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode([]SessionSummary{})
}

func getSession(w http.ResponseWriter, r *http.Request) {
	sessionID := chi.URLParam(r, "session_id")
	_ = sessionID
	// TODO: load from store
	http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
}

func listSessionEvents(w http.ResponseWriter, r *http.Request) {
	sessionID := chi.URLParam(r, "session_id")
	_ = sessionID
	// TODO: load event sequence from store
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode([]SessionEvent{})
}

// getStats returns aggregate metrics for the Studio dashboard header.
func getStats(w http.ResponseWriter, r *http.Request) {
	agentID := r.URL.Query().Get("agent_id")
	_ = agentID
	// TODO: aggregate from store
	stats := map[string]any{
		"sessions_today":          0,
		"revenue_today_cents":     0,
		"sessions_this_week":      0,
		"revenue_this_week_cents": 0,
		"avg_session_duration_s":  0,
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(stats)
}

// streamEvents streams live session events to the Studio via SSE.
// The Studio listens to this to show a real-time feed of what the agent is doing.
func streamEvents(w http.ResponseWriter, r *http.Request) {
	agentID := r.URL.Query().Get("agent_id")
	_ = agentID

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	// TODO: subscribe to the agent's event bus (Redis pub/sub from agentkit/sdk)
	// For now, keep the connection alive until client disconnects.
	ctx := r.Context()
	<-ctx.Done()
	flusher.Flush()
}
