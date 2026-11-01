import config

RECEIVED = "Received"
NEEDS_REVIEW = "Needs review"
MISSING = "Missing"


def required_documents(services):
    """E.g. ['ITR'] -> ['PAN card', 'Aadhaar card', 'Bank statement'] (no repeats)."""
    needed = []
    for service in services:
        for document in config.REQUIRED_DOCUMENTS.get(service, []):
            if document not in needed:
                needed.append(document)
    return needed


def checklist_for(client, documents):
    """Returns a list of (document type, state). State is Received, Needs review or Missing."""
    rows = []
    for doc_type in required_documents(client["services"]):
        statuses = [doc["status"] for doc in documents if doc["doc_type"] == doc_type]
        if config.DOC_ACCEPTED in statuses:
            state = RECEIVED
        elif config.DOC_NEEDS_REVIEW in statuses:
            state = NEEDS_REVIEW
        else:
            state = MISSING
        rows.append((doc_type, state))
    return rows


def work_out_status(client, documents):
    if client["status"] == config.STATUS_ONBOARDED:
        return config.STATUS_ONBOARDED
    if not documents or not client["services"]:
        return config.STATUS_NEW
    for _, state in checklist_for(client, documents):
        if state != RECEIVED:
            return config.STATUS_DOCS_PENDING
    return config.STATUS_READY


def documents_to_ask_for(client, documents):
    """Only the documents we have not received at all (Needs review ones are with staff)."""
    return [doc_type for doc_type, state in checklist_for(client, documents) if state == MISSING]


def notes_for_client(client, documents):
    """
    Problems with files the client sent, e.g. ('scan.png', 'the scan is too blurry ...').
    Skipped if that document type has since been received properly.
    """
    received = [doc_type for doc_type, state in checklist_for(client, documents) if state == RECEIVED]
    notes = []
    for doc in documents:
        if doc["status"] != config.DOC_ACCEPTED and doc["client_note"] and doc["doc_type"] not in received:
            file_name = doc["file_path"].replace("\\", "/").split("/")[-1]
            notes.append((file_name, doc["client_note"]))
    return notes


def build_message(client, to_ask, notes, kind, days_waiting=0):
    """Returns (subject, email_body, whatsapp_body)."""
    name = client["name"] or "Sir/Madam"
    services = ", ".join(client["services"]) or "your work"

    if kind == "Reminder":
        subject = f"Reminder: documents still needed for your {services} onboarding"
        opening = f"This is a friendly reminder. It has been {days_waiting} days and we are still waiting for some documents."
    else:
        subject = f"Documents needed to complete your {services} onboarding"
        opening = f"Thank you for choosing {config.FIRM_NAME} for {services}."

    email_lines = [f"Dear {name},", "", opening, ""]
    if to_ask:
        email_lines.append("To complete your onboarding, please send us:")
        for number, document in enumerate(to_ask, start=1):
            email_lines.append(f"  {number}. {document}")
        email_lines.append("")
    if notes:
        email_lines.append("We could not use some of the files you sent:")
        for file_name, note in notes:
            email_lines.append(f"  - {file_name}: {note}")
        email_lines.append("")
    email_lines += [
        "You can simply reply to this email with the documents attached (PDF, JPG or PNG).",
        "",
        "Regards,",
        "Onboarding Team",
        config.FIRM_NAME,
    ]

    whatsapp_parts = [f"Hi {name}, this is {config.FIRM_NAME} about your {services} onboarding."]
    if kind == "Reminder":
        whatsapp_parts.append("Friendly reminder:")
    if to_ask:
        whatsapp_parts.append("Please send: " + ", ".join(to_ask) + ".")
    for file_name, note in notes:
        whatsapp_parts.append(f"About {file_name}: {note}")
    whatsapp_parts.append("Thank you!")

    return subject, "\n".join(email_lines), " ".join(whatsapp_parts)
