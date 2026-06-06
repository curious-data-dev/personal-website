"""Optional email notification via Gmail SMTP.

Ported from the original aggregator.py. Kept for those who want
email as a backup notification channel alongside the web UI.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def send_daily_email(subject: str, body_html: str) -> bool:
    """Send a daily digest email via Gmail SMTP.

    Args:
        subject: Email subject line.
        body_html: HTML body content.

    Returns:
        True if sent successfully, False otherwise.
    """
    if not all([settings.gmail_user, settings.gmail_app_password, settings.recipient_email]):
        logger.warning("Email not configured — skipping send")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.gmail_user
        msg["To"] = settings.recipient_email

        # Plain-text fallback (strip HTML tags)
        import re
        plain = re.sub(r"<[^>]+>", "", body_html)
        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.gmail_user, settings.gmail_app_password)
            server.send_message(msg)

        logger.info(f"Email sent to {settings.recipient_email}: {subject}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False
