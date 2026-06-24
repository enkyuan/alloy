# ryo API — pre-built static binary
# Build on host: CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -o bin/api ./cmd/api/main.go
FROM scratch

COPY bin/api /api

EXPOSE 8080

ENTRYPOINT ["/api"]
