import re

import config
import validators

HEADER = re.compile(
    r"^Email\s+(\d+)[^|]*\|\s*From:\s*(\S+)\s*\|\s*Attachments:\s*(.*)$",
    re.IGNORECASE,
)


def read_emails(file_path=config.EMAILS_FILE):
    """Split the text file into a list of emails. Each email is a dictionary."""
    emails = []
    current_email = None
    with open(file_path, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            header = HEADER.match(line)
            if header:
                attachments = [name.strip() for name in header.group(3).split(",") if name.strip()]
                current_email = {
                    "number": int(header.group(1)),
                    "sender": header.group(2).lower(),
                    "attachments": attachments,
                    "body": "",
                }
                emails.append(current_email)
            elif current_email is not None and line:
                current_email["body"] += line + " "
    return emails


def find_name(text):
    """Looks for phrases like "I'm Rohan Mehta", "My name is ..." or "Sunita Traders here"."""
    capitalised_words = r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"
    patterns = [
        r"\bI(?:'m|’m| am)\s+" + capitalised_words,
        r"\b[Mm]y name is\s+" + capitalised_words,
        r"\b" + capitalised_words + r"\s+here\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def find_pan(text):
    """First looks for "PAN <code>", then for any word shaped like a PAN."""
    labelled = re.search(r"\bPAN\b[\s:#-]*([A-Za-z0-9]*[0-9][A-Za-z0-9]*)", text)
    if labelled:
        return labelled.group(1).upper()
    anywhere = re.search(r"\b" + validators.PAN_FORMAT + r"\b", text)
    return anywhere.group(0) if anywhere else ""


def find_gstin(text):
    """First looks for "GSTIN <code>", then for any word shaped like a GSTIN."""
    labelled = re.search(r"\bGSTIN\b[\s:#-]*([A-Za-z0-9]+)", text)
    if labelled:
        return labelled.group(1).upper()
    anywhere = re.search(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}\b", text)
    return anywhere.group(0) if anywhere else ""


def find_phone(text):
    """Finds a 10-digit mobile number, even if written as '98765 00002' or '+91 98765-00002'."""
    match = re.search(r"(?<!\d)(?:\+?91[\s-]?)?([6-9]\d{4}[\s-]?\d{5})(?!\d)", text)
    if match:
        return re.sub(r"[^0-9]", "", match.group(1))
    return ""


def find_services(text):
    """Returns e.g. ['ITR'] or ['GST'] based on keywords in the email."""
    lower_text = text.lower()
    services = []
    for service, keywords in config.SERVICE_KEYWORDS.items():
        for keyword in keywords:
            if re.search(r"\b" + re.escape(keyword) + r"\b", lower_text):
                services.append(service)
                break
    return services


def extract_client_details(email):
    body = email["body"]
    return {
        "name": find_name(body),
        "email": email["sender"],
        "phone": find_phone(body),
        "pan": find_pan(body),
        "gstin": find_gstin(body),
        "services": find_services(body),
    }


def check_details(details, is_new_client):
    """Returns a list of problems with the details. We flag them, we never guess."""
    problems = []
    if details["pan"] and not validators.is_valid_pan(details["pan"]):
        problems.append(
            f"PAN '{details['pan']}' in the email is not a valid PAN format "
            "(should be 5 letters, 4 digits, 1 letter)."
        )
    if details["gstin"] and not validators.is_valid_gstin(details["gstin"]):
        problems.append(f"GSTIN '{details['gstin']}' in the email is not a valid GSTIN format.")

    # For an existing client, missing details are normal (they are already saved).
    if is_new_client:
        if not details["name"]:
            problems.append("Client name not found in the email.")
        if not details["phone"]:
            problems.append("Phone number not found in the email (WhatsApp follow-up not possible).")
        if not details["services"]:
            problems.append("Service (GST / ITR / Audit) not identified. Staff should set it.")
    return problems
