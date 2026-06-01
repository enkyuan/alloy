.PHONY: dev build tidy lint test

dev:
	go run ./cmd/api

build:
	go build -o bin/api ./cmd/api

tidy:
	go mod tidy

lint:
	golangci-lint run ./...

test:
	go test ./... -v
