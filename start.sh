#!/bin/sh
set -eu

if [ ! -f .env ]; then
    echo "Error: .env not found."
    echo "Run: cp .env.example .env"
    exit 1
fi

TAILSCALE_ENABLED=$(grep '^TAILSCALE_ENABLED=' .env | cut -d= -f2 | tr -d '\r' || true)

if [ "$TAILSCALE_ENABLED" = "true" ]; then
    echo "Starting Smart Drink Fridge with Tailscale..."
    docker compose --profile tailscale up -d
else
    echo "Starting Smart Drink Fridge without Tailscale..."
    docker compose up -d
fi
