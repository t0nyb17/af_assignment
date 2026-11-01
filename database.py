import json
import sqlite3
from datetime import datetime

import config

JSON_COLUMNS = ["services", "fields", "flags"]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")



def get_connection():
    connection = sqlite3.connect(config.DATABASE_FILE)
    connection.row_factory = sqlite3.Row   # lets us write row["name"] instead of row[1]
    return connection


def run(sql, params=()):
    """Run an INSERT / UPDATE / DELETE and return the id of the new row."""
    connection = get_connection()
    cursor = connection.execute(sql, params)
    connection.commit()
    new_id = cursor.lastrowid
    connection.close()
    return new_id


def fetch_all(sql, params=()):
    connection = get_connection()
    rows = connection.execute(sql, params).fetchall()
    connection.close()
    return [row_to_dict(row) for row in rows]


def fetch_one(sql, params=()):
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def row_to_dict(row):
    """Convert a database row into a normal dictionary and decode the JSON columns."""
    data = dict(row)
    for column in JSON_COLUMNS:
        if column in data:
            data[column] = json.loads(data[column] or "[]")
    return data

def create_tables():
    connection = get_connection()
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, email TEXT, phone TEXT, pan TEXT, gstin TEXT,
            services TEXT,
            status TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER, message TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER, file_path TEXT, source TEXT,
            doc_type TEXT, status TEXT,
            fields TEXT, flags TEXT, client_note TEXT,
            sharpness REAL, received_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER, kind TEXT,
            subject TEXT, email_body TEXT, whatsapp_body TEXT,
            status TEXT, channel TEXT, approved_by TEXT, outbox_file TEXT,
            created_at TEXT, updated_at TEXT, sent_at TEXT
        );
        CREATE TABLE IF NOT EXISTS processed_emails (
            email_key TEXT PRIMARY KEY, processed_at TEXT
        );
        """
    )
    connection.commit()
    connection.close()


def reset_database():
    connection = get_connection()
    connection.executescript(
        """
        DROP TABLE IF EXISTS clients;
        DROP TABLE IF EXISTS flags;
        DROP TABLE IF EXISTS documents;
        DROP TABLE IF EXISTS messages;
        DROP TABLE IF EXISTS processed_emails;
        """
    )
    connection.commit()
    connection.close()
    create_tables()


def add_client(details):
    return run(
        "INSERT INTO clients (name, email, phone, pan, gstin, services, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            details["name"], details["email"], details["phone"], details["pan"], details["gstin"],
            json.dumps(details["services"]), config.STATUS_NEW, now(), now(),
        ),
    )


def save_client(client):
    run(
        "UPDATE clients SET name = ?, email = ?, phone = ?, pan = ?, gstin = ?, services = ?, "
        "status = ?, updated_at = ? WHERE id = ?",
        (
            client["name"], client["email"], client["phone"], client["pan"], client["gstin"],
            json.dumps(client["services"]), client["status"], now(), client["id"],
        ),
    )


def get_client(client_id):
    return fetch_one("SELECT * FROM clients WHERE id = ?", (client_id,))


def get_all_clients():
    return fetch_all("SELECT * FROM clients ORDER BY id")


def find_client_by_email(email):
    return fetch_one("SELECT * FROM clients WHERE lower(email) = lower(?)", (email,))


def find_client_by_pan(pan):
    return fetch_one("SELECT * FROM clients WHERE upper(pan) = upper(?)", (pan,))

def add_flag(client_id, message):
    run("INSERT INTO flags (client_id, message, created_at) VALUES (?, ?, ?)", (client_id, message, now()))


def get_flags(client_id):
    return fetch_all("SELECT * FROM flags WHERE client_id = ? ORDER BY id", (client_id,))


def add_document(client_id, file_path, source, report):
    return run(
        "INSERT INTO documents (client_id, file_path, source, doc_type, status, fields, flags, "
        "client_note, sharpness, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            client_id, file_path, source, report["doc_type"], report["status"],
            json.dumps(report["fields"]), json.dumps(report["flags"]), report["client_note"],
            report["sharpness"], now(),
        ),
    )


def get_documents(client_id):
    return fetch_all("SELECT * FROM documents WHERE client_id = ? ORDER BY id", (client_id,))


def get_document(document_id):
    return fetch_one("SELECT * FROM documents WHERE id = ?", (document_id,))


def save_document(document):
    run(
        "UPDATE documents SET status = ?, flags = ?, client_note = ? WHERE id = ?",
        (document["status"], json.dumps(document["flags"]), document["client_note"], document["id"]),
    )

def add_message(client_id, kind, subject, email_body, whatsapp_body):
    return run(
        "INSERT INTO messages (client_id, kind, subject, email_body, whatsapp_body, status, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (client_id, kind, subject, email_body, whatsapp_body, config.MSG_WAITING, now(), now()),
    )


def save_message(message):
    run(
        "UPDATE messages SET subject = ?, email_body = ?, whatsapp_body = ?, status = ?, channel = ?, "
        "approved_by = ?, outbox_file = ?, sent_at = ?, updated_at = ? WHERE id = ?",
        (
            message["subject"], message["email_body"], message["whatsapp_body"], message["status"],
            message["channel"], message["approved_by"], message["outbox_file"], message["sent_at"],
            now(), message["id"],
        ),
    )


def get_message(message_id):
    return fetch_one("SELECT * FROM messages WHERE id = ?", (message_id,))


def get_messages(status, client_id=None):
    if client_id is None:
        return fetch_all("SELECT * FROM messages WHERE status = ? ORDER BY id", (status,))
    return fetch_all(
        "SELECT * FROM messages WHERE status = ? AND client_id = ? ORDER BY id", (status, client_id)
    )


def email_already_processed(email_key):
    return fetch_one("SELECT * FROM processed_emails WHERE email_key = ?", (email_key,)) is not None


def mark_email_processed(email_key):
    run("INSERT INTO processed_emails (email_key, processed_at) VALUES (?, ?)", (email_key, now()))
