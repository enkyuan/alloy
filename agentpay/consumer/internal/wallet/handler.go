package wallet

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	stripe "github.com/stripe/stripe-go/v82"
	"github.com/stripe/stripe-go/v82/customer"
	"github.com/stripe/stripe-go/v82/paymentmethod"
	"github.com/stripe/stripe-go/v82/setupintent"

	"github.com/enkyuan/alloy/agentpay/consumer/internal/auth"
	"github.com/enkyuan/alloy/agentpay/consumer/internal/middleware"
)

type handler struct {
	consumerStore *auth.Store
}

// Router mounts wallet routes.
func Router(db *pgxpool.Pool, stripeKey string) http.Handler {
	stripe.Key = stripeKey
	h := &handler{consumerStore: auth.NewStore(db)}
	r := chi.NewRouter()
	r.Get("/", h.status)
	r.Post("/setup", h.setup)
	return r
}

func (h *handler) status(w http.ResponseWriter, r *http.Request) {
	consumerID := middleware.ConsumerID(r.Context())
	c, err := h.consumerStore.GetByID(r.Context(), consumerID)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	if c.StripeCustomerID == "" {
		writeJSON(w, http.StatusOK, map[string]any{
			"stripe_customer_id": nil,
			"payment_methods":    []any{},
		})
		return
	}
	params := &stripe.PaymentMethodListParams{
		Customer: stripe.String(c.StripeCustomerID),
		Type:     stripe.String("card"),
	}
	iter := paymentmethod.List(params)
	var methods []map[string]any
	for iter.Next() {
		pm := iter.PaymentMethod()
		methods = append(methods, map[string]any{
			"id":    pm.ID,
			"brand": string(pm.Card.Brand),
			"last4": pm.Card.Last4,
			"exp": map[string]any{
				"month": pm.Card.ExpMonth,
				"year":  pm.Card.ExpYear,
			},
		})
	}
	if methods == nil {
		methods = []map[string]any{}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"stripe_customer_id": c.StripeCustomerID,
		"payment_methods":    methods,
	})
}

func (h *handler) setup(w http.ResponseWriter, r *http.Request) {
	consumerID := middleware.ConsumerID(r.Context())
	c, err := h.consumerStore.GetByID(r.Context(), consumerID)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	if c.StripeCustomerID == "" {
		cust, err := customer.New(&stripe.CustomerParams{Email: stripe.String(c.Email)})
		if err != nil {
			writeErr(w, http.StatusBadGateway, "stripe error: "+err.Error())
			return
		}
		if err := h.consumerStore.SetStripeCustomerID(r.Context(), consumerID, cust.ID); err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		c.StripeCustomerID = cust.ID
	}
	si, err := setupintent.New(&stripe.SetupIntentParams{
		Customer:           stripe.String(c.StripeCustomerID),
		PaymentMethodTypes: stripe.StringSlice([]string{"card"}),
	})
	if err != nil {
		writeErr(w, http.StatusBadGateway, "stripe error: "+err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"client_secret": si.ClientSecret})
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
