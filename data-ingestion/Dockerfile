FROM golang:1.26-alpine AS builder

WORKDIR /

COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -o go-ingestor .

FROM alpine:3.23
COPY --from=builder /go-ingestor .

CMD ["./go-ingestor"]
