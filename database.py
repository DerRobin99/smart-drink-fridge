import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB = os.environ.get(
    "DATABASE_PATH",
    os.path.join(BASE_DIR, "getraenke.db")
)


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
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Datenbank initialisiert: {DB}")
