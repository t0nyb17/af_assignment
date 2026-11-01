import re

PAN_FORMAT = r"[A-Z]{5}[0-9]{4}[A-Z]"                               # e.g. ABCDE1234F
GSTIN_FORMAT = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]"    # e.g. 27ABCDE1234F1Z5
PHONE_FORMAT = r"[6-9][0-9]{9}"                                     # Indian mobile number
AADHAAR_FORMAT = r"[0-9]{4}\s?[0-9]{4}\s?[0-9]{4}"                  # 12 digits


def clean_code(value):
    """Remove spaces and use capital letters: ' abcde 1234f ' -> 'ABCDE1234F'."""
    return re.sub(r"\s+", "", value or "").upper()


def is_valid_pan(pan):
    """PAN = 5 letters, 4 digits, 1 letter."""
    return re.fullmatch(PAN_FORMAT, clean_code(pan)) is not None


def is_valid_gstin(gstin):
    """GSTIN = 2-digit state code + 10-character PAN + entity number + 'Z' + check character."""
    return re.fullmatch(GSTIN_FORMAT, clean_code(gstin)) is not None


def pan_inside_gstin(gstin):
    """Characters 3 to 12 of a GSTIN are the PAN of the business."""
    return clean_code(gstin)[2:12]


def is_valid_phone(phone):
    """10 digits starting with 6, 7, 8 or 9."""
    return re.fullmatch(PHONE_FORMAT, phone or "") is not None


def is_valid_aadhaar(number):
    """Exactly 12 digits (spaces between the groups are allowed)."""
    return re.fullmatch(AADHAAR_FORMAT, (number or "").strip()) is not None


def mask_aadhaar(number):
    """Keep only the last 4 digits: '1234 5678 9012' -> 'XXXX XXXX 9012'."""
    digits = re.sub(r"[^0-9]", "", number or "")
    return "XXXX XXXX " + digits[-4:]


def normalise_name(name):
    """'  Rohan  mehta. ' -> 'ROHAN MEHTA' so two names can be compared fairly."""
    letters_only = re.sub(r"[^A-Za-z ]", " ", name or "")
    return " ".join(letters_only.upper().split())


def names_match(name_a, name_b):
    return normalise_name(name_a) == normalise_name(name_b)
