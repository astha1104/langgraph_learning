import os
import smtplib
from email.message import EmailMessage


def send_email(recipient_email: str, subject: str, body: str) -> str:
    sender_email = os.getenv("SMTP_EMAIL")
    password = os.getenv("SMTP_PASSWORD")
    if not sender_email or not password:
        raise RuntimeError("Set SMTP_EMAIL and SMTP_PASSWORD before sending email.")

    message = EmailMessage()
    message["From"] = sender_email
    message["To"] = recipient_email
    message["Subject"] = subject
    message.set_content(body)

    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()  # Upgrade connection to secure TLS
        server.login(sender_email, password)
        server.send_message(message)

    return "Email sent successfully!"
