#!/bin/sh
set -eu

DATABASE=${SMART_FRIDGE_DATABASE:-/home/docker/smart-drink-fridge/data/getraenke.db}
SSH_KEY=${SMART_FRIDGE_BACKUP_KEY:-/home/robin/.ssh/smart-fridge-backup-to-pi}
REMOTE=${SMART_FRIDGE_BACKUP_REMOTE:-robin@192.168.178.155}
REMOTE_DIR=${SMART_FRIDGE_BACKUP_REMOTE_DIR:-/home/robin/smart-drink-fridge-offsite-backups}
KEEP=${SMART_FRIDGE_BACKUP_KEEP:-30}
STAMP=$(date +%Y-%m-%d_%H-%M-%S)
NAME=smart-drink-fridge_${STAMP}.db
TEMP=$(mktemp /tmp/smart-drink-fridge-backup.XXXXXX.db)

cleanup() {
    rm -f "$TEMP"
}
trap cleanup EXIT INT TERM

test -f "$DATABASE"
sqlite3 "$DATABASE" ".backup '$TEMP'"
test "$(sqlite3 "$TEMP" 'PRAGMA integrity_check;')" = "ok"

ssh -i "$SSH_KEY" -o BatchMode=yes "$REMOTE" "mkdir -p '$REMOTE_DIR'"
scp -i "$SSH_KEY" -o BatchMode=yes "$TEMP" "$REMOTE:$REMOTE_DIR/$NAME.partial"
ssh -i "$SSH_KEY" -o BatchMode=yes "$REMOTE" \
    "mv '$REMOTE_DIR/$NAME.partial' '$REMOTE_DIR/$NAME' && \
     find '$REMOTE_DIR' -maxdepth 1 -type f -name 'smart-drink-fridge_*.db' -printf '%T@ %p\n' | \
     sort -nr | tail -n +$((KEEP + 1)) | cut -d' ' -f2- | xargs -r rm --"

echo "Backup erfolgreich übertragen: $REMOTE:$REMOTE_DIR/$NAME"
