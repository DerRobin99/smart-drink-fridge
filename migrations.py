import sqlite3


MIGRATIONS = [
    (
        1,
        "1.2.4 Grundeinstellungen",
        [
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('language', 'auto')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('backup_enabled', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('backup_path', '/backups')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('backup_interval', 'daily')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('backup_time', '03:00')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('backup_retention', '14')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('last_backup', '')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('last_backup_status', '')
            """,
        ],
    ),
    (
        2,
        "Preise und Währungen",
        [
            """
            ALTER TABLE produkte
            ADD COLUMN preis_cent INTEGER NOT NULL DEFAULT 0
            """,
            """
            ALTER TABLE produkte
            ADD COLUMN waehrung TEXT NOT NULL DEFAULT 'EUR'
            """,
            """
            ALTER TABLE buchungen
            ADD COLUMN einzelpreis_cent INTEGER
            """,
            """
            ALTER TABLE buchungen
            ADD COLUMN waehrung TEXT
            """,
        ],
    ),
    (
        3,
        "Optionale Benutzerkonten",
        [
            """
            CREATE TABLE IF NOT EXISTS benutzer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                login_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                rfid_hash TEXT UNIQUE,
                rolle TEXT NOT NULL DEFAULT 'user',
                aktiv INTEGER NOT NULL DEFAULT 1,
                erstellt_am DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            ALTER TABLE buchungen
            ADD COLUMN benutzer_id INTEGER
            """,
            """
            ALTER TABLE buchungen
            ADD COLUMN benutzer_name TEXT
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('benutzerkonten_aktiv', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('aktiver_scanner_benutzer', '')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('aktiver_scanner_benutzer_bis', '')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('scanner_benutzer_erforderlich', '0')
            """,
        ],
    ),
    (
        4,
        "Konfigurierbare Pushover-Benachrichtigungen",
        [
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_enabled', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_user_encrypted', '')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_token_encrypted', '')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_env_fallback_disabled', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_event_low_stock', '1')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_event_out_of_stock', '1')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_event_removed', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_event_restocked', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_event_unknown_barcode', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('pushover_event_scan_blocked', '0')
            """,
        ],
    ),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    applied_versions = {
        row[0]
        for row in conn.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()
    }

    for version, name, statements in MIGRATIONS:
        if version in applied_versions:
            continue

        try:
            with conn:
                for statement in statements:
                    conn.execute(statement)

                conn.execute(
                    """
                    INSERT INTO schema_migrations (version, name)
                    VALUES (?, ?)
                    """,
                    (version, name),
                )

            print(f"Migration {version} abgeschlossen: {name}")

        except sqlite3.Error as exc:
            raise RuntimeError(
                f"Migration {version} fehlgeschlagen: {name}"
            ) from exc
