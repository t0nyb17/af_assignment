import sys

import config
import document_reader
import email_reader
import validators

results = []


def check(condition, description):
    print(("PASS  " if condition else "FAIL  ") + description)
    results.append(condition)


print("--- Rules ---")
check(validators.is_valid_pan("ABCDE1234F"), "ABCDE1234F is a valid PAN")
check(not validators.is_valid_pan("ABCDE12345"), "ABCDE12345 is NOT a valid PAN (last character must be a letter)")
check(validators.is_valid_gstin("27ABCDE1234F1Z5"), "27ABCDE1234F1Z5 is a valid GSTIN format")
check(validators.pan_inside_gstin("27ABCDE1234F1Z5") == "ABCDE1234F", "PAN inside the GSTIN is ABCDE1234F")
check(validators.is_valid_phone("9876500001"), "9876500001 is a valid mobile number")
check(not validators.is_valid_phone("12345"), "12345 is NOT a valid mobile number")
check(validators.mask_aadhaar("1234 5678 9012") == "XXXX XXXX 9012", "Aadhaar is masked to the last 4 digits")
check(validators.names_match("ROHAN MEHTA", "Rohan  Mehta"), "Names match ignoring capitals and spaces")

print("\n--- Emails ---")
emails = email_reader.read_emails()
check(len(emails) == 5, "5 emails read from the sample file")
one, two, three = (email_reader.extract_client_details(email) for email in emails[:3])
check(one["name"] == "Rohan Mehta" and one["pan"] == "ABCDE1234F" and one["phone"] == "9876500001", "Email 1: Rohan Mehta, PAN and phone found")
check(one["services"] == ["ITR"], "Email 1: service is ITR")
check(two["name"] == "Sunita Traders" and two["gstin"] == "27ABCDE1234F1Z5" and two["phone"] == "9876500002", "Email 2: Sunita Traders, GSTIN and phone '98765 00002' found")
check(two["services"] == ["GST"], "Email 2: service is GST")
check(three["name"] == "Amit Shah" and three["services"] == ["Audit"], "Email 3: Amit Shah, service is Audit")
check(three["pan"] == "ABCDE12345" and three["phone"] == "", "Email 3: invalid PAN captured as-is, no phone")
check(len(email_reader.check_details(three, is_new_client=True)) == 2, "Email 3: 2 problems flagged (invalid PAN, no phone)")

print("\n--- Documents (this loads the OCR model, give it a few seconds) ---")
no_client = {"name": "", "pan": "", "gstin": ""}


def read(file_name, client=no_client):
    return document_reader.analyse_document(config.INBOX_DIR / file_name, client)


pan = read("sample_pan_rohan.png")
check(pan["doc_type"] == "PAN card" and pan["status"] == config.DOC_ACCEPTED, "Rohan's PAN card is accepted")
check(pan["fields"]["pan"]["value"] == "ABCDE1234F", "PAN number read from the card")

aadhaar = read("sample_aadhaar_rohan.png")
check(aadhaar["doc_type"] == "Aadhaar card", "Aadhaar card recognised")
check(aadhaar["fields"]["aadhaar_number"]["value"] == "XXXX XXXX 9012", "Aadhaar number stored masked")

gst = read("sample_gst_sunita.png")
check(gst["doc_type"] == "GST certificate" and gst["fields"]["gstin"]["value"] == "27ABCDE1234F1Z5", "GST certificate and GSTIN read")

bank = read("sample_bank_statement_sunita.pdf")
check(bank["doc_type"] == "Bank statement" and bank["fields"]["account_holder"]["value"] == "SUNITA TRADERS", "Scanned bank statement PDF read")

print("\n--- Failure cases ---")
invalid = read("sample_pan_amit_invalid.png")
check(invalid["status"] == config.DOC_NEEDS_REVIEW and "Invalid PAN" in invalid["flags"][0], "Invalid PAN is flagged (Needs review)")

blurry = read("sample_pan_rohan_blurry.png")
check(blurry["doc_type"] == "Unreadable" and blurry["status"] == config.DOC_REJECTED, "Blurry scan is rejected, nothing guessed")

wrong = read("sample_wrong_document_electricity_bill.png")
check(wrong["doc_type"] == "Wrong document" and wrong["status"] == config.DOC_REJECTED, "Electricity bill is rejected as a wrong document")

mismatch = read("sample_pan_rohan.png", {"name": "Amit Shah", "pan": "", "gstin": ""})
check(any("Name mismatch" in flag for flag in mismatch["flags"]), "Rohan's PAN sent for Amit is flagged as a name mismatch")

missing = read("file_that_does_not_exist.png")
check(missing["status"] == config.DOC_REJECTED, "A missing attachment is rejected, the program does not crash")

passed = sum(results)
print(f"\n{passed} of {len(results)} checks passed.")
sys.exit(0 if passed == len(results) else 1)
