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
    (
        5,
        "Konfigurierbare automatische Backups und Update-Status",
        [
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('backup_frequency', 'daily')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('backup_weekday', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('backup_max_backups', '30')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('backup_max_age_days', '90')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('last_backup_error', '')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('update_install_status', 'idle')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('update_install_target', '')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('update_install_started_at', '')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('update_install_error', '')
            """,
        ],
    ),
    (
        6,
        "Checkout, Standardwährung und Gerätesteuerung",
        [
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('default_currency', 'EUR')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('checkout_mode_enabled', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('host_control_enabled', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('display_show_user', '1')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('display_show_booking', '1')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('display_show_inventory', '0')
            """,
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            VALUES ('display_rotate_seconds', '10')
            """,
        ],
    ),
    (
        7,
        "Einrichtungsassistent",
        [
            """
            INSERT OR IGNORE INTO einstellungen (schluessel, wert)
            SELECT 'setup_completed',
                   CASE WHEN EXISTS (SELECT 1 FROM produkte)
                             OR EXISTS (SELECT 1 FROM benutzer)
                        THEN '1' ELSE '0' END
            """,
        ],
    ),
    (
        8,
        "Zentralserver, Scanner und Standortbestände",
        [
            """
            CREATE TABLE IF NOT EXISTS standorte (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                aktiv INTEGER NOT NULL DEFAULT 1,
                erstellt_am DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "INSERT OR IGNORE INTO standorte (id, name) VALUES (1, 'Standard')",
            """
            CREATE TABLE IF NOT EXISTS scanner_geraete (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scanner_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL,
                standort_id INTEGER NOT NULL,
                api_token_hash TEXT NOT NULL,
                aktiv INTEGER NOT NULL DEFAULT 1,
                letzter_kontakt DATETIME,
                FOREIGN KEY (standort_id) REFERENCES standorte(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS standort_bestaende (
                produkt_id INTEGER NOT NULL,
                standort_id INTEGER NOT NULL,
                bestand INTEGER NOT NULL DEFAULT 0,
                mindestbestand INTEGER NOT NULL DEFAULT 0,
                sollbestand INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (produkt_id, standort_id),
                FOREIGN KEY (produkt_id) REFERENCES produkte(id) ON DELETE CASCADE,
                FOREIGN KEY (standort_id) REFERENCES standorte(id) ON DELETE CASCADE
            )
            """,
            """
            INSERT OR IGNORE INTO standort_bestaende
                (produkt_id, standort_id, bestand, mindestbestand, sollbestand)
            SELECT id, 1, bestand, mindestbestand, sollbestand FROM produkte
            """,
            "ALTER TABLE buchungen ADD COLUMN scanner_id TEXT",
            "ALTER TABLE buchungen ADD COLUMN standort_id INTEGER",
            "ALTER TABLE buchungen ADD COLUMN standort_name TEXT",
            """
            CREATE TABLE IF NOT EXISTS scanner_events (
                event_id TEXT PRIMARY KEY,
                scanner_id TEXT NOT NULL,
                empfangen_am DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                result_json TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bestands_umlagerungen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produkt_id INTEGER NOT NULL,
                von_standort_id INTEGER NOT NULL,
                zu_standort_id INTEGER NOT NULL,
                menge INTEGER NOT NULL,
                zeitpunkt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                benutzer_name TEXT,
                FOREIGN KEY (produkt_id) REFERENCES produkte(id),
                FOREIGN KEY (von_standort_id) REFERENCES standorte(id),
                FOREIGN KEY (zu_standort_id) REFERENCES standorte(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ha_location_sync (
                sync_key TEXT PRIMARY KEY,
                item_name TEXT NOT NULL
            )
            """,
            "INSERT OR IGNORE INTO einstellungen VALUES ('default_location_id', '1')",
            "INSERT OR IGNORE INTO einstellungen VALUES ('shopping_list_scope', 'shared')",
        ],
    ),
    (
        9,
        "Lokale Scanner-Erkennung",
        [
            "ALTER TABLE scanner_geraete ADD COLUMN lokal_erkannt INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE scanner_geraete ADD COLUMN letzte_lokale_erkennung DATETIME",
        ],
    ),
    (
        10,
        "Sichere Scanner-Netzwerkkopplung",
        [
            """
            CREATE TABLE IF NOT EXISTS scanner_kopplungsanfragen (
                scanner_id TEXT PRIMARY KEY COLLATE NOCASE,
                name TEXT NOT NULL,
                secret_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                angefragt_am DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                bestaetigt_am DATETIME
            )
            """,
        ],
    ),
    (
        11,
        "Sichere Mobile-App-Zugaenge und Einkaufsliste",
        [
            """
            CREATE TABLE IF NOT EXISTS mobile_api_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benutzer_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                erstellt_am DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                zuletzt_verwendet DATETIME,
                widerrufen_am DATETIME,
                FOREIGN KEY (benutzer_id) REFERENCES benutzer(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS mobile_push_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benutzer_id INTEGER NOT NULL,
                device_token_hash TEXT NOT NULL UNIQUE,
                device_token TEXT NOT NULL,
                environment TEXT NOT NULL DEFAULT 'development',
                aktiviert INTEGER NOT NULL DEFAULT 1,
                aktualisiert_am DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (benutzer_id) REFERENCES benutzer(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS mobile_einkaufsliste (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titel TEXT NOT NULL,
                menge INTEGER NOT NULL DEFAULT 1,
                erledigt INTEGER NOT NULL DEFAULT 0,
                erstellt_von INTEGER,
                erstellt_am DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                aktualisiert_am DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (erstellt_von) REFERENCES benutzer(id) ON DELETE SET NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_mobile_tokens_user ON mobile_api_tokens(benutzer_id)",
            "CREATE INDEX IF NOT EXISTS idx_mobile_shopping_open ON mobile_einkaufsliste(erledigt, id)",
        ],
    ),
    (
        12,
        "Konfigurierbare Benachrichtigungen fuer mobile Geraete",
        [
            "ALTER TABLE mobile_push_devices ADD COLUMN benachrichtigungen_aktiv INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE mobile_push_devices ADD COLUMN niedriger_bestand INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE mobile_push_devices ADD COLUMN server_offline INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE mobile_push_devices ADD COLUMN backup_fehler INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE mobile_push_devices ADD COLUMN updates INTEGER NOT NULL DEFAULT 1",
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
