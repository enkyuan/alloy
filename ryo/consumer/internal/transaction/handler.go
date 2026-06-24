package transaction

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/ryo/consumer/internal/middleware"
)

type handler struct {
	store *Store
}

// Router mounts the transactions list route.
func Router(db *pgxpool.Pool) http.Handler {
	h := &handler{store: NewStore(db)}
	r := chi.NewRouter()
	r.Get("/", h.list)
	return r
}

// ActivityRouter mounts the plain-language activity feed route.
func ActivityRouter(db *pgxpool.Pool) http.Handler {
	h := &handler{store: NewStore(db)}
	r := chi.NewRouter()
	r.Get("/", h.activity)
	return r
}

func (h *handler) list(w http.ResponseWriter, r *http.Request) {
	consumerID := middleware.ConsumerID(r.Context())
	limit := queryInt(r, "limit", 20)
	offset := queryInt(r, "offset", 0)
	txs, err := h.store.List(r.Context(), consumerID, limit, offset)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	if txs == nil {
		txs = []Transaction{}
	}
	writeJSON(w, http.StatusOK, txs)
}

func (h *handler) activity(w http.ResponseWriter, r *http.Request) {
	consumerID := middleware.ConsumerID(r.Context())
	limit := queryInt(r, "limit", 20)
	offset := queryInt(r, "offset", 0)
	txs, err := h.store.List(r.Context(), consumerID, limit, offset)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	type entry struct {
		ID         string `json:"id"`
		PlainLabel string `json:"label"`
		Status     string `json:"status"`
		CreatedAt  string `json:"created_at"`
	}
	out := make([]entry, 0, len(txs))
	for _, tx := range txs {
		out = append(out, entry{
			ID:         tx.ID,
			PlainLabel: tx.PlainLabel,
			Status:     tx.Status,
			CreatedAt:  tx.CreatedAt.Format("2006-01-02T15:04:05Z"),
		})
	}
	writeJSON(w, http.StatusOK, out)
}

func queryInt(r *http.Request, key string, def int) int {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < 0 {
		return def
	}
	return n
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		_ = err
	}
}

func writeErr(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
