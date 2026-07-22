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
            ean TEXT PRIMARY KEY,
            name TEXT NOT NULL,
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

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Leere Datenbank initialisiert: {DB}")
