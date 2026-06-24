package webhook

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/ryo/api/internal/middleware"
)

type webhookHandler struct {
	store *Store
}

// Router mounts webhook CRUD routes.
func Router(db *pgxpool.Pool) http.Handler {
	h := &webhookHandler{store: NewStore(db)}
	r := chi.NewRouter()
	r.Post("/", h.create)
	r.Get("/", h.list)
	r.Delete("/{id}", h.delete)
	return r
}

type createRequest struct {
	URL    string   `json:"url"    validate:"required,url"`
	Events []string `json:"events"`
}

func (h *webhookHandler) create(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	var req createRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	secret := uuid.New().String() + uuid.New().String() // 72-char random secret
	wh := Webhook{
		ID:        uuid.New().String(),
		OrgID:     orgID,
		URL:       req.URL,
		Secret:    secret,
		Events:    req.Events,
		CreatedAt: time.Now().UTC(),
	}
	created, err := h.store.Insert(r.Context(), wh)
	if err != nil {
		writeErrorH(w, http.StatusInternalServerError, err.Error())
		return
	}
	// Return secret only on creation
	writeJSONH(w, http.StatusCreated, map[string]any{
		"id":         created.ID,
		"url":        created.URL,
		"events":     created.Events,
		"secret":     secret,
		"created_at": created.CreatedAt,
	})
}

func (h *webhookHandler) list(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	whs, err := h.store.List(r.Context(), orgID)
	if err != nil {
		writeErrorH(w, http.StatusInternalServerError, err.Error())
		return
	}
	if whs == nil {
		whs = []Webhook{}
	}
	writeJSONH(w, http.StatusOK, whs)
}

func (h *webhookHandler) delete(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	orgID := middleware.OrgID(r.Context())
	if err := h.store.Delete(r.Context(), id, orgID); err != nil {
		writeErrorH(w, http.StatusInternalServerError, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func writeJSONH(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		// Headers already sent; log only
		_ = err
	}
}

func writeErrorH(w http.ResponseWriter, status int, msg string) {
	writeJSONH(w, status, map[string]string{"error": msg})
}
