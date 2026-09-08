from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from io import BytesIO
from django.conf import settings
from twilio.rest import Client
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
import logging
import random
import re
import string
import qrcode # Added for QR codes
from datetime import date as _date
import smtplib
import secrets
import html as html_lib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def get_school_branding():
    """
    Returns a dict with:
    - school_name
    - tagline
    - contact
    - logo_url (must be a local MEDIA_URL path to embed into PDFs)
    """
    defaults = {
        "school_name": "Bitende Junior School",
        "tagline": "Bitende, Uganda",
        "contact": "P.O. Box 123 | +256 701 000 000",
        "logo_url": None,
    }
    try:
        from .models import SystemSetting

        v = (
            SystemSetting.objects.filter(key="school_branding")
            .values_list("value", flat=True)
            .first()
        )
        if isinstance(v, dict):
            return {**defaults, **v}
    except Exception:
        pass
    return defaults


def _resolve_media_path_from_url(url):
    try:
        if not url:
            return None
        u = str(url).strip()
        if not u:
            return None
        media_url = (getattr(settings, "MEDIA_URL", None) or "/media/").rstrip("/") + "/"
        if not u.startswith(media_url):
            return None
        rel = u[len(media_url) :].lstrip("/")
        root = getattr(settings, "MEDIA_ROOT", None)
        if not root:
            return None
        import os

        return os.path.join(str(root), rel.replace("/", os.sep))
    except Exception:
        return None


def _try_draw_logo(canvas_obj, branding, x=72, y=740, size=54):
    try:
        path = _resolve_media_path_from_url((branding or {}).get("logo_url"))
        if not path:
            return False
        canvas_obj.drawImage(path, x, y - size, width=size, height=size, mask="auto")
        return True
    except Exception:
        return False


def get_active_api_credential(service_name):
    """
    Runtime lookup for API credentials. Avoids DB access in settings.py.
    Returns APICredential or None.
    """
    try:
        from .models import APICredential

        return (
            APICredential.objects.filter(service_name=service_name, is_active=True)
            .order_by("-updated_at")
            .first()
        )
    except Exception:
        return None

def generate_random_password(length=12):
    safe_symbols = "@#$%*!?"
    groups = [
        string.ascii_uppercase,
        string.ascii_lowercase,
        string.digits,
        safe_symbols,
    ]
    size = max(int(length or 12), 10)
    password_chars = [secrets.choice(group) for group in groups]
    all_chars = ''.join(groups)
    while len(password_chars) < size:
        password_chars.append(secrets.choice(all_chars))
    random.SystemRandom().shuffle(password_chars)
    return ''.join(password_chars)

def generate_otp(length=6):
    digits = string.digits
    otp = ''.join(random.choice(digits) for i in range(length))
    return otp

def send_email(subject, recipient_list, template_name, context):
    try:
        html_message = render_to_string(template_name, context)
        plain_message = strip_tags(html_message)
        recipient_list = [r for r in (recipient_list or []) if r]
        if not recipient_list:
            logger.warning("send_email called without recipients")
            return False

        smtp_cred = get_active_api_credential('gmail_smtp') or get_active_api_credential('email_smtp')
        if smtp_cred:
            x = smtp_cred.extra_data or {}
            if smtp_cred.service_name == 'gmail_smtp':
                host = 'smtp.gmail.com'
                port = 587
                username = (x.get('username') or '').strip()
                password = (smtp_cred.client_secret or '').strip()
                use_tls = True
            else:
                host = (smtp_cred.client_id or '').strip()
                port = x.get('port') or 587
                username = (x.get('username') or '').strip()
                password = (smtp_cred.client_secret or '').strip()
                use_tls = str(x.get('use_tls') or 'true').strip().lower() not in ('0', 'false', 'no')
            try:
                port = int(port)
            except Exception:
                port = 587

            if host and username and password:
                msg = EmailMessage()
                msg['Subject'] = subject
                msg['From'] = (x.get('from_email') or username or settings.DEFAULT_FROM_EMAIL)
                msg['To'] = ', '.join(recipient_list)
                msg.set_content(plain_message or '')
                if html_message:
                    msg.add_alternative(html_message, subtype='html')

                with smtplib.SMTP(host, port, timeout=15) as server:
                    if use_tls:
                        server.starttls()
                    server.login(username, password)
                    server.send_message(msg)
                logger.info(f"Email sent via active SMTP credential to {recipient_list} with subject: {subject}")
                return True

        from_email = settings.DEFAULT_FROM_EMAIL
        send_mail(subject, plain_message, from_email, recipient_list, html_message=html_message)
        logger.info(f"Email sent to {recipient_list} with subject: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {recipient_list}: {e}")
        return False

def generate_graduation_certificate_pdf(student, academic_year, average_score, class_position):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    # Title
    p.setFont('Helvetica-Bold', 24)
    p.drawCentredString(letter[0] / 2, 750, "Bitende Junior School")
    p.setFont('Helvetica', 18)
    p.drawCentredString(letter[0] / 2, 720, "Graduation Certificate")

    # Student Information
    p.setFont('Helvetica', 12)
    p.drawString(100, 650, f"This certifies that:")
    p.setFont('Helvetica-Bold', 14)
    p.drawString(100, 620, f"{student.first_name} {student.last_name}")

    p.setFont('Helvetica', 12)
    p.drawString(100, 590, f"Student ID: {student.student_id}")
    p.drawString(100, 570, f"Successfully completed Primary Seven ({student.current_class.level})")
    p.drawString(100, 550, f"in the Academic Year {academic_year}")
    p.drawString(100, 530, f"With an average score of {average_score:.2f}% and class position {class_position}")

    # Signatures
    p.line(100, 300, 300, 300)
    p.drawString(100, 280, "Head Teacher")

    p.line(400, 300, 600, 300)
    p.drawString(400, 280, "Date")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def generate_teacher_credential_pdf(teacher, username, password, login_url):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    p.setFont('Helvetica-Bold', 20)
    branding = get_school_branding()
    _try_draw_logo(p, branding, x=72, y=770, size=54)
    p.drawCentredString(letter[0] / 2, 750, f"{branding.get('school_name')} - Teacher Credentials")

    p.setFont('Helvetica', 12)
    p.drawString(100, 700, f"Teacher Name: {teacher.first_name} {teacher.last_name}")
    p.drawString(100, 680, f"Employee ID: {teacher.employee_id}")
    p.drawString(100, 660, f"Username: {username}")
    p.drawString(100, 640, f"Temporary Password: {password}")
    p.drawString(100, 620, f"Login URL: {login_url}")
    p.drawString(100, 580, "Please log in and change your password immediately.")
    p.drawString(100, 560, "Do not share these details with anyone.")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def generate_staff_credential_pdf(staff_name, role, username, password, login_url):
    """
    Generic credentials PDF for non-teaching staff accounts (admin/bursar/reception/DOS/etc).
    Temporary password is included; caller should only generate this when a short-lived handover
    token is present, or when printing immediately after account creation.
    """
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    p.setFont('Helvetica-Bold', 20)
    branding = get_school_branding()
    _try_draw_logo(p, branding, x=72, y=770, size=54)
    title_role = (role or 'Staff').strip().title()
    p.drawCentredString(letter[0] / 2, 750, f"{branding.get('school_name')} - {title_role} Credentials")

    p.setFont('Helvetica', 12)
    p.drawString(100, 700, f"Name: {staff_name or '-'}")
    p.drawString(100, 680, f"Role: {role or '-'}")
    p.drawString(100, 660, f"Username: {username}")
    p.drawString(100, 640, f"Temporary Password: {password}")
    p.drawString(100, 620, f"Login URL: {login_url}")
    p.drawString(100, 580, "Please log in and change your password immediately.")
    p.drawString(100, 560, "Do not share these details with anyone.")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def generate_parent_credential_pdf(parent_name, student_name, student_id, login_url, phone_number, password):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    p.setFont('Helvetica-Bold', 20)
    branding = get_school_branding()
    _try_draw_logo(p, branding, x=72, y=770, size=54)
    p.drawCentredString(letter[0] / 2, 750, f"{branding.get('school_name')} - Parent Portal Credentials")

    p.setFont('Helvetica', 12)
    p.drawString(100, 700, f"Parent Name: {parent_name}")
    p.drawString(100, 680, f"Student Name: {student_name}")
    p.drawString(100, 660, f"Student ID: {student_id}")
    p.drawString(100, 640, f"Login URL: {login_url}")
    p.drawString(100, 620, f"Login Identifier (Phone): {phone_number}")
    p.drawString(100, 600, f"Temporary Password: {password}")
    p.drawString(100, 560, "Please log in and change your password immediately.")
    p.drawString(100, 540, "Do not share these details with anyone.")

    # QR Code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,  # type: ignore[attr-defined]
        box_size=4,
        border=4,
    )
    qr.add_data(login_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save QR code to a BytesIO object
    qr_buffer = BytesIO()
    img.save(qr_buffer, format="PNG")  # type: ignore[call-arg]
    qr_buffer.seek(0)

    # Draw QR code on PDF (position adjusted)
    p.drawImage(qr_buffer, 450, 550, width=100, height=100) # x, y, width, height
    p.drawString(450, 530, "Scan for Login")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


def generate_family_credential_pdf(
    parent_name,
    student_name,
    student_id,
    login_url,
    parent_phone=None,
    parent_email=None,
    parent_password=None,
    student_username=None,
    student_password=None,
):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    branding = get_school_branding()
    _try_draw_logo(p, branding, x=72, y=770, size=54)
    p.setFont('Helvetica-Bold', 20)
    p.drawCentredString(letter[0] / 2, 750, f"{branding.get('school_name')} - Family Portal Credentials")

    y = 708
    line = 18

    def row(label, value, bold=False):
        nonlocal y
        if value in [None, '']:
            return
        p.setFont('Helvetica-Bold' if bold else 'Helvetica-Bold', 11)
        p.drawString(82, y, f"{label}:")
        p.setFont('Helvetica', 11)
        p.drawString(235, y, str(value))
        y -= line

    row("Parent / Guardian", parent_name or 'Parent/Guardian')
    row("Student", student_name)
    row("Student ID", student_id)
    row("Portal login URL", login_url)

    y -= 8
    p.setFont('Helvetica-Bold', 13)
    p.drawString(82, y, "Parent Portal")
    y -= 20
    row("Login phone", parent_phone)
    row("Login email", parent_email)
    row("Temporary password", parent_password)
    if not parent_password:
        row("Password status", "Existing password remains unchanged.")

    y -= 8
    p.setFont('Helvetica-Bold', 13)
    p.drawString(82, y, "Student Portal")
    y -= 20
    row("Login username", student_username)
    row("Temporary password", student_password)
    if student_username and not student_password:
        row("Password status", "Existing password remains unchanged.")

    y -= 8
    p.setFont('Helvetica-Bold', 12)
    p.drawString(82, y, "Important")
    y -= 18
    p.setFont('Helvetica', 10)
    for line_text in [
        "1. Please confirm the child registration details are correct.",
        "2. Login with the phone number or email that was registered.",
        "3. Use 'Forgot password' to reset using the registered email or phone number.",
        "4. Change temporary passwords immediately after first login.",
    ]:
        p.drawString(94, y, line_text)
        y -= 14

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def generate_student_credential_pdf(student_name, student_username, student_password, login_url):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    p.setFont('Helvetica-Bold', 20)
    branding = get_school_branding()
    _try_draw_logo(p, branding, x=72, y=770, size=54)
    p.drawCentredString(letter[0] / 2, 750, f"{branding.get('school_name')} - Student Portal Credentials")

    p.setFont('Helvetica', 12)
    p.drawString(100, 700, f"Student Name: {student_name}")
    p.drawString(100, 680, f"Username: {student_username}")
    p.drawString(100, 660, f"Temporary Password: {student_password}")
    p.drawString(100, 640, f"Login URL: {login_url}")
    p.drawString(100, 600, "Please log in and change your password immediately.")
    p.drawString(100, 580, "Do not share these details with anyone.")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


def generate_payment_receipt_pdf(payment, school_name="Bitende Junior School"):
    """
    Minimal PDF receipt generator for finance/parents.
    """
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    p.setFont('Helvetica-Bold', 20)
    p.drawCentredString(letter[0] / 2, 750, f"{school_name} - Payment Receipt")

    p.setFont('Helvetica', 12)
    y = 705
    line = 18

    def row(label, value):
        nonlocal y
        p.setFont('Helvetica-Bold', 11)
        p.drawString(90, y, f"{label}:")
        p.setFont('Helvetica', 11)
        p.drawString(210, y, str(value) if value is not None else "-")
        y -= line

    stu = getattr(payment, 'student', None)
    row("Receipt Number", getattr(payment, 'receipt_number', None) or "-")
    received_at = getattr(payment, 'received_at', None)
    row("Date", received_at.strftime('%Y-%m-%d %H:%M') if received_at else "-")
    row("Student", f"{getattr(stu, 'first_name', '')} {getattr(stu, 'last_name', '')}".strip() if stu else "-")
    row("Student ID", getattr(stu, 'student_id', None) if stu else "-")
    row("Amount (UGX)", f"UGX {float(payment.amount):,.2f}" if getattr(payment, 'amount', None) is not None else "-")
    row("Method", getattr(payment, 'method', None))
    row("Reference", getattr(payment, 'reference', None))
    row("Status", getattr(payment, 'status', None))
    row("Approved By", getattr(getattr(payment, 'approved_by', None), 'username', None))
    approved_at = getattr(payment, 'approved_at', None)
    row("Approved At", approved_at.strftime('%Y-%m-%d %H:%M') if approved_at else "-")

    # Footer
    p.setFont('Helvetica', 10)
    p.setFillColor(colors.grey)
    p.drawString(90, 80, "This receipt is system-generated.")
    p.setFillColor(colors.black)

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


def generate_deposit_batch_report_pdf(batch, payments, school_name="Bitende Junior School"):
    """
    Deposit batch report PDF for bank reconciliation.

    `payments` can be a queryset or list of Payment objects.
    """
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title="Deposit Batch Report",
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontName = "Helvetica-Bold"
    title_style.fontSize = 18

    normal = styles["Normal"]
    normal.fontSize = 10

    story = []
    story.append(Paragraph(f"{school_name}", title_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Deposit Batch Report", styles["Heading2"]))
    story.append(Spacer(1, 10))

    created_by = getattr(getattr(batch, "created_by", None), "username", None) or "-"
    posted_by = getattr(getattr(batch, "posted_by", None), "username", None) or "-"

    meta_rows = [
        ["Batch", (getattr(batch, "name", None) or f"Batch #{getattr(batch, 'id', '-')}")],
        ["Bank", getattr(batch, "bank_name", None) or "-"],
        ["Deposit Date", getattr(batch, "deposit_date", None).isoformat() if getattr(batch, "deposit_date", None) else "-"],  # type: ignore[attr-defined]
        ["Reference", getattr(batch, "reference", None) or "-"],
        ["Status", "Posted" if getattr(batch, "is_posted", False) else "Open"],
        ["Posted At", getattr(batch, "posted_at", None).strftime("%Y-%m-%d %H:%M") if getattr(batch, "posted_at", None) else "-"],  # type: ignore[attr-defined]
        ["Posted By", posted_by],
        ["Created By", created_by],
        ["Generated At", timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")],
    ]
    meta_tbl = Table(meta_rows, colWidths=[1.25 * inch, 5.25 * inch])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.whitesmoke),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(meta_tbl)
    story.append(Spacer(1, 14))

    pay_list = list(payments or [])
    total = 0
    for p in pay_list:
        try:
            total += float(getattr(p, "amount", 0) or 0)
        except Exception:
            pass

    story.append(Paragraph(f"Payments: <b>{len(pay_list)}</b>  |  Total: <b>UGX {total:,.0f}</b>", normal))
    story.append(Spacer(1, 10))

    rows = [["#", "Receipt", "Date", "Student", "Amount (UGX)", "Reference"]]
    for idx, p in enumerate(pay_list, start=1):
        stu = getattr(p, "student", None)
        stu_label = "-"
        if stu is not None:
            sid = getattr(stu, "student_id", None) or ""
            nm = f"{getattr(stu, 'first_name', '')} {getattr(stu, 'last_name', '')}".strip()
            if sid and nm:
                stu_label = f"{sid} - {nm}"
            elif sid:
                stu_label = sid
            elif nm:
                stu_label = nm
        received_at = getattr(p, "received_at", None)
        rows.append(
            [
                str(idx),
                getattr(p, "receipt_number", None) or "-",
                received_at.strftime("%Y-%m-%d %H:%M") if received_at else "-",
                stu_label,
                f"{float(getattr(p, 'amount', 0) or 0):,.0f}",
                getattr(p, "reference", None) or "-",
            ]
        )

    tbl = Table(
        rows,
        colWidths=[0.35 * inch, 1.05 * inch, 1.15 * inch, 2.55 * inch, 1.05 * inch, 1.25 * inch],
        repeatRows=1,
    )
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                ("ALIGN", (4, 1), (4, -1), "RIGHT"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(tbl)

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_cashbook_close_pdf(cashbook, school_name="Bitende Junior School"):
    """
    Printable close-of-day cashbook reconciliation.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="Close of Day Cashbook",
    )

    styles = getSampleStyleSheet()
    story = [
        Paragraph(school_name, styles["Title"]),
        Spacer(1, 6),
        Paragraph("Bursar Close-of-Day Cashbook", styles["Heading2"]),
        Spacer(1, 10),
    ]

    def money(v):
        try:
            return f"UGX {float(v or 0):,.0f}"
        except Exception:
            return "UGX 0"

    cashier_name = getattr(getattr(cashbook, "cashier", None), "username", None) or "All cashiers"
    closed_by = getattr(getattr(cashbook, "closed_by", None), "username", None) or "-"
    snapshot = cashbook.snapshot or {}

    meta_rows = [
        ["Date", getattr(cashbook, "close_date", None).isoformat() if getattr(cashbook, "close_date", None) else "-"],  # type: ignore[attr-defined]
        ["Cashier", cashier_name],
        ["Closed By", closed_by],
        ["Closed At", timezone.localtime(cashbook.closed_at).strftime("%Y-%m-%d %H:%M") if getattr(cashbook, "closed_at", None) else "-"],
        ["Opening Cash", money(cashbook.opening_cash)],
        ["Cash Received", money(cashbook.cash_received_total)],
        ["Non-Cash Received", money(cashbook.non_cash_received_total)],
        ["Approved Expenses", money(cashbook.approved_expense_total)],
        ["Expected Cash On Hand", money(cashbook.expected_cash_on_hand)],
        ["Counted Cash On Hand", money(cashbook.counted_cash_on_hand)],
        ["Variance", money(cashbook.variance_amount)],
        ["Deposit Batch Total", money(cashbook.deposit_batch_total)],
    ]
    meta_tbl = Table(meta_rows, colWidths=[1.8 * inch, 4.6 * inch])
    meta_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("FONTNAME", (1, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.whitesmoke),
    ]))
    story.extend([meta_tbl, Spacer(1, 12)])

    def section_table(title, headers, rows, col_widths):
        story.append(Paragraph(title, styles["Heading3"]))
        table_rows = [headers] + (rows or [["-", "-", "-"]])
        tbl = Table(table_rows, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.extend([tbl, Spacer(1, 10)])

    method_rows = [
        [str(r.get("method_label") or "-"), str(r.get("count") or 0), money(r.get("total_amount"))]
        for r in (snapshot.get("by_method") or [])
    ]
    cashier_rows = [
        [str(r.get("cashier_name") or "-"), str(r.get("count") or 0), money(r.get("total_amount"))]
        for r in (snapshot.get("by_cashier") or [])
    ]
    batch_rows = [
        [
            str(r.get("batch_name") or "-"),
            str(r.get("payments_count") or 0),
            money(r.get("total_amount")),
            "Posted" if r.get("is_posted") else "Open",
        ]
        for r in (snapshot.get("deposit_batches") or [])
    ]

    section_table("By Method", ["Method", "Count", "Total"], method_rows, [2.6 * inch, 1.1 * inch, 2.1 * inch])
    section_table("By Cashier", ["Cashier", "Count", "Total"], cashier_rows, [2.6 * inch, 1.1 * inch, 2.1 * inch])
    section_table("Deposit Batches", ["Batch", "Count", "Total", "Status"], batch_rows, [2.7 * inch, 0.8 * inch, 1.5 * inch, 1.0 * inch])

    expense_rows = [
        [
            str(r.get("category") or "-"),
            str(r.get("count") or 0),
            money(r.get("total_amount")),
        ]
        for r in (snapshot.get("expenses_by_category") or [])
    ]
    section_table("Approved Expenses", ["Category", "Count", "Total"], expense_rows, [2.6 * inch, 1.1 * inch, 2.1 * inch])

    if getattr(cashbook, "notes", None):
        story.append(Paragraph("Notes", styles["Heading3"]))
        story.append(Paragraph(str(cashbook.notes), styles["BodyText"]))

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_cashier_handover_pdf(summary, school_name="Bitende Junior School"):
    """
    Printable handover summary for the next bursar/cashier.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="Cashier Handover",
    )

    styles = getSampleStyleSheet()
    story = [
        Paragraph(school_name, styles["Title"]),
        Spacer(1, 6),
        Paragraph("Cashier Handover Summary", styles["Heading2"]),
        Spacer(1, 10),
    ]

    def money(v):
        try:
            return f"UGX {float(v or 0):,.0f}"
        except Exception:
            return "UGX 0"

    prior_close = (summary or {}).get("prior_close") or {}
    meta_rows = [
        ["Handover Date", (summary or {}).get("close_date") or "-"],
        ["Cashier Scope", (summary or {}).get("cashier_username") or "School-wide"],
        ["Suggested Opening Cash", money((summary or {}).get("opening_cash_suggestion"))],
        ["Prior Close Date", prior_close.get("close_date") or "-"],
        ["Prior Counted Cash", money(prior_close.get("counted_cash_on_hand"))],
        ["Prior Variance", money(prior_close.get("variance_amount"))],
        ["Pending Deposit Total", money((summary or {}).get("pending_deposit_total"))],
        ["Unresolved Promise Total", money((summary or {}).get("unresolved_promise_total"))],
        ["Overdue Promises", str((summary or {}).get("overdue_promise_count") or 0)],
    ]
    meta_tbl = Table(meta_rows, colWidths=[2.0 * inch, 4.4 * inch])
    meta_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("FONTNAME", (1, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.whitesmoke),
    ]))
    story.extend([meta_tbl, Spacer(1, 12)])

    def section_table(title, headers, rows, col_widths):
        story.append(Paragraph(title, styles["Heading3"]))
        table_rows = [headers] + (rows or [["-", "-", "-"]])
        tbl = Table(table_rows, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.extend([tbl, Spacer(1, 10)])

    deposit_rows = [
        [
            str(r.get("batch_name") or "-"),
            str(r.get("deposit_date") or "-"),
            str(r.get("payments_count") or 0),
            money(r.get("total_amount")),
            "Posted" if r.get("is_posted") else "Pending",
        ]
        for r in ((summary or {}).get("pending_deposits") or [])
    ]
    section_table(
        "Pending Bank Deposits",
        ["Batch", "Date", "Count", "Total", "Status"],
        deposit_rows,
        [2.2 * inch, 1.0 * inch, 0.7 * inch, 1.2 * inch, 1.0 * inch],
    )

    promise_rows = [
        [
            str(r.get("student_name") or "-"),
            str(r.get("promised_for") or "-"),
            str(r.get("status") or "-"),
            money(r.get("amount")),
            str(r.get("installment_label") or r.get("notes") or "-"),
        ]
        for r in ((summary or {}).get("unresolved_promises") or [])
    ]
    section_table(
        "Unresolved Fee Promises",
        ["Student", "Due", "Status", "Amount", "Notes"],
        promise_rows,
        [2.0 * inch, 0.9 * inch, 0.9 * inch, 1.0 * inch, 1.8 * inch],
    )

    prior_notes = prior_close.get("notes")
    if prior_notes:
        story.append(Paragraph("Prior Close Notes", styles["Heading3"]))
        story.append(Paragraph(str(prior_notes), styles["BodyText"]))

    doc.build(story)
    buffer.seek(0)
    return buffer


def generate_fee_statement_pdf(student, academic_year, terms, school_name="Bitende Junior School"):
    """
    Simple per-student fee statement PDF for an academic year.

    `terms` is a list of dicts with keys:
      term_number, opening_balance, term_due, adjustments_total, paid_in_term, paid_applied,
      balance_due, closing_balance
    """
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    p.setFont('Helvetica-Bold', 18)
    p.drawCentredString(letter[0] / 2, 760, school_name)
    p.setFont('Helvetica-Bold', 14)
    p.drawCentredString(letter[0] / 2, 738, f"Fee Statement - Academic Year {academic_year}")

    p.setFont('Helvetica', 11)
    y = 705
    line = 16

    def row(label, value):
        nonlocal y
        p.setFont('Helvetica-Bold', 10)
        p.drawString(72, y, f"{label}:")
        p.setFont('Helvetica', 10)
        p.drawString(200, y, str(value) if value is not None else "-")
        y -= line

    row("Student", f"{getattr(student, 'first_name', '')} {getattr(student, 'last_name', '')}".strip())
    row("Student ID", getattr(student, 'student_id', None))
    cls = getattr(getattr(student, 'current_class', None), 'level', '') or ''
    sec = (getattr(student, 'section', '') or '').strip()
    row("Class", f"{cls}{sec}")
    y -= 8

    # Table header
    p.setFont('Helvetica-Bold', 10)
    p.drawString(72, y, "Term")
    p.drawString(120, y, "Opening")
    p.drawString(190, y, "Term Due")
    p.drawString(260, y, "Adjust.")
    p.drawString(320, y, "Paid")
    p.drawString(380, y, "Balance")
    p.drawString(455, y, "Closing")
    y -= 10
    p.setStrokeColor(colors.lightgrey)
    p.line(72, y, 540, y)
    y -= 14

    p.setFont('Helvetica', 10)
    for t in (terms or []):
        if y < 140:
            p.showPage()
            p.setFont('Helvetica-Bold', 12)
            p.drawCentredString(letter[0] / 2, 760, f"Fee Statement - Academic Year {academic_year} (cont.)")
            p.setFont('Helvetica', 10)
            y = 720
        tm = t.get('term_number')
        p.drawString(72, y, f"T{tm}")
        p.drawRightString(175, y, str(t.get('opening_balance', '0')))
        p.drawRightString(245, y, str(t.get('term_due', '0')))
        p.drawRightString(305, y, str(t.get('adjustments_total', '0')))
        p.drawRightString(365, y, str(t.get('paid_applied', t.get('paid_in_term', '0'))))
        p.drawRightString(440, y, str(t.get('balance_due', '0')))
        p.drawRightString(535, y, str(t.get('closing_balance', '0')))
        y -= line

    y -= 8
    p.setFont('Helvetica-Oblique', 9)
    p.setFillColor(colors.grey)
    p.drawString(72, y, "Notes: Opening/Closing are carry-forward balances (credit positive, arrears negative).")
    y -= 12
    p.drawString(72, y, "This statement is system-generated.")
    p.setFillColor(colors.black)

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def _safe_format_template(template_text, mapping):
    # Minimal safe formatter for "{key}" placeholders; missing keys become empty strings.
    class _SafeDict(dict):
        def __missing__(self, key):
            return ''
    try:
        return str(template_text).format_map(_SafeDict(mapping or {}))
    except Exception:
        return str(template_text)


_ALLOWED_RICH_TEXT_TAGS = {
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'ul', 'ol', 'li',
    'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead',
    'tbody', 'tfoot', 'tr', 'th', 'td', 'div', 'span', 'a', 'hr', 'sub', 'sup',
}
_ALIGNABLE_RICH_TEXT_TAGS = {
    'p', 'div', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th',
}


def _extract_allowed_style_attrs(raw_attrs):
    attrs = str(raw_attrs or '')
    style_match = re.search(r'style\s*=\s*([\'"])(.*?)\1', attrs, flags=re.IGNORECASE | re.DOTALL)
    if not style_match:
        return ''
    style_value = style_match.group(2) or ''
    align_match = re.search(r'text-align\s*:\s*(left|center|right|justify)', style_value, flags=re.IGNORECASE)
    if not align_match:
        return ''
    return f' style="text-align:{align_match.group(1).lower()}"'


def _extract_anchor_attrs(raw_attrs):
    attrs = str(raw_attrs or '')
    href_match = re.search(r'href\s*=\s*([\'"])(.*?)\1', attrs, flags=re.IGNORECASE | re.DOTALL)
    if not href_match:
        return ''
    href = (href_match.group(2) or '').strip()
    if not href or href.lower().startswith(('javascript:', 'data:')):
        return ''
    safe_href = html_lib.escape(href, quote=True)
    return f' href="{safe_href}" target="_blank" rel="noopener noreferrer"'


def _extract_table_cell_attrs(raw_attrs):
    attrs = str(raw_attrs or '')
    out = []
    for key in ('colspan', 'rowspan'):
        match = re.search(rf'{key}\s*=\s*([\'"]?)(\d+)\1', attrs, flags=re.IGNORECASE)
        if match:
            out.append(f'{key}="{int(match.group(2))}"')
    return (' ' + ' '.join(out)) if out else ''


def sanitize_rich_text_html(value):
    raw = str(value or '')
    if not raw.strip():
        return ''
    cleaned = raw.replace('\r\n', '\n')
    cleaned = re.sub(r'<!--.*?-->', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', '', cleaned)
    cleaned = re.sub(r'(?i)\son[a-z0-9_-]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', cleaned)

    def _tag_replacer(match):
        slash = match.group(1) or ''
        tag = (match.group(2) or '').lower()
        raw_attrs = match.group(3) or ''
        if tag not in _ALLOWED_RICH_TEXT_TAGS:
            return ''
        if slash:
            return f'</{tag}>'
        attrs = ''
        if tag in _ALIGNABLE_RICH_TEXT_TAGS:
            attrs += _extract_allowed_style_attrs(raw_attrs)
        if tag == 'a':
            attrs += _extract_anchor_attrs(raw_attrs)
        if tag in {'td', 'th'}:
            attrs += _extract_table_cell_attrs(raw_attrs)
        return f'<{tag}{attrs}>'

    cleaned = re.sub(r'<\s*(/?)\s*([a-zA-Z0-9]+)([^>]*)>', _tag_replacer, cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def rich_text_to_plain_text(value):
    html = sanitize_rich_text_html(value)
    if not html:
        return ''
    text = re.sub(r'(?i)<br\s*/?>', '\n', html)
    text = re.sub(r'(?i)<hr\s*/?>', '\n--------------------\n', text)
    text = re.sub(r'(?i)<li[^>]*>', '- ', text)
    text = re.sub(r'(?i)</(p|div|blockquote|h1|h2|h3|h4|h5|h6|ul|ol|li|table|thead|tbody|tfoot|tr)>', '\n', text)
    text = re.sub(r'(?i)</(td|th)>', '\t', text)
    text = strip_tags(text)
    text = html_lib.unescape(text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def _wrap_lines_for_pdf(text, max_chars=110):
    # Rough wrap fallback (avoids dependence on canvas stringWidth for now).
    # Keeps paragraphs split by blank lines.
    out = []
    for para in str(text or '').splitlines():
        if not para.strip():
            out.append('')
            continue
        words = para.split()
        line = ''
        for w in words:
            if not line:
                line = w
                continue
            if len(line) + 1 + len(w) <= max_chars:
                line += ' ' + w
            else:
                out.append(line)
                line = w
        if line:
            out.append(line)
    return out

def generate_admission_letter_pdf(student, login_url, parent_username=None, parent_password=None, student_username=None, student_password=None, template_text=None):
    """
    Simple admission letter + optional credentials section (only when provided by caller).
    Passwords are never stored; pass them only when freshly generated.
    """
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    branding = get_school_branding()
    school_name = str(branding.get("school_name") or "Bitende Junior School")
    title = "Admission Letter" 
    p.setFont('Helvetica-Bold', 18) 
    _try_draw_logo(p, branding, x=72, y=780, size=54)
    p.drawCentredString(letter[0] / 2, 760, school_name) 
    p.setFont('Helvetica-Bold', 14)
    p.drawCentredString(letter[0] / 2, 736, title)

    p.setFont('Helvetica', 11)
    y = 700
    today = _date.today().isoformat()
    p.drawString(72, y, f"Date: {today}")
    y -= 26
    p.drawString(72, y, f"Student Name: {student.first_name} {student.last_name}")
    y -= 16
    p.drawString(72, y, f"Student ID: {student.student_id}")
    y -= 16
    cls = getattr(getattr(student, 'current_class', None), 'level', '') or ''
    sec = (student.section or '')
    p.drawString(72, y, f"Class: {cls}{sec}")
    y -= 16
    if getattr(student, 'enrollment_date', None):
        p.drawString(72, y, f"Enrollment Date: {student.enrollment_date}")
        y -= 16
    if getattr(student, 'parent_name', None):
        p.drawString(72, y, f"Parent/Guardian: {student.parent_name} ({student.parent_relationship or ''})")
        y -= 16
    if getattr(student, 'parent_phone', None):
        p.drawString(72, y, f"Parent Phone: {student.parent_phone}")
        y -= 16

    y -= 10
    if template_text:
        mapping = {
            'school_name': school_name,
            'today': today,
            'student_name': f"{student.first_name} {student.last_name}",
            'student_id': student.student_id,
            'class_label': f"{cls}{sec}",
            'enrollment_date': str(getattr(student, 'enrollment_date', '') or ''),
            'parent_name': str(getattr(student, 'parent_name', '') or ''),
            'parent_relationship': str(getattr(student, 'parent_relationship', '') or ''),
            'parent_phone': str(getattr(student, 'parent_phone', '') or ''),
            'login_url': str(login_url or ''),
        }
        rendered = _safe_format_template(template_text, mapping)
        lines = _wrap_lines_for_pdf(rendered, max_chars=110)
    else:
        lines = [
            "Dear Parent/Guardian,",
            "",
            "We are pleased to inform you that your child has been admitted to Bitende Junior School.",
            "Please report with the required materials and complete the registration process at the school office.",
            "",
            "School Portal Access:",
            f"Login URL: {login_url}",
        ]
    for line in lines:
        p.drawString(72, y, line)
        y -= 14
        if y < 200:
            p.showPage()
            y = 740

    if parent_username or student_username:
        y -= 10
        p.setFont('Helvetica-Bold', 12)
        p.drawString(72, y, "Temporary Credentials (change password after login):")
        y -= 18
        p.setFont('Helvetica', 11)
        if parent_username:
            p.drawString(72, y, f"Parent Username: {parent_username}")
            y -= 14
            if parent_password:
                p.drawString(72, y, f"Parent Temporary Password: {parent_password}")
                y -= 14
        if student_username:
            p.drawString(72, y, f"Student Username: {student_username}")
            y -= 14
            if student_password:
                p.drawString(72, y, f"Student Temporary Password: {student_password}")
                y -= 14

    y -= 18
    p.setFont('Helvetica-Oblique', 10)
    p.drawString(72, y, "Note: Passwords are not stored in plain text. If you lose them, contact the school to reset.")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


def generate_mail_merge_letter_pdf(documents, bundle_title="Letters"):
    """
    Render one or more personalized branded letters into a single printable PDF bundle.
    Each item in documents should be a dict with title/body/recipient/meta fields.
    """
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    branding = get_school_branding()
    school_name = str(branding.get("school_name") or "Bitende Junior School")
    tagline = str(branding.get("tagline") or "")
    contact = str(branding.get("contact") or "")

    docs = list(documents or [])
    if not docs:
        docs = [{"title": bundle_title, "body": "No personalized letters were generated.", "recipient_name": ""}]

    for index, item in enumerate(docs):
        if index:
            p.showPage()
        _try_draw_logo(p, branding, x=72, y=780, size=54)
        p.setFont('Helvetica-Bold', 18)
        p.drawCentredString(letter[0] / 2, 765, school_name)
        p.setFont('Helvetica', 10)
        if tagline:
            p.drawCentredString(letter[0] / 2, 748, tagline)
        if contact:
            p.drawCentredString(letter[0] / 2, 734, contact)

        title = str(item.get('title') or bundle_title or 'Letter')
        recipient_name = str(item.get('recipient_name') or '').strip()
        recipient_contact = str(item.get('recipient_contact') or '').strip()
        student_name = str(item.get('student_name') or '').strip()
        student_id = str(item.get('student_id') or '').strip()
        class_label = str(item.get('class_label') or '').strip()
        body_html = sanitize_rich_text_html(item.get('body_html') or item.get('body') or '')
        body = rich_text_to_plain_text(body_html or item.get('body') or '')
        issued_on = str(item.get('date_label') or _date.today().isoformat())

        p.setFont('Helvetica-Bold', 14)
        p.drawCentredString(letter[0] / 2, 700, title)

        y = 668
        p.setFont('Helvetica', 11)
        if recipient_name:
            p.drawString(72, y, f"To: {recipient_name}")
            y -= 16
        if recipient_contact:
            p.drawString(72, y, f"Contact: {recipient_contact}")
            y -= 16
        p.drawString(72, y, f"Date: {issued_on}")
        y -= 16
        if student_name:
            p.drawString(72, y, f"Student: {student_name}")
            y -= 16
        if student_id:
            p.drawString(72, y, f"Student ID: {student_id}")
            y -= 16
        if class_label:
            p.drawString(72, y, f"Class: {class_label}")
            y -= 16

        y -= 10
        for line_text in _wrap_lines_for_pdf(body, max_chars=108):
            if y < 88:
                p.showPage()
                _try_draw_logo(p, branding, x=72, y=780, size=48)
                y = 730
                p.setFont('Helvetica', 11)
            p.drawString(72, y, line_text)
            y -= 14

        y -= 10
        p.setFont('Helvetica', 11)
        p.drawString(72, max(y, 72), f"Issued by {school_name}")

    p.save()
    buffer.seek(0)
    return buffer

def generate_report_card_pdf(
    *,
    student,
    academic_term,
    marks_rows=None,
    marks_data=None,
    overall_average=0.0,
    overall_grade=None,
    aggregate_points=None,
    class_position=0,
    attendance_percentage=0.0,
    grading_scale_data=None,
    branding=None,
):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Backward/forward compatibility: prefer marks_rows when provided.
    if marks_data is None:
        marks_data = marks_rows or []
    if grading_scale_data is None:
        grading_scale_data = []

    # Custom style for center alignment and spacing
    center_style = ParagraphStyle(name='Center', alignment=1, spaceAfter=6)
    left_style = ParagraphStyle(name='Left', alignment=0, spaceAfter=6)

    b = get_school_branding()
    if isinstance(branding, dict):
        b = {**b, **branding}

    # School Header
    story.append(Paragraph(f"<b>{str(b.get('school_name') or 'BITENDE JUNIOR SCHOOL').upper()}</b>", styles['h1']))
    story.append(Paragraph(" | ".join([x for x in [b.get('tagline'), b.get('contact')] if x]), center_style))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(f"<b>STUDENT PROGRESS REPORT - Term {academic_term.term_number}, Academic Year {academic_term.academic_year}</b>", center_style))
    story.append(Spacer(1, 0.2 * inch))

    # Student Details
    story.append(Paragraph(f"<b>Student Name:</b> {student.first_name} {student.last_name}", left_style))
    story.append(Paragraph(f"<b>Student ID:</b> {student.student_id}", left_style))
    story.append(Paragraph(f"<b>Class:</b> {student.current_class.level} {student.section}", left_style))
    
    # Assuming teacher_a is the class teacher. You might need to refine this based on your actual assignment logic.
    class_teacher_name = student.current_class.teacher_a if student.current_class and student.current_class.teacher_a else "N/A"
    story.append(Paragraph(f"<b>Class Teacher:</b> {class_teacher_name}", left_style))
    story.append(Spacer(1, 0.2 * inch))

    # Marks Table
    has_points = any((m or {}).get('points', None) is not None for m in (marks_data or []))
    if has_points:
        data = [['Subject', 'Max', 'Score', '%', 'Grade', 'Pts', 'Remarks']]
    else:
        data = [['Subject', 'Max', 'Score', '%', 'Grade', 'Remarks']]

    for mark in (marks_data or []):
        try:
            score = float(mark.get('score', 0) or 0)
        except Exception:
            score = 0.0
        percentage = float(mark.get('percentage', score) or 0)

        # Use precomputed grade when present (marks_rows), else compute from grading scale.
        grade = mark.get('grade', None) or "N/A"
        if grade == "N/A":
            for gs in grading_scale_data:
                if float(gs.get('min_score', 0)) <= percentage <= float(gs.get('max_score', 0)):
                    grade = gs.get('grade', grade)
                    break

        remarks = mark.get('remarks') if mark.get('remarks') else "-"
        if has_points:
            pts = mark.get('points', None)
            pts_s = "-" if pts is None else str(pts)
            data.append([
                mark.get('subject', ''),
                "100",
                f"{score:.0f}",
                f"{percentage:.1f}%",
                grade,
                pts_s,
                remarks,
            ])
        else:
            data.append([
                mark.get('subject', ''),
                "100",
                f"{score:.0f}",
                f"{percentage:.1f}%",
                grade,
                remarks,
            ])

    if has_points:
        table = Table(data, colWidths=[1.35*inch, 0.55*inch, 0.65*inch, 0.6*inch, 0.6*inch, 0.45*inch, 2.35*inch])
    else:
        table = Table(data, colWidths=[1.6*inch, 0.65*inch, 0.8*inch, 0.75*inch, 0.65*inch, 2.55*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D3D3D3')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.2 * inch))

    # Performance Summary
    story.append(Paragraph(f"<b>Overall Average:</b> {overall_average:.2f}%", left_style))
    if overall_grade:
        story.append(Paragraph(f"<b>Overall Grade:</b> {overall_grade}", left_style))
    if aggregate_points is not None:
        story.append(Paragraph(f"<b>Aggregate Points:</b> {aggregate_points}", left_style))
    story.append(Paragraph(f"<b>Class Position:</b> {class_position}", left_style))
    story.append(Paragraph(f"<b>Attendance:</b> {attendance_percentage:.2f}%", left_style))
    story.append(Paragraph(f"<b>Conduct Grade:</b> {student.get_conduct_grade_display()}", left_style))
    story.append(Spacer(1, 0.2 * inch))

    # Remarks
    story.append(Paragraph("<b>Class Teacher Remarks:</b>", left_style))
    story.append(Paragraph(student.promotion_notes if student.promotion_notes else "No remarks.", left_style))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("<b>Head Teacher Remarks:</b>", left_style))
    story.append(Paragraph(student.head_teacher_remarks if student.head_teacher_remarks else "No remarks.", left_style))
    story.append(Spacer(1, 0.5 * inch))

    # Signatures
    story.append(Paragraph("__________________________", left_style))
    story.append(Paragraph(f"Class Teacher: {class_teacher_name}", left_style))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("__________________________", left_style))
    story.append(Paragraph("Head Teacher Signature", left_style))
    story.append(Spacer(1, 0.2 * inch))

    doc.build(story)
    buffer.seek(0)
    return buffer

def send_sms(to_number, message):
    try:
        # Prefer local DB-configured gateways. Order: MegaSMS -> Twilio.
        meg = get_active_api_credential("megasms")
        if meg:
            try:
                import requests

                x = meg.extra_data or {}
                url = (x.get("url") or "").strip()
                sender = (x.get("sender") or "").strip()
                api_key = (meg.api_key or "").strip()
                if url and sender and api_key:
                    # Default: form-encoded; some providers accept JSON too.
                    fmt = (x.get("payload_format") or "form").strip().lower()
                    payload = {
                        "api_key": api_key,
                        "to": to_number,
                        "message": message,
                        "sender": sender,
                    }
                    if fmt == "json":
                        r = requests.post(url, json=payload, timeout=8)
                    else:
                        r = requests.post(url, data=payload, timeout=8)
                    if 200 <= int(getattr(r, "status_code", 0) or 0) < 300:
                        logger.info(f"MegaSMS sent to {to_number}: {r.status_code}")
                        return True
                    logger.warning(f"MegaSMS failed to {to_number}: {getattr(r, 'status_code', None)} {getattr(r, 'text', '')[:120]}")
            except Exception as e:
                logger.error(f"Failed to send SMS via MegaSMS to {to_number}: {e}")

        cred = get_active_api_credential("twilio_sms")
        account_sid = (cred.client_id if cred and cred.client_id else None) or settings.TWILIO_ACCOUNT_SID
        auth_token = (cred.client_secret if cred and cred.client_secret else None) or settings.TWILIO_AUTH_TOKEN
        twilio_phone_number = (cred.extra_data.get("from_number") if cred and cred.extra_data else None) or settings.TWILIO_PHONE_NUMBER

        client = Client(account_sid, auth_token)
        msg = client.messages.create(
            to=to_number,
            from_=twilio_phone_number,
            body=message
        )
        logger.info(f"SMS sent to {to_number}: {msg.sid}")
        return True
    except Exception as e:
        logger.error(f"Failed to send SMS to {to_number}: {e}")
        return False


def generate_teacher_appointment_letter_pdf(teacher, username, password, login_url, base_salary=None, employment_type=None):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    branding = get_school_branding()
    school_name = branding.get('school_name') or "Bitende Junior School"

    _try_draw_logo(p, branding, x=54, y=height - 80, size=50)
    p.setFont('Helvetica-Bold', 18)
    p.setFillColorRGB(0.48, 0, 0)
    p.drawString(115, height - 50, school_name)
    p.setFont('Helvetica', 10)
    p.setFillColorRGB(0.3, 0.3, 0.3)
    p.drawString(115, height - 65, f"{branding.get('address') or 'Kampala, Uganda'} | Phone: {branding.get('phone') or '+256 701 234567'}")
    p.drawString(115, height - 78, f"Motto: {branding.get('motto') or 'Strive for Excellence'}")

    p.setStrokeColorRGB(0.8, 0.8, 0.8)
    p.setLineWidth(1)
    p.line(54, height - 92, width - 54, height - 92)

    p.setFont('Helvetica-Bold', 14)
    p.setFillColorRGB(0.1, 0.1, 0.1)
    p.drawCentredString(width / 2, height - 120, "OFFICIAL APPOINTMENT & INTAKE WELCOME LETTER")

    p.setFont('Helvetica', 11)
    today_str = date.today().strftime('%d %B %Y')
    p.drawString(54, height - 145, f"Date: {today_str}")
    p.drawString(54, height - 165, f"Dear {teacher.first_name} {teacher.last_name},")
    p.drawString(54, height - 185, f"We are pleased to welcome you to the academic staff team at {school_name}. Below are your official")
    p.drawString(54, height - 200, "employment details, assigned credentials, and system access information.")

    p.setFillColorRGB(0.97, 0.97, 0.98)
    p.rect(54, height - 310, width - 108, 95, fill=1, stroke=1)
    p.setFillColorRGB(0, 0, 0)
    p.setFont('Helvetica-Bold', 11)
    p.drawString(68, height - 230, "1. STAFF PROFILE & APPOINTMENT DETAILS")
    p.setFont('Helvetica', 10)
    p.drawString(68, height - 250, f"Full Name: {teacher.first_name} {teacher.last_name}")
    p.drawString(300, height - 250, f"Employee ID: {teacher.employee_id or 'N/A'}")
    p.drawString(68, height - 270, f"Phone: {teacher.phone or 'N/A'}")
    p.drawString(300, height - 270, f"Email: {teacher.email or 'N/A'}")
    emp_type = employment_type or getattr(teacher, 'employment_type', 'Permanent')
    salary_str = f"UGX {float(base_salary):,.2f}" if base_salary is not None else "As per Contract"
    p.drawString(68, height - 295, f"Employment Type: {emp_type}")
    p.drawString(300, height - 295, f"Base Salary: {salary_str}")

    p.setFillColorRGB(0.96, 0.93, 0.93)
    p.rect(54, height - 425, width - 108, 95, fill=1, stroke=1)
    p.setFillColorRGB(0, 0, 0)
    p.setFont('Helvetica-Bold', 11)
    p.drawString(68, height - 345, "2. SECURE SYSTEM PORTAL CREDENTIALS")
    p.setFont('Helvetica', 10)
    p.drawString(68, height - 365, f"Portal URL: {login_url}")
    p.drawString(68, height - 385, f"Username: {username}")
    p.drawString(300, height - 385, f"Temporary Password: {password}")
    p.setFont('Helvetica-Oblique', 9)
    p.setFillColorRGB(0.6, 0, 0)
    p.drawString(68, height - 410, "* SECURITY REMINDER: Log in immediately and update your temporary password on your first session.")

    p.setFillColorRGB(0, 0, 0)
    p.setFont('Helvetica-Bold', 11)
    p.drawString(54, height - 450, "3. PORTAL TERMS OF USE & CODE OF CONDUCT")
    p.setFont('Helvetica', 9)
    p.drawString(54, height - 470, "By signing below, you agree to maintain strictly confidential access to student records, grades, and fee data.")
    p.drawString(54, height - 485, "Unauthorized sharing of portal credentials or tampering with assessment marks is strictly prohibited.")

    p.line(54, height - 560, 250, height - 560)
    p.drawString(54, height - 575, "Principal / Head Teacher Signature")
    p.drawString(54, height - 590, "Date: ________________________")

    p.line(320, height - 560, 520, height - 560)
    p.drawString(320, height - 575, "Teacher Signature & Acceptance")
    p.drawString(320, height - 590, "Date: ________________________")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer
