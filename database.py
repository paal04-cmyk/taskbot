import sqlite3
import os
import json

DB_PATH = os.environ.get("DB_PATH", "tasks.db")

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._crea_tabelle()

    def _crea_tabelle(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titolo TEXT NOT NULL,
                priorita INTEGER NOT NULL,
                gruppo INTEGER NOT NULL,
                difficolta INTEGER NOT NULL,
                scadenza TEXT,
                inserimento TEXT NOT NULL,
                score REAL DEFAULT 0,
                completata INTEGER DEFAULT 0,
                ripetizione TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pianificazione (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titolo TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def aggiungi_task(self, titolo, priorita, gruppo, difficolta, scadenza, inserimento, score, ripetizione=None):
        cur = self.conn.execute(
            "INSERT INTO tasks (titolo, priorita, gruppo, difficolta, scadenza, inserimento, score, ripetizione) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (titolo, priorita, gruppo, difficolta, scadenza, inserimento, score, ripetizione)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_tasks_ordinate(self):
        cur = self.conn.execute(
            "SELECT * FROM tasks WHERE completata = 0 ORDER BY score DESC"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_task_by_id(self, task_id):
        cur = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def aggiorna_score(self, task_id, score):
        self.conn.execute("UPDATE tasks SET score = ? WHERE id = ?", (score, task_id))
        self.conn.commit()

    def completa_task(self, task_id):
        self.conn.execute("UPDATE tasks SET completata = 1 WHERE id = ?", (task_id,))
        self.conn.commit()

    def cancella_task(self, task_id):
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()

    def salva_pianificazione(self, titoli):
        self.conn.execute("DELETE FROM pianificazione")
        for t in titoli:
            self.conn.execute("INSERT INTO pianificazione (titolo) VALUES (?)", (t,))
        self.conn.commit()

    def get_pianificazione(self):
        cur = self.conn.execute("SELECT titolo FROM pianificazione")
        return [row['titolo'] for row in cur.fetchall()]

    def cancella_pianificazione(self):
        self.conn.execute("DELETE FROM pianificazione")
        self.conn.commit()
