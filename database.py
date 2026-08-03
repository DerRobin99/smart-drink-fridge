import os
import sqlite3
from migrations import run_migrations

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB = os.environ.get(
    "DATABASE_PATH",
    os.path.join(BASE_DIR, "getraenke.db")
)


def get_db_connection():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn




def get_setting(key, default=None):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel = ?",
        (key,)
    ).fetchone()
    conn.close()
    return row["wert"] if row else default


def set_setting(key, value):
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO einstellungen (schluessel, wert)
        VALUES (?, ?)
        ON CONFLICT(schluessel)
        DO UPDATE SET wert=excluded.wert
        """,
        (key, str(value))
    )
    conn.commit()
    conn.close()


def init_db():
    conn = sqlite3.connect(DB)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS produkte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            marke TEXT NOT NULL DEFAULT '',
            verpackungsinfo TEXT NOT NULL DEFAULT '',
            bestand INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS buchungen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ean TEXT NOT NULL,
            produkt TEXT NOT NULL,
            aktion TEXT NOT NULL,
            zeitpunkt DATETIME DEFAULT CURRENT_TIMESTAMP,
            menge INTEGER,
            bestand_vorher INTEGER,
            bestand_nachher INTEGER,
            quelle TEXT,
            storniert INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS produkt_barcodes (
            ean TEXT PRIMARY KEY,
            produkt_id INTEGER NOT NULL,
            menge INTEGER NOT NULL DEFAULT 1,
            aktion TEXT NOT NULL DEFAULT 'entnehmen',
            FOREIGN KEY (produkt_id)
                REFERENCES produkte(id)
                ON DELETE CASCADE
        )
        """
    )

    # Global application settings.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS einstellungen (
            schluessel TEXT PRIMARY KEY,
            wert TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ha_shopping_sync (
            produkt_id INTEGER PRIMARY KEY,
            item_name TEXT NOT NULL,
            FOREIGN KEY (produkt_id)
                REFERENCES produkte(id)
                ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO einstellungen (schluessel, wert)
        VALUES ('ha_einkaufsliste_aktiv', '0')
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO einstellungen (schluessel, wert)
        VALUES
            ('backup_enabled', '1'),
            ('backup_path', '/data/backups'),
            ('backup_frequency', 'daily'),
            ('backup_time', '03:00'),
            ('backup_weekday', '0'),
            ('backup_max_backups', '30'),
            ('backup_max_age_days', '90'),
            ('last_backup', ''),
            ('last_backup_status', ''),
            ('last_backup_error', ''),
            ('default_currency', 'EUR'),
            ('checkout_mode_enabled', '0'),
            ('host_control_enabled', '0'),
            ('display_show_user', '1'),
            ('display_show_booking', '1'),
            ('display_show_inventory', '0'),
            ('display_rotate_seconds', '10')
        """
    )
    # Migrate existing databases without deleting user data.
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(produkte)").fetchall()
    }

    if "mindestbestand" not in columns:
        conn.execute(
            "ALTER TABLE produkte "
            "ADD COLUMN mindestbestand INTEGER NOT NULL DEFAULT 0"
        )

    if "sollbestand" not in columns:
        conn.execute(
            "ALTER TABLE produkte "
            "ADD COLUMN sollbestand INTEGER NOT NULL DEFAULT 0"
        )

    conn.commit()

    run_migrations(conn)

    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Datenbank initialisiert: {DB}")
