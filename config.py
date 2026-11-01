"""
Settings for the Client Onboarding prototype.

Everything a CA firm might want to change (checklists, reminder days,
quality limits) is kept here, so nobody has to dig through the code.
"""
from pathlib import Path

# ---------------- Folders and files ----------------
BASE_DIR = Path(__file__).parent
INBOX_DIR = BASE_DIR / "inbox"            # sample emails + their attachments
EMAILS_FILE = INBOX_DIR / "sample_emails.txt"
UPLOADS_DIR = BASE_DIR / "uploads"        # documents that staff upload later
OUTBOX_DIR = BASE_DIR / "outbox"          # approved messages are saved here
DATABASE_FILE = BASE_DIR / "onboarding.db"

FIRM_NAME = "Absolute Finance"


REMINDER_AFTER_DAYS = 3

MIN_FIELD_CONFIDENCE = 0.85

MIN_SHARPNESS = 800

SERVICE_KEYWORDS = {
    "GST": ["gst", "gstin"],
    "ITR": ["itr", "income tax return", "tax return"],
    "Audit": ["audit"],
}
REQUIRED_DOCUMENTS = {
    "ITR": ["PAN card", "Aadhaar card", "Bank statement"],
    "GST": ["PAN card", "Aadhaar card", "GST certificate", "Bank statement"],
    "Audit": ["PAN card", "GST certificate", "Bank statement"],
}

STATUS_NEW = "New"                    # record created, no documents / service unknown
STATUS_DOCS_PENDING = "Docs pending"  # something is missing or needs checking
STATUS_READY = "Ready for review"     # every checklist document is received
STATUS_ONBOARDED = "Onboarded"        # a staff member approved the onboarding
ALL_STATUSES = [STATUS_NEW, STATUS_DOCS_PENDING, STATUS_READY, STATUS_ONBOARDED]

DOC_ACCEPTED = "Accepted"           # read clearly, all checks passed
DOC_NEEDS_REVIEW = "Needs review"   # readable, but something looks wrong
DOC_REJECTED = "Rejected"           # blurry, wrong document, or unreadable

MSG_WAITING = "Waiting for approval"
MSG_SENT = "Sent"
MSG_REJECTED = "Rejected"
MSG_CANCELLED = "Cancelled"         # draft no longer needed (e.g. all docs arrived)
