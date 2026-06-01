// Package agent handles agent creation and configuration.
//
// An Agent is a configured instance of the agentkit runtime:
// it has a business type, a personality/system prompt, a set of
// enabled tools (e.g. take_order, request_payment), and a linked
// payment wallet.  The Studio uses these endpoints to build the
// no-code agent-creation wizard.
package agent

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

// Agent represents a configured agent instance.
type Agent struct {
	ID           string       `json:"id"`
	Name         string       `json:"name"`
	BusinessType BusinessType `json:"business_type"`
	SystemPrompt string       `json:"system_prompt"`
	Tools        []string     `json:"tools"`        // e.g. ["take_order","request_payment"]
	VoiceEnabled bool         `json:"voice_enabled"`
	WalletID     string       `json:"wallet_id,omitempty"`
	EmbedToken   string       `json:"embed_token"`  // token used by the JS widget
	CreatedAt    time.Time    `json:"created_at"`
}

// BusinessType shapes the agent's defaults (system prompt, default tools).
type BusinessType string

const (
	BusinessTypeCafe       BusinessType = "cafe"
	BusinessTypeRestaurant BusinessType = "restaurant"
	BusinessTypeRetail     BusinessType = "retail"
	BusinessTypeService    BusinessType = "service"
	BusinessTypeCustom     BusinessType = "custom"
)

// CreateAgentRequest is the Studio wizard payload.
type CreateAgentRequest struct {
	Name         string       `json:"name"`
	BusinessType BusinessType `json:"business_type"`
	SystemPrompt string       `json:"system_prompt,omitempty"` // auto-generated if empty
	Tools        []string     `json:"tools,omitempty"`          // defaults applied per business_type
	VoiceEnabled bool         `json:"voice_enabled"`
}

// Router returns the chi.Router for /v1/agents.
func Router() http.Handler {
	r := chi.NewRouter()
	r.Post("/", createAgent)
	r.Get("/", listAgents)
	r.Get("/{id}", getAgent)
	r.Patch("/{id}", updateAgent)
	r.Delete("/{id}", deleteAgent)
	r.Get("/{id}/embed", getEmbedSnippet) // returns JS snippet
	return r
}

func createAgent(w http.ResponseWriter, r *http.Request) {
	var req CreateAgentRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request"}`, http.StatusBadRequest)
		return
	}

	if req.SystemPrompt == "" {
		req.SystemPrompt = defaultPrompt(req.BusinessType)
	}
	if len(req.Tools) == 0 {
		req.Tools = defaultTools(req.BusinessType)
	}

	agent := Agent{
		ID:           uuid.New().String(),
		Name:         req.Name,
		BusinessType: req.BusinessType,
		SystemPrompt: req.SystemPrompt,
		Tools:        req.Tools,
		VoiceEnabled: req.VoiceEnabled,
		EmbedToken:   uuid.New().String(),
		CreatedAt:    time.Now().UTC(),
	}

	// TODO: persist to store

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(agent)
}

func listAgents(w http.ResponseWriter, r *http.Request) {
	// TODO: load from store, scoped to authenticated user/org
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode([]Agent{})
}

func getAgent(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	// TODO: load from store
	_ = id
	http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
}

func updateAgent(w http.ResponseWriter, r *http.Request) {
	// TODO: partial update
	w.WriteHeader(http.StatusNoContent)
}

func deleteAgent(w http.ResponseWriter, r *http.Request) {
	// TODO: soft-delete
	w.WriteHeader(http.StatusNoContent)
}

// getEmbedSnippet returns the JS embed snippet for this agent.
func getEmbedSnippet(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	// TODO: look up embed_token from store
	snippet := map[string]string{
		"snippet": `<script src="https://cdn.agentkit.dev/embed.js" data-agent="` + id + `" async></script>`,
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(snippet)
}

// defaultPrompt returns a business-type-specific system prompt.
func defaultPrompt(bt BusinessType) string {
	switch bt {
	case BusinessTypeCafe, BusinessTypeRestaurant:
		return "You are a friendly ordering assistant. Help customers browse the menu, take their order accurately, confirm customisations, and process payment."
	case BusinessTypeRetail:
		return "You are a helpful shop assistant. Help customers find products, answer questions, and complete checkout."
	case BusinessTypeService:
		return "You are a helpful booking assistant. Help customers schedule appointments and process payment."
	default:
		return "You are a helpful business assistant."
	}
}

// defaultTools returns the default tool set for a business type.
func defaultTools(bt BusinessType) []string {
	switch bt {
	case BusinessTypeCafe, BusinessTypeRestaurant:
		return []string{"get_menu", "add_to_order", "confirm_order", "request_payment", "send_receipt"}
	case BusinessTypeRetail:
		return []string{"search_products", "add_to_cart", "request_payment", "send_receipt"}
	case BusinessTypeService:
		return []string{"get_availability", "book_appointment", "request_payment", "send_confirmation"}
	default:
		return []string{"request_payment"}
	}
}
