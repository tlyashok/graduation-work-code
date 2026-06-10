# Многоэтапная сборка
FROM golang:1.25-alpine AS builder
ENV GOTOOLCHAIN=local

WORKDIR /build
COPY . .
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o rec-service ./cmd/server

# Итоговый образ
FROM alpine:3.19

WORKDIR /app
COPY --from=builder /build/rec-service .

EXPOSE 8000

CMD ["./rec-service"]
