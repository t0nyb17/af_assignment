# Screen recording of the working project
<video controls src="20261101_151803.mp4" title="Title"></video>

# Client Onboarding Automation for a CA Firm (Prototype)

A small Python app that takes new-client emails and their documents and:

1. **Intake**: reads the emails and creates a client record (name, PAN, email, phone, service).
2. **Document extraction**: reads PAN, Aadhaar, GST certificate and bank statement images/PDFs with OCR, pulls out the key fields and **flags** low-confidence or mismatched values instead of guessing.
3. **Checklist and follow-up**: builds a document checklist per service and drafts an email and a WhatsApp message asking for what is missing, plus a reminder after a set number of days.
4. **Tracker**: a dashboard showing every client's status (New, Docs pending, Ready for review, Onboarded), downloadable as a CSV sheet.
5. **Human approval**: nothing is sent to a client until a named staff member approves it.

All data is the dummy data from the provided sample pack. No real IDs are used.

---

## Where each requirement is implemented

| Requirement | File | Main function |
|---|---|---|
| Intake (emails → client record) | `email_reader.py`, `pipeline.py` | `read_emails`, `extract_client_details`, `process_email` |
| Document extraction + flags | `document_reader.py` | `analyse_document` |
| Checklist by service | `config.py`, `checklist.py` | `REQUIRED_DOCUMENTS`, `checklist_for` |
| Email / WhatsApp drafts + reminder | `checklist.py`, `pipeline.py` | `build_message`, `update_draft`, `create_due_reminders` |
| Tracker (statuses, sheet export) | `app.py`, `checklist.py` | `show_tracker`, `work_out_status` |
| Human approval | `pipeline.py`, `app.py` | `approve_and_send`, `show_approval_queue` |
| Failure cases | `document_reader.py`, `pipeline.py` | see the "Failure cases" table below |

---

## Setup

**You need:** Python 3.11, 3.12 or 3.13 (tested on 3.13). No other software is needed: the OCR models come inside the `rapidocr` Python package.

```bash
# 1. Go into the project folder
cd client-onboarding

# 2. Create and switch on a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac / Linux:
source venv/bin/activate

# 3. Install the libraries (the first install can take a few minutes)
pip install -r requirements.txt

# 4. (Optional) Run the self-check: 27 checks, including all failure cases
python test_rules.py

# 5. Start the dashboard (it opens at http://localhost:8501)
streamlit run app.py
```

If you don't want the dashboard, `python pipeline.py` processes the inbox and prints the log and tracker in the terminal.

## How to use the dashboard

1. Type your name in the sidebar (every approval is saved with a name).
2. Click **Read inbox emails**. The log shows what happened to every email and attachment.
3. **Tracker** tab: status counts, the client table and **Download tracker as CSV**.
4. **Client details** tab: the client record, checklist, warnings, extracted fields with confidence scores, and staff actions (accept or reject a flagged document, upload a document received later, mark a document as received, edit details, approve onboarding).
5. **Approval queue** tab: edit the email or WhatsApp draft, then **Approve and send** or **Reject draft**.
6. To test reminders, move **Today's date** in the sidebar forward 3+ days and click **Check for reminders**.
7. **Reset all data** starts the demo again.

## Project structure

```
client-onboarding/
├── app.py              Dashboard: tracker, client details, approval queue (Streamlit)
├── pipeline.py         Connects all steps + every staff action
├── email_reader.py     Step 1: reads emails, finds name / PAN / phone / GSTIN / service
├── document_reader.py  Step 2: OCR, document type, field extraction, quality checks
├── checklist.py        Step 3: checklist, status, message drafts
├── validators.py       Small rule checks (PAN, GSTIN, phone, Aadhaar, names)
├── database.py         Saving / loading with SQLite
├── config.py           All settings (checklists, reminder days, thresholds)
├── test_rules.py       Self-check script
├── requirements.txt
├── inbox/              The 5 sample emails + dummy documents
├── outbox/             (created at runtime) approved messages
└── uploads/            (created at runtime) documents uploaded by staff
```

---

## Design choices

- **Python + Streamlit.** Streamlit builds a web dashboard from plain Python, so there is no separate frontend to write. The whole project is one language.
- **OCR + rules instead of an LLM.** The brief says *"flag low-confidence or mismatched fields rather than guessing"*. RapidOCR (PaddleOCR models running on ONNX Runtime) gives a **confidence score for every line of text** it reads, and regular-expression rules either match or don't. An LLM can return a confident-looking value that isn't on the page, and that is exactly the guessing we need to avoid. It also means no API key, no cost, and client documents never leave the computer.
- **Checks in a fixed order.** Each document goes through: can the file be opened → is it sharp enough → is it a document we accept → are the fields present, confident and valid → do they match the client record. The first failure decides the outcome, and the reason is saved.
- **Three document outcomes.** `Accepted` (counts towards the checklist), `Needs review` (readable but suspicious, so staff decide), `Rejected` (blurry, wrong or unreadable, so the client is asked again).
- **Duplicate detection.** A new email is matched to an existing client by email address or by a valid PAN. A match is merged into the existing record, never created twice. Conflicting values are kept as they were and flagged.
- **Safe to re-run.** Every processed email is recorded, so clicking "Read inbox emails" twice creates nothing new.
- **SQLite database.** It is built into Python, stored in one file, and needs no server. All queries use `?` placeholders (no SQL injection).
- **Human approval by design.** Drafts are saved as `Waiting for approval`. The only function that "sends" (`approve_and_send`) needs a staff name and runs only when the Approve button is clicked. Staff can edit the text first.
- **Privacy.** Only the last 4 digits of an Aadhaar number are stored (`XXXX XXXX 9012`).
- **Settings in one file.** Checklists, reminder days, the confidence threshold (0.85) and the sharpness threshold (800) are all in `config.py`.

## Failure cases and how they are handled

| Case (sample file) | How it is detected | What happens |
|---|---|---|
| **Invalid PAN** (`ABCDE12345`, email 3 + `sample_pan_amit_invalid.png`) | Regex: PAN must be 5 letters + 4 digits + 1 letter | Client warning, document set to **Needs review**, draft tells the client the PAN looks invalid |
| **Blurry scan** (`sample_pan_rohan_blurry.png`) | Sharpness score 308, below the minimum of 800 (clear samples score about 1650-2970) | **Rejected** as Unreadable. Nothing is extracted, so nothing is guessed. Draft asks for a clearer copy |
| **Duplicate client** (emails 4 and 5 from `rohan@example.com`) | Same email address (or same valid PAN) as an existing client | Merged into client #1, no second record, warning added for staff |
| **Wrong document** (`sample_wrong_document_electricity_bill.png`) | Text contains none of the PAN / Aadhaar / GST / bank keywords | **Rejected** as Wrong document, with its title shown. Draft tells the client it isn't a document we asked for |
| **Mismatch found in the test data** | The PAN inside Sunita's GSTIN (`ABCDE1234F`) is already saved as Rohan Mehta's PAN | GST certificate set to **Needs review** with the reason. Staff must accept or reject it |
| Name or PAN on a document differs from the client record | Name comparison that ignores capitals and spaces, plus a PAN comparison | **Needs review** + a mismatch flag |
| Low OCR confidence | Any field read below 0.85 confidence | **Needs review** + "please check by eye" |
| Missing / unsupported / damaged attachment | File checks before OCR | **Rejected** with a reason. The app does not crash |
| Phone number missing (email 3) | No 10-digit mobile number found | Warning. WhatsApp is disabled for that client, email only |
| Service not identified | No GST / ITR / audit keyword found | Status stays **New** and staff set the service |

Note: the labels "(duplicate)" and "(wrong doc)" in `sample_emails.txt` are ignored by the code. The system detects these cases on its own.

## Limitations

- **Intake reads a sample text file**, not a live mailbox. In production this would be replaced by reading a real inbox (for example with Python's built-in `imaplib`, or the Gmail API).
- **Sending is simulated.** Approved messages are saved in `outbox/`, and the dashboard gives a ready `mailto:` or WhatsApp (`wa.me`) link. Real sending would need SMTP or the WhatsApp Business API.
- **Field extraction is template-based.** The patterns match the layout of the sample documents (for example `Name: ...`, `PAN: ...`). Real PAN cards, Aadhaar cards and bank statements come in many layouts and would need more patterns or a trained document model.
- **Format checks only.** PAN, GSTIN and Aadhaar are checked for the right shape, not against government databases. The GSTIN check character and the Aadhaar Verhoeff checksum are not verified, and neither is the PAN's 4th character (holder type, e.g. `P` for an individual). The sample data uses dummy values that would fail these stricter checks.
- **The thresholds were tuned on the sample files** (sharpness 800, confidence 0.85). Real scans would need re-tuning.
- **Name extraction from the email** looks for phrases like "I'm ...", "My name is ..." and "... here". Other wordings leave the name blank, which is flagged, and it is filled in from an ID document if one arrives.
- **Checklists are simplified examples**, and the firm should set its own in `config.py`.
- **Single user, local only.** There is no login. The staff name is typed in, which is enough for a prototype audit trail but not for production.
- For scanned PDFs, the pictures inside each page are read with OCR, so long PDFs are slow. The dashboard shows no preview for PDFs.

