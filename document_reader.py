import re
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat
from pypdf import PdfReader
from rapidocr import RapidOCR

import config
import validators

SUPPORTED_FILES = [".png", ".jpg", ".jpeg", ".pdf"]

# Words that tell us what kind of document it is (checked in this order).
DOCUMENT_KEYWORDS = {
    "PAN card": ["INCOME TAX DEPARTMENT", "PERMANENT ACCOUNT NUMBER"],
    "Aadhaar card": ["AADHAAR", "UNIQUE IDENTIFICATION AUTHORITY"],
    "Bank statement": ["ACCOUNT STATEMENT", "STATEMENT OF ACCOUNT", "ACCOUNT HOLDER"],
    "GST certificate": ["GST REGISTRATION", "GSTIN"],
}

# For each document type: field name -> pattern that finds the value on one line of text.
FIELD_PATTERNS = {
    "PAN card": {
        "name": r"^Name\s*:\s*(.+)$",
        "father_name": r"^Father(?:'s name)?\s*:\s*(.+)$",
        "date_of_birth": r"^DOB\s*:\s*(.+)$",
        "pan": r"^PAN\s*:\s*(.+)$",
    },
    "Aadhaar card": {
        "name": r"^Name\s*:\s*(.+)$",
        "date_of_birth": r"^DOB\s*:\s*(.+)$",
        "gender": r"^(Male|Female|Transgender)$",
        "aadhaar_number": r"^Aadhaar\s*:\s*(.+)$",
    },
    "GST certificate": {
        "legal_name": r"^Legal name\s*:\s*(.+)$",
        "gstin": r"^GSTIN\s*:\s*(.+)$",
        "state": r"^State\s*:\s*(.+)$",
        "registration_type": r"^Type\s*:\s*(.+)$",
        "registration_date": r"^Date of registration\s*:\s*(.+)$",
    },
    "Bank statement": {
        "account_holder": r"Account holder\s*:\s*(.+?)(?:\s+A/c|$)",
        "account_number": r"A/c\s*:\s*(\S+)",
    },
}

# Which field holds the person's / business's name on each document.
NAME_FIELD = {
    "PAN card": "name",
    "Aadhaar card": "name",
    "GST certificate": "legal_name",
    "Bank statement": "account_holder",
}

_ocr_engine = None


def get_ocr_engine():
    """Load the OCR model only once (it takes a couple of seconds) and reuse it."""
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR(params={"Global.log_level": "critical"})
    return _ocr_engine


def measure_sharpness(image):
    """
    Sharp images have crisp edges, blurry images have soft edges.
    We highlight the edges and measure how much they vary.
    A low number means the image is blurry.
    """
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    return ImageStat.Stat(edges).var[0]


def read_lines(path):
    """
    Turn a file into a list of (text, confidence) lines.
    Also returns the sharpness of the blurriest page
    (None for a digital PDF, because its text is exact).
    """
    images = []
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        typed_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if typed_text.strip():
            lines = [(line.strip(), 1.0) for line in typed_text.splitlines() if line.strip()]
            return lines, None
        # A scanned PDF only contains pictures of the pages, so we read those pictures.
        for page in reader.pages:
            for picture in page.images:
                images.append(picture.image.convert("RGB"))
    else:
        with Image.open(path) as picture:
            images.append(picture.convert("RGB"))

    lines = []
    sharpness_values = []
    for image in images:
        sharpness_values.append(measure_sharpness(image))
        result = get_ocr_engine()(image)
        for text, score in zip(result.txts or [], result.scores or []):
            lines.append((text, float(score)))

    sharpness = min(sharpness_values) if sharpness_values else None
    return lines, sharpness


def identify_document(lines):
    """Returns 'PAN card', 'Aadhaar card', ... or None if it is none of them."""
    all_text = " ".join(text for text, _ in lines).upper()
    for doc_type, keywords in DOCUMENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in all_text:
                return doc_type
    return None


def extract_fields(doc_type, lines):
    """Go through the lines and pick out each field with the confidence of its line."""
    fields = {}
    for field_name, pattern in FIELD_PATTERNS[doc_type].items():
        for text, confidence in lines:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields[field_name] = {"value": match.group(1).strip(), "confidence": round(confidence, 3)}
                break
    return fields


def check_fields(doc_type, fields, client):
    """
    Returns (flags, client_note).
    flags       = problems for staff to look at
    client_note = one short sentence we may need to tell the client
    """
    flags = []
    client_note = ""

    # Every expected field must be found and read with enough confidence.
    for field_name in FIELD_PATTERNS[doc_type]:
        label = field_name.replace("_", " ")
        if field_name not in fields:
            flags.append(f"Could not find '{label}' on the document.")
        elif fields[field_name]["confidence"] < config.MIN_FIELD_CONFIDENCE:
            score = fields[field_name]["confidence"]
            flags.append(f"Low confidence reading '{label}' ({score:.0%}). Please check it by eye.")

    def value_of(field_name):
        return fields.get(field_name, {}).get("value", "")

    if doc_type == "PAN card":
        pan = validators.clean_code(value_of("pan"))
        if pan and not validators.is_valid_pan(pan):
            flags.append(f"Invalid PAN format '{pan}' (should be 5 letters, 4 digits, 1 letter).")
            client_note = (
                f"the PAN on it ({pan}) does not look valid. "
                "Please check it and send a clear copy of your PAN card."
            )
        elif pan and validators.is_valid_pan(client["pan"]) and pan != validators.clean_code(client["pan"]):
            flags.append(f"PAN mismatch: the card says {pan}, the email says {client['pan']}.")
            client_note = "the PAN on the card does not match the PAN in your email. Please confirm the correct PAN."

    if doc_type == "Aadhaar card":
        number = value_of("aadhaar_number")
        if number and not validators.is_valid_aadhaar(number):
            flags.append("Aadhaar number is not 12 digits.")
            client_note = "the Aadhaar number on it could not be read correctly. Please send a clearer copy."
        if number:
            # Privacy: we never store the full Aadhaar number, only the last 4 digits.
            fields["aadhaar_number"]["value"] = validators.mask_aadhaar(number)

    if doc_type == "GST certificate":
        gstin = validators.clean_code(value_of("gstin"))
        if gstin and not validators.is_valid_gstin(gstin):
            flags.append(f"Invalid GSTIN format '{gstin}'.")
            client_note = "the GSTIN on the certificate could not be verified. Please send a clear copy."
        if gstin and client["gstin"] and gstin != validators.clean_code(client["gstin"]):
            flags.append(f"GSTIN mismatch: the certificate says {gstin}, the email says {client['gstin']}.")
        if validators.is_valid_gstin(gstin) and validators.is_valid_pan(client["pan"]):
            if validators.pan_inside_gstin(gstin) != validators.clean_code(client["pan"]):
                flags.append(
                    f"The PAN inside the GSTIN ({validators.pan_inside_gstin(gstin)}) "
                    f"is different from the client's PAN ({client['pan']})."
                )

    # The name on the document must match the name on the client record.
    name_on_document = value_of(NAME_FIELD[doc_type])
    if name_on_document and client["name"] and not validators.names_match(name_on_document, client["name"]):
        flags.append(f"Name mismatch: the document says '{name_on_document}', the client record says '{client['name']}'.")
        if not client_note:
            client_note = f"the name on it ({name_on_document}) does not match the name we have ({client['name']})."

    return flags, client_note


def analyse_document(file_path, client):
    """
    Main function of this file. Returns a "report" dictionary:
      doc_type, status, fields, flags, client_note, sharpness
    """
    path = Path(file_path)
    report = {
        "doc_type": "Unknown",
        "status": config.DOC_REJECTED,
        "fields": {},
        "flags": [],
        "client_note": "",
        "sharpness": None,
    }

    # 1. Can we open the file at all?
    if not path.exists():
        report["flags"].append("File not found. The attachment may be missing from the email.")
        report["client_note"] = "the attachment did not reach us. Please send it again."
        return report
    if path.suffix.lower() not in SUPPORTED_FILES:
        report["flags"].append(f"Unsupported file type '{path.suffix}'. Only PDF, JPG and PNG can be read.")
        report["client_note"] = "we can only accept PDF, JPG or PNG files."
        return report
    try:
        lines, sharpness = read_lines(path)
    except Exception as error:
        report["flags"].append(f"Could not open the file ({error}).")
        report["client_note"] = "the file seems damaged and could not be opened. Please send it again."
        return report
    if sharpness is not None:
        report["sharpness"] = round(sharpness)

    # 2. Is it readable? (blurry scan check)
    if sharpness is not None and sharpness < config.MIN_SHARPNESS:
        report["doc_type"] = "Unreadable"
        report["flags"].append(
            f"Blurry scan: sharpness {sharpness:.0f} is below the minimum of {config.MIN_SHARPNESS}. "
            "Nothing was extracted, to avoid guessing."
        )
        report["client_note"] = "the scan is too blurry to read. Please send a clearer photo or PDF."
        return report
    if not lines:
        report["doc_type"] = "Unreadable"
        report["flags"].append("No text could be read from this file.")
        report["client_note"] = "we could not read any text in it. Please send a clearer copy."
        return report

    # 3. Is it one of the documents we accept? (wrong document check)
    doc_type = identify_document(lines)
    if doc_type is None:
        title = lines[0][0]
        report["doc_type"] = "Wrong document"
        report["flags"].append(
            f"This is not a PAN card, Aadhaar card, GST certificate or bank statement. "
            f"The document title reads '{title}'."
        )
        report["client_note"] = f"it looks like a different document ('{title}'), not one of the documents we asked for."
        return report

    # 4. Pull out the fields and check each one.
    report["doc_type"] = doc_type
    report["fields"] = extract_fields(doc_type, lines)
    report["flags"], report["client_note"] = check_fields(doc_type, report["fields"], client)
    if report["flags"]:
        report["status"] = config.DOC_NEEDS_REVIEW
    else:
        report["status"] = config.DOC_ACCEPTED
    return report
