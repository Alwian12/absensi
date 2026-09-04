"""Email service — silently skips when SMTP not configured."""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings


def _send(to: str | list[str], subject: str, html: str) -> bool:
    if not settings.smtp_enabled or not settings.smtp_host:
        return False
    recipients = [to] if isinstance(to, str) else to
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from or settings.smtp_username
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(msg["From"], recipients, msg.as_string())
        return True
    except Exception:
        return False


def send_absence_alert(pembimbing_email: str, peserta_name: str, date_str: str) -> bool:
    html = f"""
    <h2>Peserta Belum Absen</h2>
    <p><strong>{peserta_name}</strong> belum melakukan absensi pada <strong>{date_str}</strong>.</p>
    <p><a href="{settings.app_base_url}/attendance">Buka halaman absensi</a></p>
    """
    return _send(pembimbing_email, f"[PKL] {peserta_name} belum absen — {date_str}", html)


def send_weekly_report(recipient_email: str, report_html: str, week_label: str) -> bool:
    return _send(recipient_email, f"[PKL] Rekap Mingguan — {week_label}", report_html)


def send_leave_notification(recipient_email: str, peserta_name: str, action: str, keterangan: str) -> bool:
    html = f"""
    <h2>Permohonan Izin PKL</h2>
    <p>Peserta <strong>{peserta_name}</strong> mengajukan permohonan izin.</p>
    <p><strong>Keterangan:</strong> {keterangan}</p>
    <p><strong>Status:</strong> {action}</p>
    <p><a href="{settings.app_base_url}/leave">Buka halaman izin</a></p>
    """
    return _send(recipient_email, f"[PKL] Permohonan Izin — {peserta_name}", html)
