"""
The "brain" that connects all the steps:

    read emails -> find or create client -> read documents
                -> update checklist and status -> draft follow-up messages

It also contains every action a staff member can take from the dashboard
(accept a document, approve a message, mark a client onboarded, ...).

You can also run it without the dashboard:   python pipeline.py
"""
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import checklist
import config
import database
import document_reader
import email_reader
import validators


def process_inbox():
    """Reads every email in the inbox file. Returns a list of log lines to show staff."""
    database.create_tables()
    log = []
    for email in email_reader.read_emails():
        log += process_email(email)
    if not log:
        log.append("No emails found in the inbox.")
    return log


def process_email(email):
    label = f"Email {email['number']} from {email['sender']}"
    email_key = f"{email['number']}|{email['sender']}|{','.join(email['attachments'])}"
    if database.email_already_processed(email_key):
        return [f"{label}: already processed earlier, skipped (so no duplicates are created)."]

    details = email_reader.extract_client_details(email)
    client, matched_on = find_existing_client(details)
    log = []

    if client is None:
        client_id = database.add_client(details)
        services = ", ".join(details["services"]) or "not identified"
        log.append(f"{label}: NEW client #{client_id} '{details['name'] or 'name unknown'}' created. Services: {services}.")
        problems = email_reader.check_details(details, is_new_client=True)
    else:
        client_id = client["id"]
        log.append(
            f"{label}: matches EXISTING client #{client_id} '{client['name']}' (same {matched_on}). "
            "Added to that record, no duplicate created."
        )
        problems = email_reader.check_details(details, is_new_client=False) + merge_details(client, details)
        database.add_flag(
            client_id,
            f"Email {email['number']} came from an existing client (matched on {matched_on}). "
            "It was merged into this record instead of creating a duplicate client.",
        )

    for problem in problems:
        database.add_flag(client_id, f"Email {email['number']}: {problem}")
        log.append(f"    warning: {problem}")

    if not email["attachments"]:
        log.append("    no attachments in this email.")
    for file_name in email["attachments"]:
        log.append("    " + add_document(client_id, config.INBOX_DIR / file_name, f"Email {email['number']}"))

    refresh_client(client_id)
    database.mark_email_processed(email_key)
    return log


def find_existing_client(details):
    """Duplicate check: same email address, or same valid PAN, means the same client."""
    client = database.find_client_by_email(details["email"])
    if client:
        return client, "email address"
    if validators.is_valid_pan(details["pan"]):
        client = database.find_client_by_pan(details["pan"])
        if client:
            return client, "PAN"
    return None, None


def merge_details(client, details):
    """Fill in blanks on an existing client. If a value conflicts, keep the old one and flag it."""
    problems = []
    for field in ["name", "phone", "pan", "gstin"]:
        new_value = details[field]
        old_value = client[field]
        if new_value and not old_value:
            client[field] = new_value
        elif new_value and old_value and new_value.upper() != old_value.upper():
            problems.append(
                f"{field} in this email ({new_value}) is different from the saved {field} ({old_value}). "
                "Kept the saved value, please check with the client."
            )
    for service in details["services"]:
        if service not in client["services"]:
            client["services"].append(service)
    database.save_client(client)
    return problems



def add_document(client_id, file_path, source):
    """Read one document, run the extra checks, save it. Returns one log line."""
    client = database.get_client(client_id)
    report = document_reader.analyse_document(file_path, client)
    check_against_other_records(client, report)
    database.add_document(client_id, str(file_path), source, report)

    # If the email had no name, take it from an ID document, but flag it for staff to confirm.
    name_field = document_reader.NAME_FIELD.get(report["doc_type"])
    if not client["name"] and name_field and name_field in report["fields"]:
        client["name"] = report["fields"][name_field]["value"].title()
        database.save_client(client)
        database.add_flag(client_id, f"Name '{client['name']}' was taken from the {report['doc_type']}. Please confirm.")

    line = f"{Path(file_path).name} -> {report['doc_type']}: {report['status']}"
    if report["flags"]:
        line += f"  ({report['flags'][0]})"
    return line


def check_against_other_records(client, report):
    """Checks that need the database: duplicate copies and PANs that belong to someone else."""
    if report["status"] == config.DOC_REJECTED:
        return

    for old_doc in database.get_documents(client["id"]):
        if old_doc["doc_type"] == report["doc_type"] and old_doc["status"] == config.DOC_ACCEPTED:
            report["flags"].append(f"Extra copy: a {report['doc_type']} was already accepted for this client.")
            break

    if report["doc_type"] == "GST certificate":
        gstin = report["fields"].get("gstin", {}).get("value", "")
        if validators.is_valid_gstin(gstin):
            pan = validators.pan_inside_gstin(gstin)
            owner = database.find_client_by_pan(pan)
            if owner and owner["id"] != client["id"]:
                report["flags"].append(
                    f"The PAN inside this GSTIN ({pan}) belongs to another client: "
                    f"#{owner['id']} {owner['name']}. Please verify before accepting."
                )
                report["status"] = config.DOC_NEEDS_REVIEW


def save_upload(client_id, file_name, file_bytes):
    """Save a file uploaded by staff and return its path."""
    config.UPLOADS_DIR.mkdir(exist_ok=True)
    safe_name = Path(file_name).name   # drop any folder names, keep only the file name
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    path = config.UPLOADS_DIR / f"client{client_id}_{stamp}_{safe_name}"
    path.write_bytes(file_bytes)
    return path


def refresh_client(client_id):
    """Recalculate the status and keep the follow-up draft up to date."""
    client = database.get_client(client_id)
    documents = database.get_documents(client_id)
    client["status"] = checklist.work_out_status(client, documents)
    database.save_client(client)
    update_draft(client, documents)


def latest_sent_message(client_id):
    sent = database.get_messages(config.MSG_SENT, client_id)
    return sent[-1] if sent else None


def update_draft(client, documents):
    waiting = database.get_messages(config.MSG_WAITING, client["id"])
    to_ask = checklist.documents_to_ask_for(client, documents)
    notes = checklist.notes_for_client(client, documents)

    nothing_to_ask = not to_ask and not notes
    finished = client["status"] in (config.STATUS_READY, config.STATUS_ONBOARDED)
    if finished or nothing_to_ask or not client["services"]:
        for message in waiting:
            message["status"] = config.MSG_CANCELLED
            database.save_message(message)
        return

    if waiting:
        draft = waiting[0]
        draft["subject"], draft["email_body"], draft["whatsapp_body"] = checklist.build_message(
            client, to_ask, notes, draft["kind"]
        )
        database.save_message(draft)
        return

    # Only write a new follow-up if something new arrived since our last message.
    last_sent = latest_sent_message(client["id"])
    newest_document = max((doc["received_at"] for doc in documents), default="")
    if last_sent is None or newest_document > last_sent["sent_at"]:
        subject, email_body, whatsapp_body = checklist.build_message(client, to_ask, notes, "Follow-up")
        database.add_message(client["id"], "Follow-up", subject, email_body, whatsapp_body)


def create_due_reminders(today):
    """Draft a reminder for clients who were messaged REMINDER_AFTER_DAYS ago and still have gaps."""
    created = []
    for client in database.get_all_clients():
        if client["status"] not in (config.STATUS_NEW, config.STATUS_DOCS_PENDING):
            continue
        if database.get_messages(config.MSG_WAITING, client["id"]):
            continue
        last_sent = latest_sent_message(client["id"])
        if last_sent is None:
            continue
        days_waiting = (today - date.fromisoformat(last_sent["sent_at"][:10])).days
        if days_waiting < config.REMINDER_AFTER_DAYS:
            continue
        documents = database.get_documents(client["id"])
        to_ask = checklist.documents_to_ask_for(client, documents)
        notes = checklist.notes_for_client(client, documents)
        if not to_ask and not notes:
            continue
        subject, email_body, whatsapp_body = checklist.build_message(client, to_ask, notes, "Reminder", days_waiting)
        database.add_message(client["id"], "Reminder", subject, email_body, whatsapp_body)
        created.append(f"Reminder drafted for {client['name']} (no reply for {days_waiting} days).")
    return created


def require_staff_name(staff_name):
    if not staff_name or not staff_name.strip():
        raise ValueError("Please type your name in the sidebar first. Every approval is recorded with a name.")


def approve_and_send(message_id, channel, subject, email_body, whatsapp_body, staff_name):
    """
    The ONLY place a message leaves the system, and only after a staff member clicks Approve.
    "Sending" in this prototype = saving the final message in the outbox folder
    and giving staff a ready link (mailto: or WhatsApp) to deliver it.
    """
    require_staff_name(staff_name)
    message = database.get_message(message_id)
    if message is None or message["status"] != config.MSG_WAITING:
        raise ValueError("This draft is no longer waiting for approval.")
    client = database.get_client(message["client_id"])
    if channel == "WhatsApp" and not validators.is_valid_phone(client["phone"]):
        raise ValueError("This client has no valid phone number, so WhatsApp is not possible.")

    body = email_body if channel == "Email" else whatsapp_body
    recipient = client["email"] if channel == "Email" else "+91 " + client["phone"]

    config.OUTBOX_DIR.mkdir(exist_ok=True)
    outbox_file = config.OUTBOX_DIR / f"message_{message_id}_{channel.lower()}.txt"
    outbox_file.write_text(
        f"To: {recipient}\nChannel: {channel}\nSubject: {subject}\n"
        f"Approved by: {staff_name}\nApproved at: {database.now()}\n\n{body}\n",
        encoding="utf-8",
    )

    message.update({
        "subject": subject,
        "email_body": email_body,
        "whatsapp_body": whatsapp_body,
        "status": config.MSG_SENT,
        "channel": channel,
        "approved_by": staff_name.strip(),
        "outbox_file": outbox_file.name,
        "sent_at": database.now(),
    })
    database.save_message(message)

    if channel == "Email":
        link = f"mailto:{client['email']}?subject={quote(subject)}&body={quote(body)}"
    else:
        link = f"https://wa.me/91{client['phone']}?text={quote(body)}"
    return {"client": client["name"], "channel": channel, "file": outbox_file.name, "link": link}


def reject_message(message_id, staff_name):
    require_staff_name(staff_name)
    message = database.get_message(message_id)
    message["status"] = config.MSG_REJECTED
    message["approved_by"] = staff_name.strip()
    database.save_message(message)


def accept_document(document_id, staff_name):
    require_staff_name(staff_name)
    document = database.get_document(document_id)
    document["status"] = config.DOC_ACCEPTED
    document["flags"].append(f"Accepted by {staff_name.strip()} after checking ({database.now()}).")
    database.save_document(document)
    refresh_client(document["client_id"])


def reject_document(document_id, staff_name):
    require_staff_name(staff_name)
    document = database.get_document(document_id)
    document["status"] = config.DOC_REJECTED
    document["flags"].append(f"Rejected by {staff_name.strip()} ({database.now()}).")
    if not document["client_note"]:
        document["client_note"] = "we could not verify it. Please send a clearer copy."
    database.save_document(document)
    refresh_client(document["client_id"])


def mark_received_by_staff(client_id, doc_type, staff_name):
    """For documents checked outside the system (e.g. the client brought the original to the office)."""
    require_staff_name(staff_name)
    report = {
        "doc_type": doc_type,
        "status": config.DOC_ACCEPTED,
        "fields": {},
        "flags": [f"Marked as received by {staff_name.strip()} (checked outside the system)."],
        "client_note": "",
        "sharpness": None,
    }
    database.add_document(client_id, "", "Staff", report)
    refresh_client(client_id)


def update_client_details(client_id, name, phone, pan, gstin, services, staff_name):
    """Staff correct details (e.g. after a phone call). Invalid values are still flagged."""
    require_staff_name(staff_name)
    client = database.get_client(client_id)
    client.update({
        "name": name.strip(),
        "phone": phone.strip(),
        "pan": validators.clean_code(pan),
        "gstin": validators.clean_code(gstin),
        "services": services,
    })
    database.save_client(client)
    database.add_flag(client_id, f"Details edited by {staff_name.strip()}.")
    if client["pan"] and not validators.is_valid_pan(client["pan"]):
        database.add_flag(client_id, f"Edited PAN '{client['pan']}' is still not a valid PAN format.")
    if client["phone"] and not validators.is_valid_phone(client["phone"]):
        database.add_flag(client_id, f"Edited phone '{client['phone']}' is not a valid 10-digit mobile number.")
    refresh_client(client_id)


def mark_onboarded(client_id, staff_name):
    require_staff_name(staff_name)
    client = database.get_client(client_id)
    if client["status"] != config.STATUS_READY:
        raise ValueError("Only clients that are 'Ready for review' can be onboarded.")
    client["status"] = config.STATUS_ONBOARDED
    database.save_client(client)
    database.add_flag(client_id, f"Onboarding approved by {staff_name.strip()}.")
    refresh_client(client_id)


def reset_everything():
    """Delete all records and generated files so the demo can start again."""
    database.reset_database()
    for folder in [config.OUTBOX_DIR, config.UPLOADS_DIR]:
        if folder.exists():
            for file in folder.iterdir():
                if file.is_file():
                    file.unlink()


if __name__ == "__main__":
    reset_everything()
    for line in process_inbox():
        print(line)
    print("\nTRACKER")
    for client in database.get_all_clients():
        documents = database.get_documents(client["id"])
        missing = checklist.documents_to_ask_for(client, documents)
        print(f"  #{client['id']} {client['name']:<16} {client['status']:<17} still missing: {', '.join(missing) or '-'}")
    print(f"\nDrafts waiting for staff approval: {len(database.get_messages(config.MSG_WAITING))}")
