from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import checklist
import config
import database
import pipeline
import validators

st.set_page_config(page_title="Client Onboarding | Absolute Finance", layout="wide")
database.create_tables()

STATE_COLOURS = {checklist.RECEIVED: "green", checklist.NEEDS_REVIEW: "orange", checklist.MISSING: "red"}


def show_flash_message():
    """Show a message saved before the last page refresh (st.rerun)."""
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))



def show_sidebar():
    with st.sidebar:
        st.header("Staff controls")
        staff_name = st.text_input(
            "Your name", placeholder="e.g. Priya", help="Needed before you approve anything. It is saved with every approval."
        )
        if not staff_name:
            st.caption("Type your name to enable the approve buttons.")

        st.subheader("1. Intake")
        if st.button("Read inbox emails", type="primary"):
            with st.spinner("Reading emails and documents (first run loads the OCR model)..."):
                st.session_state["log"] = pipeline.process_inbox()

        st.subheader("2. Reminders")
        today = st.date_input("Today's date", value=date.today(), help="Move this date forward to pretend days have passed.")
        if st.button("Check for reminders"):
            st.session_state["reminder_log"] = pipeline.create_due_reminders(today) or ["No reminders are due on this date."]
        st.caption(f"A reminder is drafted {config.REMINDER_AFTER_DAYS} days after the last sent message if documents are still missing.")

        st.subheader("Demo")
        if st.button("Reset all data"):
            pipeline.reset_everything()
            st.session_state.clear()
            st.rerun()
    return staff_name


def show_tracker(clients):
    columns = st.columns(len(config.ALL_STATUSES))
    for column, status in zip(columns, config.ALL_STATUSES):
        column.metric(status, sum(1 for client in clients if client["status"] == status))

    if not clients:
        st.info("No clients yet. Click 'Read inbox emails' in the sidebar to start.")
        return

    rows = []
    for client in clients:
        documents = database.get_documents(client["id"])
        not_received = [doc for doc, state in checklist.checklist_for(client, documents) if state != checklist.RECEIVED]
        rows.append({
            "ID": client["id"],
            "Name": client["name"],
            "Email": client["email"],
            "Phone": client["phone"],
            "PAN": client["pan"],
            "GSTIN": client["gstin"],
            "Services": ", ".join(client["services"]),
            "Status": client["status"],
            "Not yet received": ", ".join(not_received) or "-",
            "Warnings": len(database.get_flags(client["id"])),
        })
    table = pd.DataFrame(rows)
    st.dataframe(table, hide_index=True)
    st.download_button(
        "Download tracker as CSV (opens in Excel or Google Sheets)",
        table.to_csv(index=False),
        file_name="client_tracker.csv",
        mime="text/csv",
    )


def show_document(document, staff_name):
    file_name = Path(document["file_path"]).name if document["file_path"] else "(no file - marked by staff)"
    title = f"{file_name}  |  {document['doc_type']}  |  {document['status']}"
    with st.expander(title, expanded=document["status"] != config.DOC_ACCEPTED):
        picture_column, details_column = st.columns([1, 2])

        with picture_column:
            path = Path(document["file_path"]) if document["file_path"] else None
            if path and path.exists() and path.suffix.lower() in (".png", ".jpg", ".jpeg"):
                st.image(str(path))
            elif path and path.suffix.lower() == ".pdf":
                st.caption("PDF file (preview not shown).")

        with details_column:
            st.caption(
                f"Source: {document['source']}  |  Received: {document['received_at']}  |  "
                f"Sharpness: {document['sharpness'] if document['sharpness'] is not None else '-'}"
            )
            if document["fields"]:
                field_rows = [
                    {"Field": name.replace("_", " "), "Value": field["value"], "Confidence": f"{field['confidence']:.0%}"}
                    for name, field in document["fields"].items()
                ]
                st.dataframe(pd.DataFrame(field_rows), hide_index=True)
            for flag in document["flags"]:
                st.warning(flag)
            if document["client_note"]:
                st.caption(f"What we will tell the client: {document['client_note']}")

            if document["status"] == config.DOC_NEEDS_REVIEW:
                accept_column, reject_column = st.columns(2)
                if accept_column.button("Accept (I checked it)", key=f"accept_{document['id']}", disabled=not staff_name):
                    pipeline.accept_document(document["id"], staff_name)
                    st.session_state["flash"] = f"{file_name} accepted."
                    st.rerun()
                if reject_column.button("Reject", key=f"reject_{document['id']}", disabled=not staff_name):
                    pipeline.reject_document(document["id"], staff_name)
                    st.session_state["flash"] = f"{file_name} rejected. The client will be asked again."
                    st.rerun()


def show_staff_actions(client, documents, staff_name):
    st.subheader("Staff actions")
    upload_column, manual_column = st.columns(2)

    with upload_column:
        uploaded = st.file_uploader(
            "Client sent a document later? Upload it here",
            type=["png", "jpg", "jpeg", "pdf"],
            key=f"upload_{client['id']}",
        )
        if uploaded is not None and st.button("Read uploaded document", key=f"read_{client['id']}"):
            with st.spinner("Reading document..."):
                path = pipeline.save_upload(client["id"], uploaded.name, uploaded.getvalue())
                result = pipeline.add_document(client["id"], path, "Uploaded by staff")
                pipeline.refresh_client(client["id"])
            st.session_state["flash"] = result
            st.rerun()

    with manual_column:
        not_received = [doc for doc, state in checklist.checklist_for(client, documents) if state == checklist.MISSING]
        if not_received:
            doc_type = st.selectbox(
                "Mark a document as received (checked outside the system)",
                not_received,
                key=f"manual_{client['id']}",
            )
            if st.button("Mark as received", key=f"mark_{client['id']}", disabled=not staff_name):
                pipeline.mark_received_by_staff(client["id"], doc_type, staff_name)
                st.session_state["flash"] = f"{doc_type} marked as received."
                st.rerun()

    with st.expander("Edit client details (for example after a phone call)"):
        with st.form(f"edit_{client['id']}"):
            name = st.text_input("Name", client["name"], key=f"name_{client['id']}")
            phone = st.text_input("Phone (10 digits)", client["phone"], key=f"phone_{client['id']}")
            pan = st.text_input("PAN", client["pan"], key=f"pan_{client['id']}")
            gstin = st.text_input("GSTIN", client["gstin"], key=f"gstin_{client['id']}")
            services = st.multiselect(
                "Services", list(config.REQUIRED_DOCUMENTS), default=client["services"], key=f"services_{client['id']}"
            )
            if st.form_submit_button("Save changes", disabled=not staff_name):
                pipeline.update_client_details(client["id"], name, phone, pan, gstin, services, staff_name)
                st.session_state["flash"] = "Client details saved."
                st.rerun()

    if client["status"] == config.STATUS_READY:
        st.success("Every checklist document is received. A staff member can now approve the onboarding.")
        if st.button("Approve onboarding", type="primary", key=f"onboard_{client['id']}", disabled=not staff_name):
            pipeline.mark_onboarded(client["id"], staff_name)
            st.session_state["flash"] = f"{client['name']} is now onboarded."
            st.rerun()
    elif client["status"] == config.STATUS_ONBOARDED:
        st.success("This client is onboarded.")
    else:
        st.info("Onboarding can be approved once every checklist item shows 'Received'.")


def show_client_details(clients, staff_name):
    if not clients:
        st.info("No clients yet.")
        return

    labels = {client["id"]: f"#{client['id']}  {client['name'] or client['email']}  ({client['status']})" for client in clients}
    client_id = st.selectbox("Choose a client", list(labels), format_func=lambda cid: labels[cid])
    client = database.get_client(client_id)
    documents = database.get_documents(client_id)

    record_column, checklist_column = st.columns(2)
    with record_column:
        st.subheader("Client record")
        pan_text = client["pan"] or "-"
        if client["pan"] and not validators.is_valid_pan(client["pan"]):
            pan_text += "  :red[(invalid format)]"
        st.markdown(
            f"**Name:** {client['name'] or '-'}  \n"
            f"**Email:** {client['email']}  \n"
            f"**Phone:** {client['phone'] or '-'}  \n"
            f"**PAN:** {pan_text}  \n"
            f"**GSTIN:** {client['gstin'] or '-'}  \n"
            f"**Services:** {', '.join(client['services']) or '-'}  \n"
            f"**Status:** {client['status']}"
        )
    with checklist_column:
        st.subheader("Document checklist")
        rows = checklist.checklist_for(client, documents)
        if not rows:
            st.warning("Service not known yet, so there is no checklist. Set the service under 'Edit client details'.")
        for doc_type, state in rows:
            st.markdown(f"- {doc_type}: :{STATE_COLOURS[state]}[**{state}**]")

    flags = database.get_flags(client_id)
    if flags:
        st.subheader("Warnings and notes for staff")
        for flag in flags:
            st.warning(f"{flag['created_at']}  -  {flag['message']}")

    st.subheader("Documents received")
    if not documents:
        st.caption("No documents yet.")
    for document in documents:
        show_document(document, staff_name)

    show_staff_actions(client, documents, staff_name)


def show_approval_queue(drafts, staff_name):
    st.caption("Nothing is sent to a client until a staff member reads the draft and clicks 'Approve and send'.")
    if not staff_name:
        st.warning("Type your name in the sidebar to approve or reject drafts.")

    if "sent" in st.session_state:
        sent = st.session_state.pop("sent")
        st.success(f"Approved and saved to outbox/{sent['file']} ({sent['channel']} to {sent['client']}).")
        st.link_button(f"Open in {sent['channel']} to deliver it", sent["link"])

    if not drafts:
        st.info("No drafts waiting for approval.")
        return

    for draft in drafts:
        client = database.get_client(draft["client_id"])
        version = f"{draft['id']}_{draft['updated_at']}"
        with st.container(border=True):
            st.markdown(f"**{draft['kind']} for {client['name'] or client['email']}**  -  drafted {draft['created_at']}")
            subject = st.text_input("Email subject", draft["subject"], key=f"subject_{version}")
            email_column, whatsapp_column = st.columns(2)
            email_body = email_column.text_area("Email text", draft["email_body"], height=330, key=f"email_{version}")
            whatsapp_body = whatsapp_column.text_area("WhatsApp text", draft["whatsapp_body"], height=330, key=f"wa_{version}")

            channels = ["Email", "WhatsApp"] if validators.is_valid_phone(client["phone"]) else ["Email"]
            channel = st.radio("Send by", channels, horizontal=True, key=f"channel_{version}")
            if len(channels) == 1:
                st.caption("WhatsApp is not available: there is no valid phone number for this client.")

            approve_column, reject_column = st.columns(2)
            if approve_column.button("Approve and send", type="primary", key=f"approve_{version}", disabled=not staff_name):
                try:
                    st.session_state["sent"] = pipeline.approve_and_send(
                        draft["id"], channel, subject, email_body, whatsapp_body, staff_name
                    )
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
            if reject_column.button("Reject draft", key=f"discard_{version}", disabled=not staff_name):
                pipeline.reject_message(draft["id"], staff_name)
                st.session_state["flash"] = "Draft rejected. Nothing was sent."
                st.rerun()


def show_sent_messages():
    sent = database.get_messages(config.MSG_SENT)
    if not sent:
        st.info("Nothing has been sent yet.")
        return
    rows = []
    for message in sent:
        client = database.get_client(message["client_id"])
        rows.append({
            "Client": client["name"],
            "Type": message["kind"],
            "Channel": message["channel"],
            "Subject": message["subject"],
            "Approved by": message["approved_by"],
            "Sent at": message["sent_at"],
            "Saved as": f"outbox/{message['outbox_file']}",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True)

staff_name = show_sidebar()

st.title("Client Onboarding Tracker")
st.caption(f"{config.FIRM_NAME}  -  prototype using dummy data only.")
show_flash_message()

if "log" in st.session_state:
    with st.expander("Inbox processing log", expanded=True):
        st.code("\n".join(st.session_state["log"]), language=None)
if "reminder_log" in st.session_state:
    st.info("\n\n".join(st.session_state.pop("reminder_log")))

all_clients = database.get_all_clients()
waiting_drafts = database.get_messages(config.MSG_WAITING)

tracker_tab, client_tab, approval_tab, sent_tab = st.tabs(
    ["Tracker", "Client details", f"Approval queue ({len(waiting_drafts)})", "Sent messages"]
)
with tracker_tab:
    show_tracker(all_clients)
with client_tab:
    show_client_details(all_clients, staff_name)
with approval_tab:
    show_approval_queue(waiting_drafts, staff_name)
with sent_tab:
    show_sent_messages()
