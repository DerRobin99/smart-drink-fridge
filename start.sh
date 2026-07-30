#!/bin/sh
set -eu

if [ ! -f .env ]; then
    echo "Error: .env not found."
    echo "Run: cp .env.example .env"
    exit 1
fi

TAILSCALE_ENABLED=$(grep '^TAILSCALE_ENABLED=' .env | cut -d= -f2 | tr -d '\r' || true)
TAILSCALE_HTTPS=$(grep '^TAILSCALE_HTTPS=' .env | cut -d= -f2 | tr -d '\r' || true)
TAILSCALE_HTTPS=${TAILSCALE_HTTPS:-true}

run_tailscale() {
    if [ "$TAILSCALE_MODE" = "host" ]; then
        tailscale "$@"
    else
        docker exec smart-drink-fridge-tailscale tailscale "$@"
    fi
}

if [ "$TAILSCALE_ENABLED" = "true" ]; then
    if command -v tailscale >/dev/null 2>&1; then
        TAILSCALE_MODE=host
        echo "Using Tailscale installed on the host..."
        docker compose up -d
    else
        TAILSCALE_MODE=container
        echo "Starting Smart Drink Fridge with Tailscale in Docker..."
        docker compose --profile tailscale up -d
    fi

    if [ "$TAILSCALE_HTTPS" = "true" ]; then
        echo "Waiting for Tailscale..."
        attempts=0

        until run_tailscale status >/dev/null 2>&1
        do
            attempts=$((attempts + 1))

            if [ "$attempts" -ge 30 ]; then
                echo "Error: Tailscale did not become ready."
                if [ "$TAILSCALE_MODE" = "container" ]; then
                    echo "Check: docker logs smart-drink-fridge-tailscale"
                else
                    echo "Check: sudo systemctl status tailscaled"
                fi
                exit 1
            fi

            sleep 2
        done

        echo "Enabling trusted HTTPS with Tailscale Serve..."

        if ! run_tailscale serve \
            --bg \
            --yes \
            --https=443 \
            http://127.0.0.1:5000
        then
            echo "Error: Tailscale HTTPS could not be enabled."
            if [ "$TAILSCALE_MODE" = "host" ]; then
                echo "If permission was denied, run once:"
                echo "  sudo tailscale set --operator=$USER"
            fi
            echo "Follow any approval URL shown above, then run ./start.sh again."
            exit 1
        fi

        echo ""
        echo "Smart Drink Fridge is available privately over HTTPS:"
        run_tailscale serve status
        echo ""
        echo "Open the https://...ts.net address on your phone."
        echo "You can then install Smart Drink Fridge as an app."
    fi
else
    echo "Starting Smart Drink Fridge without Tailscale..."
    docker compose up -d
fi
