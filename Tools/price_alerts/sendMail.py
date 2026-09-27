import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

# Load credentials from .env
load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER", "").replace(" ", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")


def send_email(
    recipient: str,
    subject: str,
    body: str,
    attachment: Path | None = None,
):
    if not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD is not configured.")

    message = EmailMessage()
    message["From"] = f"Price Finder <{GMAIL_USER}>"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    if attachment:
        content_type, _ = mimetypes.guess_type(attachment.name)
        main_type, sub_type = (
            content_type or "application/octet-stream"
        ).split("/")

        message.add_attachment(
            attachment.read_bytes(),
            maintype=main_type,
            subtype=sub_type,
            filename=attachment.name,
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(message)