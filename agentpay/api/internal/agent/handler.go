package agent

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/agentpay/api/internal/middleware"
)

// Agent represents a configured agent instance.
type Agent struct {
	ID           string       `json:"id"`
	OrgID        string       `json:"org_id"`
	Name         string       `json:"name"`
	BusinessType BusinessType `json:"business_type"`
	SystemPrompt string       `json:"system_prompt"`
	Tools        []string     `json:"tools"`
	VoiceEnabled bool         `json:"voice_enabled"`
	WalletID     string       `json:"wallet_id,omitempty"`
	EmbedToken   string       `json:"embed_token"`
	CreatedAt    time.Time    `json:"created_at"`
}

// BusinessType shapes the agent's defaults.
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
	Name         string       `json:"name"          validate:"required"`
	BusinessType BusinessType `json:"business_type"  validate:"required"`
	SystemPrompt string       `json:"system_prompt"`
	Tools        []string     `json:"tools"`
	VoiceEnabled bool         `json:"voice_enabled"`
}

// UpdateAgentRequest is the PATCH payload.
type UpdateAgentRequest struct {
	Name         string `json:"name"`
	SystemPrompt string `json:"system_prompt"`
	VoiceEnabled bool   `json:"voice_enabled"`
}

type handler struct {
	store *agentStore
}

func Router(db *pgxpool.Pool) http.Handler {
	h := &handler{store: newStore(db)}
	r := chi.NewRouter()
	r.Post("/", h.createAgent)
	r.Get("/", h.listAgents)
	r.Get("/{id}", h.getAgent)
	r.Patch("/{id}", h.updateAgent)
	r.Delete("/{id}", h.deleteAgent)
	r.Get("/{id}/embed", h.getEmbedSnippet)
	return r
}

func (h *handler) createAgent(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	var req CreateAgentRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	if req.SystemPrompt == "" {
		req.SystemPrompt = defaultPrompt(req.BusinessType)
	}
	if len(req.Tools) == 0 {
		req.Tools = defaultTools(req.BusinessType)
	}
	a := Agent{
		ID:           uuid.New().String(),
		OrgID:        orgID,
		Name:         req.Name,
		BusinessType: req.BusinessType,
		SystemPrompt: req.SystemPrompt,
		Tools:        req.Tools,
		VoiceEnabled: req.VoiceEnabled,
		EmbedToken:   uuid.New().String(),
	}
	created, err := h.store.insert(r.Context(), a)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, created)
}

func (h *handler) listAgents(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	agents, err := h.store.list(r.Context(), orgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if agents == nil {
		agents = []Agent{}
	}
	writeJSON(w, http.StatusOK, agents)
}

func (h *handler) getAgent(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	orgID := middleware.OrgID(r.Context())
	a, err := h.store.get(r.Context(), id, orgID)
	if err != nil {
		if errors.Is(err, errNotFound) || err.Error() == "not found" {
			writeError(w, http.StatusNotFound, "not found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, a)
}

func (h *handler) updateAgent(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	orgID := middleware.OrgID(r.Context())
	var req UpdateAgentRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	updated, err := h.store.update(r.Context(), id, orgID, req)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, updated)
}

func (h *handler) deleteAgent(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	orgID := middleware.OrgID(r.Context())
	if err := h.store.delete(r.Context(), id, orgID); err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *handler) getEmbedSnippet(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	orgID := middleware.OrgID(r.Context())
	a, err := h.store.get(r.Context(), id, orgID)
	if err != nil {
		writeError(w, http.StatusNotFound, "not found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{
		"snippet": `<script src="https://cdn.agentpay.dev/embed.js" data-agent="` + a.EmbedToken + `" async></script>`,
	})
}

var errNotFound = errors.New("not found")

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

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
