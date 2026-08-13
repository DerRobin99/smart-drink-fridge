# Smart Drink Fridge

[![Download on the App Store](https://img.shields.io/badge/Download_on_the-App_Store-0D96F6?logo=apple&logoColor=white)](https://apps.apple.com/app/smart-drink-fridge/id6799288886)
[![Latest Release](https://img.shields.io/github/v/release/DerRobin99/smart-drink-fridge?display_name=tag&sort=semver)](https://github.com/DerRobin99/smart-drink-fridge/releases/latest)
[![Docker Image](https://github.com/DerRobin99/smart-drink-fridge/actions/workflows/docker-publish.yml/badge.svg?branch=main)](https://github.com/DerRobin99/smart-drink-fridge/actions/workflows/docker-publish.yml)
[![App Tests](https://github.com/DerRobin99/smart-drink-fridge/actions/workflows/app-tests.yml/badge.svg?branch=main)](https://github.com/DerRobin99/smart-drink-fridge/actions/workflows/app-tests.yml)
[![Codecov](https://codecov.io/gh/DerRobin99/smart-drink-fridge/graph/badge.svg)](https://codecov.io/gh/DerRobin99/smart-drink-fridge)
[![License: MIT](https://img.shields.io/github/license/DerRobin99/smart-drink-fridge)](LICENSE)

Smart Drink Fridge is a self-hosted drink inventory system for Raspberry Pi and Docker. Scan a barcode when you take a bottle or can; stock, history, statistics and shopping lists update automatically.

## Now on the App Store

The native **Smart Drink Fridge app for iPhone and Apple Watch is available now**.

[**Download Smart Drink Fridge on the App Store →**](https://apps.apple.com/app/smart-drink-fridge/id6799288886)

The app connects directly to your own Smart Drink Fridge server and includes inventory, quick bookings, camera barcode scanning, statistics, shopping lists, widgets, Live Activities, Dynamic Island and Apple Watch support. A built-in demo lets you explore it without a server.

## What it does

- Tracks stock, transactions, prices and consumption statistics
- Supports multiple barcodes, package quantities and product lookup
- Scans with a Raspberry Pi camera or USB barcode scanner
- Manages multiple fridges, locations and remote scanner devices
- Offers optional users, PIN/password login and NFC identification
- Integrates with Home Assistant, Pushover and Tailscale
- Supports an optional Nextion status display
- Runs locally with Docker Compose and SQLite; no hosted account required
- Provides a responsive web app in 19 languages

## Screenshots

| Dashboard | Statistics | Mobile |
| --- | --- | --- |
| ![Dashboard](docs/images/dashboard.jpg) | ![Statistics](docs/images/statistics.jpg) | ![Mobile dashboard](docs/images/mobile-dashboard.jpg) |

## Quick start

Requirements: Docker with Docker Compose, a persistent host for the server, and a modern browser.

```bash
git clone https://github.com/DerRobin99/smart-drink-fridge.git
cd smart-drink-fridge
cp .env.example .env
docker compose up -d
```

Before starting, set strong values for `SECRET_KEY` and `STORNO_PASSWORT` in `.env`. Open `http://<server-ip>:5000` after the containers start.

Optional hardware services are enabled with Compose profiles:

```bash
# Camera or USB scanner
docker compose --profile scanner up -d

# Scanner, NFC reader and Nextion display
docker compose --profile scanner --profile nfc --profile display up -d
```

For upgrades, configuration, Raspberry Pi hardware, remote scanners, backups and troubleshooting, use the **[complete documentation in the Wiki](https://github.com/DerRobin99/smart-drink-fridge/wiki)**.

## Documentation

- **[Installation](https://github.com/DerRobin99/smart-drink-fridge/wiki/Installation)**
- **[Configuration](https://github.com/DerRobin99/smart-drink-fridge/wiki/Configuration)**
- **[Using the application](https://github.com/DerRobin99/smart-drink-fridge/wiki/Using-the-application)**
- **[iPhone and Apple Watch app](https://github.com/DerRobin99/smart-drink-fridge/wiki/iPhone-and-Apple-Watch-app)**
- **[Multiple fridges and remote scanners](https://github.com/DerRobin99/smart-drink-fridge/wiki/Multiple-fridges-and-remote-scanners)**
- **[Hardware and barcode scanners](https://github.com/DerRobin99/smart-drink-fridge/wiki/Hardware-and-barcode-scanners)**
- **[User accounts and NFC](https://github.com/DerRobin99/smart-drink-fridge/wiki/User-accounts-and-NFC)**
- **[Nextion display](https://github.com/DerRobin99/smart-drink-fridge/wiki/Nextion-display)**
- **[Integrations](https://github.com/DerRobin99/smart-drink-fridge/wiki/Integrations)**
- **[Backups and data](https://github.com/DerRobin99/smart-drink-fridge/wiki/Backups-and-data)**
- **[Security](https://github.com/DerRobin99/smart-drink-fridge/wiki/Security)**
- **[Troubleshooting](https://github.com/DerRobin99/smart-drink-fridge/wiki/Troubleshooting)**

## Project status

Smart Drink Fridge is actively maintained. Stable versions and release notes are published under [Releases](https://github.com/DerRobin99/smart-drink-fridge/releases); planned work is tracked in the [Roadmap](ROADMAP.md).

Contributions and translation corrections are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md), open an [issue](https://github.com/DerRobin99/smart-drink-fridge/issues), or start a [discussion](https://github.com/DerRobin99/smart-drink-fridge/discussions).

## Native push notifications

Release 1.11 adds optional Apple Push Notification service (APNs) delivery for
low stock, failed backups and completed Docker updates. APNs credentials are
server secrets: never commit the Apple `.p8` private key or copy it into a
Docker image.

```bash
mkdir -p secrets
cp /secure/location/AuthKey_XXXXXXXXXX.p8 secrets/apns-auth-key.p8
chmod 600 secrets/apns-auth-key.p8
```

Set `APNS_KEY_ID`, `APNS_TEAM_ID` and, if required, `APNS_BUNDLE_ID` in `.env`,
then start the web service with the secret-only override:

```bash
docker compose -f docker-compose.yml -f docker-compose.apns.yml up -d web
```

The server cannot send an alert while it is itself offline. Server-offline
alerts therefore have to be generated locally by the native app or by an
independent monitoring service.

## Release notes

### 1.11.0

- Integrates the native iPhone notification registrations with APNs.
- Sends optional low-stock, backup-failure and update-complete notifications.
- Adds a safe Compose override for mounting the Apple signing key read-only.
- Includes the USB scanner and session power controls added after 1.10.0.

### 1.10.0

- Adds the server-selected language to the mobile dashboard API.
- Extends mobile API language response coverage.

## Security

Run the service on a trusted private network or behind authenticated private access such as Tailscale. Do not expose the Flask service directly to the public internet. See [SECURITY.md](SECURITY.md) and the [Wiki security guide](https://github.com/DerRobin99/smart-drink-fridge/wiki/Security).

## License

[MIT](LICENSE)
