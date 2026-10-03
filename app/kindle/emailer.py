"""Send an EPUB to the Kindle 'Send to Kindle' address via Gmail SMTP.

Reuses the Gmail credentials already configured for notifications. The
sending Gmail address must be listed on Amazon's
"Approved Personal Document E-mail List" for the Kindle account, otherwise
Amazon silently drops the attachment.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# Gmail's implicit-SSL port (465) is blocked on the VPS network, while the
# STARTTLS submission port (587) works over IPv4. Keep this in sync with that
# constraint; see AGENTS.md §6.12 / §8.
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_kindle_epub(subject: str, epub_path: str | Path, recipient: str | None = None) -> bool:
    """Email one EPUB attachment. Returns True when sent successfully."""
    epub_path = Path(epub_path)
    recipient = recipient or settings.kindle_email

    if not all([settings.gmail_user, settings.gmail_app_password, recipient]):
        logger.warning(
            "Kindle email not configured (gmail_user / gmail_app_password / "
            "kindle_email missing) — skipping send"
        )
        return False

    if not epub_path.exists():
        logger.error(f"Kindle EPUB missing, cannot send: {epub_path}")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.gmail_user
        msg["To"] = recipient
        msg.set_content(
            f"{subject}\n\nThis digest is attached as an EPUB for reading on Kindle."
        )
        msg.add_attachment(
            epub_path.read_bytes(),
            maintype="application",
            subtype="epub+zip",
            filename=epub_path.name,
        )

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(settings.gmail_user, settings.gmail_app_password)
            server.send_message(msg)

        logger.info(f"Kindle EPUB sent to {recipient}: {subject}")
        return True

    except Exception as e:
        logger.error(f"Failed to send Kindle EPUB '{subject}': {e}")
        return False
