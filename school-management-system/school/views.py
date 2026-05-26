# pyright: reportAttributeAccessIssue=false, reportIncompatibleMethodOverride=false, reportArgumentType=false, reportOptionalMemberAccess=false, reportCallIssue=false
from typing import Any, Dict, Optional, cast

from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from django.contrib.auth import authenticate, login, logout
from django.db.models import F, Avg, Q, Count, Sum, Max # Added for aggregation
from django.db import transaction, IntegrityError # Added for atomic operations and DB error handling
from datetime import date, timedelta, datetime # Added for date and time operations
from django.utils import timezone # Added for timezone awareness

from .models import ( 
    SchoolClass, Subject, ClassSubject, DocumentDraft, Teacher, Student, FeeStructure, Mark, Attendance, Timetable, UserProfile, 
    AcademicTerm, PromotionAudit, AlumniRegister, OTP, IDCounter, GradingScale, UserSession, SecurityAuditLog, 
    APICredential, APICredentialHealthLog, Payment, Invoice, ClassCharge, Event, SystemSetting, TeacherAttendance, TeacherAttendanceQRToken, 
    Notification, Announcement, ExamPaper, InvoiceAdjustment, StudentGuardianLink, PrintQueueItem,
    DepositBatch, ExpenseCategory, Expense, CashbookClose, InstallmentPlan, InstallmentPlanItem,
    FeePromise, FeeReminderLog, ResultsHoldLog, CommunicationCampaign, CommunicationDelivery,  # Added new models
    ExamType, AcademicCalendarEvent, TermInstallmentPlan, StudentDebtRecord, TeacherSalary, TeacherAllowance,
    OtherStaff, StaffPayroll
) 
from .serializers import ( 
    SchoolClassSerializer, SubjectSerializer, ClassSubjectSerializer, DocumentDraftSerializer, TeacherSerializer, StudentSerializer, 
    FeeStructureSerializer, MarkSerializer, AttendanceSerializer, 
    TimetableSerializer, UserSerializer, AcademicTermSerializer, 
    PromotionAuditSerializer, AlumniRegisterSerializer, OTPSerializer, # Added new serializers 
    IDCounterSerializer, GradingScaleSerializer, UserSessionSerializer, SecurityAuditLogSerializer, 
    APICredentialSerializer, APICredentialHealthLogSerializer, PaymentSerializer, InvoiceSerializer, EventSerializer, SystemSettingSerializer, 
    TeacherAttendanceSerializer, TeacherAttendanceQRTokenSerializer, 
    NotificationSerializer, AnnouncementSerializer, ExamPaperSerializer, ClassChargeSerializer, PrintQueueItemSerializer,
    InvoiceAdjustmentSerializer, StudentGuardianLinkSerializer, 
    DepositBatchSerializer, ExpenseCategorySerializer, ExpenseSerializer, CashbookCloseSerializer,
    InstallmentPlanSerializer, InstallmentPlanItemSerializer, FeePromiseSerializer,
    FeeReminderLogSerializer, ResultsHoldLogSerializer, CommunicationCampaignSerializer,
    CommunicationDeliverySerializer,
    ExamTypeSerializer, AcademicCalendarEventSerializer, TermInstallmentPlanSerializer, StudentDebtRecordSerializer,
    TeacherSalarySerializer, TeacherAllowanceSerializer, OtherStaffSerializer, StaffPayrollSerializer
) 
from .utils import (
    generate_graduation_certificate_pdf, send_sms, generate_random_password, generate_otp,
    send_email, generate_teacher_credential_pdf, generate_staff_credential_pdf, generate_parent_credential_pdf,
    generate_family_credential_pdf,
    generate_student_credential_pdf, generate_admission_letter_pdf,
    generate_report_card_pdf, generate_payment_receipt_pdf, generate_fee_statement_pdf,
    generate_mail_merge_letter_pdf,
    _safe_format_template,
    sanitize_rich_text_html, rich_text_to_plain_text, get_active_api_credential,
    generate_deposit_batch_report_pdf, generate_cashbook_close_pdf, generate_cashier_handover_pdf,  # Added new utility functions
)
from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token
from django.utils.dateparse import parse_datetime
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import FileResponse
import secrets
from django.utils.decorators import method_decorator
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.core.cache import cache
from django.contrib.sessions.models import Session
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import requests
from decimal import Decimal, ROUND_HALF_UP

import logging
import json
import re
import base64
import io
import zipfile
import qrcode
import uuid
from PIL import Image, UnidentifiedImageError
logger = logging.getLogger(__name__)

def _truthy(v):
    return str(v or '').strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def _current_term():
    return AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number', '-start_date').first()


def _exact_term_for_date(target_date):
    if not target_date:
        return None
    return AcademicTerm.objects.filter(start_date__lte=target_date, end_date__gte=target_date).order_by('-academic_year', '-term_number', '-start_date').first()


def _term_for_date(target_date):
    if not target_date:
        return _current_term()
    return _exact_term_for_date(target_date) or _current_term()


def _term_covers_range(term, start_date, end_date=None, *, allow_holiday_break=False):
    if not term or not start_date:
        return False
    end_v = end_date or start_date
    window_end = term.end_date + timedelta(days=max(0, int(term.holiday_break_days or 0))) if allow_holiday_break else term.end_date
    return term.start_date <= start_date <= window_end and term.start_date <= end_v <= window_end


def _find_term_covering_range(start_date, end_date=None, *, allow_holiday_break=False, include_archived=False):
    qs = AcademicTerm.objects.all()
    if not include_archived:
        qs = qs.filter(is_archived=False)
    for term in qs.order_by('-academic_year', '-term_number', '-start_date'):
        if _term_covers_range(term, start_date, end_date, allow_holiday_break=allow_holiday_break):
            return term
    return None


def _require_term_window(*, start_date, end_date=None, allow_holiday_break=False, include_archived=False, label='date'):
    term = _find_term_covering_range(start_date, end_date, allow_holiday_break=allow_holiday_break, include_archived=include_archived)
    if term:
        return term
    end_v = end_date or start_date
    if end_date and end_date != start_date:
        raise DRFValidationError({label: f'{label} must fall within a configured academic term window.'})
    raise DRFValidationError({label: f'{label} must fall within a configured academic term.'})


def _require_active_term_target(academic_year, term_number, *, label='term'):
    active_term = _current_term()
    if not active_term:
        raise DRFValidationError({label: 'No active term is configured.'})
    if int(academic_year) != int(active_term.academic_year) or int(term_number) != int(active_term.term_number):
        raise DRFValidationError({label: f'Only the active term ({active_term.term_number}/{active_term.academic_year}) can be used right now.'})
    return active_term


def _term_sort_key(year, term):
    try:
        return (int(year), int(term))
    except Exception:
        return None


def _iter_student_term_pairs_upto(student, academic_year, term_number):
    target = _term_sort_key(academic_year, term_number)
    if target is None or not student:
        return []
    pairs = set()
    for inv in Invoice.objects.filter(student=student).values_list('academic_year', 'term_number'):
        key = _term_sort_key(inv[0], inv[1])
        if key and key <= target:
            pairs.add(key)
    for pay in Payment.objects.filter(student=student).values_list('academic_year', 'term_number'):
        key = _term_sort_key(pay[0], pay[1])
        if key and key <= target:
            pairs.add(key)
    for adj in InvoiceAdjustment.objects.filter(student=student, is_active=True).values_list('academic_year', 'term_number'):
        key = _term_sort_key(adj[0], adj[1])
        if key and key <= target:
            pairs.add(key)
    if target not in pairs:
        pairs.add(target)
    return sorted(pairs)


def _base_due_for_term(student, academic_year, term_number):
    if not student or not student.current_class_id:
        return Decimal('0.00')
    inv = Invoice.objects.filter(student=student, academic_year=academic_year, term_number=term_number).first()
    if inv is not None and inv.amount_due is not None:
        try:
            return Decimal(str(inv.amount_due)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            pass
    fs = FeeStructure.objects.filter(school_class_id=student.current_class_id, year=academic_year, term=term_number).first()
    if fs:
        try:
            return Decimal(str(fs.amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            return Decimal('0.00')
    try:
        return (Decimal(str(student.current_class.annual_fee)) / Decimal('3')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def _class_extras_for_term(student, academic_year, term_number):
    if not student or not student.current_class_id:
        return Decimal('0.00')
    sec = (student.section or '').strip().upper()
    cq = ClassCharge.objects.filter(
        school_class_id=student.current_class_id,
        is_active=True,
        is_published=True,
    ).filter(Q(section__isnull=True) | Q(section='') | Q(section=sec)).filter(
        Q(academic_year__isnull=True) | Q(academic_year=academic_year)
    ).filter(
        Q(term_number__isnull=True) | Q(term_number=term_number)
    )
    v = cq.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    try:
        return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def _adjustments_for_term(student, academic_year, term_number):
    if not student:
        return Decimal('0.00')
    v = InvoiceAdjustment.objects.filter(
        student=student,
        academic_year=academic_year,
        term_number=term_number,
        is_active=True,
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    try:
        return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def _payments_for_term(student, academic_year, term_number):
    if not student:
        return Decimal('0.00')
    v = Payment.objects.filter(
        student=student,
        academic_year=academic_year,
        term_number=term_number,
        status__in=['received', 'approved'],
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    try:
        return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def _opening_balance_before_term(student, academic_year, term_number):
    opening = Decimal('0.00')
    target = _term_sort_key(academic_year, term_number)
    if target is None:
        return opening
    for yr, tm in _iter_student_term_pairs_upto(student, academic_year, term_number):
        if (yr, tm) >= target:
            break
        due = (_base_due_for_term(student, yr, tm) + _class_extras_for_term(student, yr, tm) + _adjustments_for_term(student, yr, tm)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        paid = _payments_for_term(student, yr, tm)
        opening = (opening + paid - due).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return opening


def _public_holiday_settings():
    raw = get_system_setting('public_holiday_settings', {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    country_code = str(raw.get('country_code') or 'UG').strip().upper() or 'UG'
    subdivisions = raw.get('subdivision_code')
    return {
        'enabled': bool(raw.get('enabled', True)),
        'country_code': country_code,
        'subdivision_code': (str(subdivisions).strip().upper() if subdivisions else None),
    }


def _fetch_public_holidays(country_code, year):
    url = f'https://date.nager.at/api/v3/PublicHolidays/{int(year)}/{country_code}'
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, list) else []


def _sync_public_holiday_events(term):
    cfg = _public_holiday_settings()
    if not cfg['enabled']:
        return
    break_days = max(0, int(term.holiday_break_days or 0))
    range_end = term.end_date + timedelta(days=break_days)
    years = sorted({term.start_date.year, range_end.year})
    for yr in years:
        try:
            holidays = _fetch_public_holidays(cfg['country_code'], yr)
        except Exception:
            logger.warning("Public holiday sync failed for %s %s", cfg['country_code'], yr)
            continue
        for item in holidays:
            day_raw = item.get('date')
            if not day_raw:
                continue
            try:
                day = date.fromisoformat(str(day_raw))
            except Exception:
                continue
            if day < term.start_date or day > range_end:
                continue
            local_name = (item.get('localName') or item.get('name') or 'Public holiday').strip()
            title = f"Public Holiday: {local_name} ({day.isoformat()})"
            note = f"System-synced public holiday for {cfg['country_code']}."
            _upsert_system_event(
                title=title,
                defaults={
                    'description': note,
                    'start_date': day,
                    'end_date': day,
                    'audience_roles': [],
                    'is_published': True,
                    'image_url': None,
                    'created_by': None,
                },
            )


def _term_system_event_title(term, kind):
    prefix = f"Academic Term {term.term_number} {term.academic_year}"
    if kind == 'start':
        return f"{prefix} begins"
    if kind == 'end':
        return f"{prefix} ends"
    if kind == 'break':
        return f"{prefix} holiday break"
    raise ValueError(f"Unsupported term event kind: {kind}")


def _upsert_system_event(*, title, defaults):
    qs = Event.objects.filter(title=title, created_by__isnull=True).order_by('id')
    obj = qs.first()
    if obj is None:
        return Event.objects.create(title=title, **defaults)
    changed = []
    for field, value in defaults.items():
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed.append(field)
    if changed:
        obj.save(update_fields=changed + ['updated_at'])
    dup_ids = list(qs.values_list('id', flat=True)[1:])
    if dup_ids:
        Event.objects.filter(id__in=dup_ids).delete()
    return obj


def _sync_term_calendar_events(term):
    base_note = (
        f"System-generated from Academic Term {term.term_number}/{term.academic_year}. "
        "Edit the term to keep this calendar entry aligned."
    )
    start_title = _term_system_event_title(term, 'start')
    end_title = _term_system_event_title(term, 'end')
    break_title = _term_system_event_title(term, 'break')

    _upsert_system_event(
        title=start_title,
        defaults={
            'description': f"{base_note} Classes open on this date.",
            'start_date': term.start_date,
            'end_date': term.start_date,
            'audience_roles': [],
            'is_published': True,
            'image_url': None,
            'created_by': None,
        },
    )
    _upsert_system_event(
        title=end_title,
        defaults={
            'description': f"{base_note} Teaching for the term closes on this date.",
            'start_date': term.end_date,
            'end_date': term.end_date,
            'audience_roles': [],
            'is_published': True,
            'image_url': None,
            'created_by': None,
        },
    )

    break_days = max(0, int(term.holiday_break_days or 0))
    if break_days > 0:
        break_start = term.end_date + timedelta(days=1)
        break_end = term.end_date + timedelta(days=break_days)
        _upsert_system_event(
            title=break_title,
            defaults={
                'description': f"{base_note} Holiday break after term close.",
                'start_date': break_start,
                'end_date': break_end,
                'audience_roles': [],
                'is_published': True,
                'image_url': None,
                'created_by': None,
            },
        )
    else:
        Event.objects.filter(title=break_title, created_by__isnull=True).delete()
    _sync_public_holiday_events(term)


def _term_overlaps_existing(*, start_date, end_date, exclude_term_id=None):
    qs = AcademicTerm.objects.all()
    if exclude_term_id is not None:
        qs = qs.exclude(id=exclude_term_id)
    return qs.filter(start_date__lte=end_date, end_date__gte=start_date).exists()


def _serialize_term_calendar(term):
    today = timezone.localdate()
    weekends = []
    instructional_days = 0
    cursor = term.start_date
    while cursor <= term.end_date:
        if cursor.weekday() >= 5:
            weekends.append(cursor.isoformat())
        else:
            instructional_days += 1
        cursor += timedelta(days=1)

    break_days = max(0, int(term.holiday_break_days or 0))
    break_start = term.end_date + timedelta(days=1) if break_days > 0 else None
    break_end = term.end_date + timedelta(days=break_days) if break_days > 0 else None

    events_qs = Event.objects.filter(
        start_date__lte=(break_end or term.end_date),
    ).filter(
        Q(end_date__isnull=True, start_date__gte=term.start_date) | Q(end_date__gte=term.start_date)
    ).order_by('start_date', 'end_date', 'title')

    timetable_qs = Timetable.objects.filter(is_active=True, academic_year=term.academic_year, term_number=term.term_number).order_by('school_class__level', 'section', 'id')

    if today < term.start_date:
        status_label = 'upcoming'
    elif today > term.end_date:
        status_label = 'completed'
    else:
        status_label = 'active'

    return {
        'term': AcademicTermSerializer(term).data,
        'status': status_label,
        'today': today.isoformat(),
        'today_in_term': term.start_date <= today <= term.end_date,
        'instructional_days': instructional_days,
        'weekend_days': weekends,
        'weekend_count': len(weekends),
        'holiday_break': {
            'days': break_days,
            'start_date': break_start.isoformat() if break_start else None,
            'end_date': break_end.isoformat() if break_end else None,
        },
        'events': EventSerializer(events_qs, many=True).data,
        'timetables': TimetableSerializer(timetable_qs, many=True).data,
    }


def _is_placeholder_twilio_sid(value):
    value = str(value or '').strip()
    return (not value) or value == 'ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'


def _is_placeholder_twilio_secret(value):
    value = str(value or '').strip()
    return (not value) or value == 'your_auth_token'


def _is_placeholder_twilio_number(value):
    value = str(value or '').strip()
    return (not value) or value == '+15017122661'


def _email_transport_meta():
    smtp_cred = get_active_api_credential('gmail_smtp') or get_active_api_credential('email_smtp')
    if smtp_cred:
        return {
            'email_transport': smtp_cred.get_service_name_display(),
            'email_delivery_mode': 'live-smtp',
            'email_live_ready': True,
        }

    backend = str(getattr(settings, 'EMAIL_BACKEND', '') or '').strip()
    if backend == 'django.core.mail.backends.console.EmailBackend':
        return {
            'email_transport': 'Django Console Backend',
            'email_delivery_mode': 'console',
            'email_live_ready': False,
        }
    if backend == 'django.core.mail.backends.smtp.EmailBackend':
        return {
            'email_transport': 'Django SMTP Backend',
            'email_delivery_mode': 'django-smtp',
            'email_live_ready': True,
        }
    return {
        'email_transport': backend or 'Not configured',
        'email_delivery_mode': 'unknown',
        'email_live_ready': False,
    }


def _sms_transport_meta():
    meg = get_active_api_credential('megasms')
    if meg and (meg.api_key or '').strip():
        return {
            'sms_transport': meg.get_service_name_display(),
            'sms_delivery_mode': 'live-api',
            'sms_live_ready': True,
        }

    twilio_cred = get_active_api_credential('twilio_sms')
    if twilio_cred:
        sid = (twilio_cred.client_id or '').strip()
        token = (twilio_cred.client_secret or '').strip()
        from_number = ((twilio_cred.extra_data or {}).get('from_number') or '').strip()
    else:
        sid = str(getattr(settings, 'TWILIO_ACCOUNT_SID', '') or '').strip()
        token = str(getattr(settings, 'TWILIO_AUTH_TOKEN', '') or '').strip()
        from_number = str(getattr(settings, 'TWILIO_PHONE_NUMBER', '') or '').strip()

    live_ready = not (
        _is_placeholder_twilio_sid(sid)
        or _is_placeholder_twilio_secret(token)
        or _is_placeholder_twilio_number(from_number)
    )
    return {
        'sms_transport': 'Twilio SMS',
        'sms_delivery_mode': 'live-api' if live_ready else 'unconfigured',
        'sms_live_ready': bool(live_ready),
    }

def _handover_cache_key(kind, obj_id, token):
    return f"handover:{kind}:{obj_id}:{token}"

def _issue_handover_token(kind, obj_id, payload, ttl_seconds=15 * 60):
    token = secrets.token_urlsafe(16)
    cache.set(_handover_cache_key(kind, obj_id, token), payload, timeout=ttl_seconds)
    return token

def _get_handover_payload(kind, obj_id, token):
    if not token:
        return None
    return cache.get(_handover_cache_key(kind, obj_id, token))

ADMIN_ROLE_LIST = ['admin', 'director', 'headteacher', 'deputy', 'dos']
ADMIN_ROLES = set(ADMIN_ROLE_LIST)
PASSWORD_ADMIN_ROLES = {'superadmin', 'director', 'headteacher', 'dos'}

def is_admin_role(role: Optional[str]) -> bool:
    return bool(role) and role in ADMIN_ROLES


def can_manage_passwords(user) -> bool:
    role = get_role(user)
    return bool(user and user.is_authenticated and (user.is_superuser or role in PASSWORD_ADMIN_ROLES))

def get_system_setting(key, default=None):
    """
    Read a system setting with a small cache for performance.
    """
    ck = f"sysset:{key}"
    cached = cache.get(ck, None)
    if cached is not None:
        return cached
    obj = SystemSetting.objects.filter(key=key).first()
    val = obj.value if obj else default
    cache.set(ck, val, timeout=60)
    return val


def _notif_prefs_for(user):
    """
    Returns merged notification prefs with defaults.
    """
    defaults = {'in_app': True, 'finance': True, 'academic': True, 'events': True, 'security': True, 'system': True}
    try:
        prefs = getattr(getattr(user, 'profile', None), 'notification_prefs', None) or {}
    except Exception:
        prefs = {}
    out = dict(defaults)
    if isinstance(prefs, dict):
        out.update({k: bool(v) for k, v in prefs.items() if k in out})
    return out


def notify_user(
    user,
    *,
    category='system',
    title,
    message=None,
    link_page=None,
    link_object_id=None,
    meta=None,
    force=False,
    student=None,
    school_class=None,
    event_key=None,
):
    """
    Create an in-app notification for a single user, respecting per-user prefs.
    """
    if not user:
        return None
    prefs = _notif_prefs_for(user)
    if not force:
        if not prefs.get('in_app', True):
            return None
        if category in prefs and not prefs.get(category, True):
            return None
    if student and not school_class:
        school_class = getattr(student, 'current_class', None)
    payload = dict(meta or {})
    if student:
        payload.setdefault('student_id', student.id)
        payload.setdefault('student_system_id', getattr(student, 'student_id', None))
        payload.setdefault('student_name', f"{getattr(student, 'first_name', '')} {getattr(student, 'last_name', '')}".strip())
    if school_class:
        payload.setdefault('class_id', school_class.id)
        payload.setdefault('class_level', getattr(school_class, 'level', None))
    if event_key:
        payload.setdefault('event_key', event_key)
        existing = Notification.objects.filter(user=user, event_key=event_key).order_by('-created_at').first()
        if existing:
            changed = False
            if title and existing.title != title[:180]:
                existing.title = title[:180]
                changed = True
            if message is not None and existing.message != message:
                existing.message = message
                changed = True
            if link_page is not None and existing.link_page != link_page:
                existing.link_page = link_page
                changed = True
            if link_object_id is not None and existing.link_object_id != link_object_id:
                existing.link_object_id = link_object_id
                changed = True
            if student is not None and getattr(existing, 'student_id', None) != getattr(student, 'id', None):
                existing.student = student
                changed = True
            if school_class is not None and getattr(existing, 'school_class_id', None) != getattr(school_class, 'id', None):
                existing.school_class = school_class
                changed = True
            if getattr(existing, 'meta', None) != payload:
                setattr(existing, 'meta', payload)
                changed = True
            if changed:
                existing.save(update_fields=['title', 'message', 'link_page', 'link_object_id', 'student', 'school_class', 'meta'])
            return existing
    return Notification.objects.create(
        user=user,
        category=category,
        title=title[:180],
        message=message,
        student=student,
        school_class=school_class,
        link_page=link_page,
        link_object_id=link_object_id,
        event_key=event_key,
        meta=payload,
    )


def notify_roles(
    roles,
    *,
    category='system',
    title,
    message=None,
    link_page=None,
    link_object_id=None,
    meta=None,
    force=False,
    student=None,
    school_class=None,
    event_key=None,
):
    """
    Broadcast to all users whose profile.role is in roles.
    """
    roles = list(roles or [])
    if not roles:
        return 0
    users = User.objects.filter(profile__role__in=roles).distinct()
    n = 0
    for u in users:
        if notify_user(
            u,
            category=category,
            title=title,
            message=message,
            link_page=link_page,
            link_object_id=link_object_id,
            meta=meta,
            force=force,
            student=student,
            school_class=school_class,
            event_key=event_key,
        ):
            n += 1
    return n


def _normalize_username_part(value):
    cleaned = re.sub(r'[^a-z0-9]+', '.', str(value or '').strip().lower())
    cleaned = re.sub(r'\.+', '.', cleaned).strip('.')
    return cleaned


def _recommended_username(first_name='', last_name='', role='user'):
    first = _normalize_username_part(first_name)
    last = _normalize_username_part(last_name)
    if first and last:
        base = f'{first}.{last}'
    else:
        base = first or last or _normalize_username_part(role) or 'user'
    base = base[:30].strip('.')
    return base or 'user'


def _unique_username(base, fallback='user'):
    root = (_normalize_username_part(base) or _normalize_username_part(fallback) or 'user')[:30].strip('.')
    root = root or 'user'
    candidate = root
    counter = 2
    while User.objects.filter(username=candidate).exists():
        suffix = f'.{counter}'
        trimmed = root[: max(1, 30 - len(suffix))].rstrip('.')
        candidate = f'{trimmed}{suffix}'
        counter += 1
    return candidate


class IsSuperUser(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        # App-level "Super Admin" (profile role) should have super-admin privileges
        # in the SPA even if not a Django admin superuser.
        try:
            return getattr(getattr(request.user, 'profile', None), 'role', None) == 'superadmin'
        except Exception:
            return False


class IsFinanceUser(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        try:
            return getattr(getattr(request.user, 'profile', None), 'role', None) in (['bursar', 'superadmin'] + ADMIN_ROLE_LIST)
        except UserProfile.DoesNotExist:
            return False


class IsPayrollUser(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        role = get_role(request.user)
        return role in ['superadmin', 'director', 'headteacher', 'bursar']


class IsStaffAdmin(permissions.BasePermission):
    """
    Superadmin + admin-like roles + reception/bursar (for staff operations).
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if IsSuperUser().has_permission(request, view):
            return True
        role = get_role(request.user)
        return bool(role) and (is_admin_role(role) or role in ['reception', 'bursar'])


class IsStaffAdminOrTeacherReadOnly(permissions.BasePermission):
    """
    Allow staff admins full access, and teachers read-only access.
    Useful for reference data like subjects/class-subjects.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if IsStaffAdmin().has_permission(request, view):
            return True
        role = get_role(request.user)
        if role == 'teacher' and request.method in permissions.SAFE_METHODS:
            return True
        return False


class CanManagePromotions(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and has_promotion_permission(request.user))


class CanManageTerms(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and has_term_management_permission(request.user))


class CanManageReportCards(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and has_report_card_permission(request.user))


class CanManageGrading(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and has_grading_permission(request.user))


def get_role(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'superadmin'
    try:
        return user.profile.role
    except UserProfile.DoesNotExist:
        return None


def get_teacher_scope(user): 
    """ 
    Returns (class_level, section) for a teacher user.
    Preference order:
    1) Class-teacher assignment (Teacher.is_class_teacher + class_teacher_class)
    2) Teacher.assigned_class like 'P.4A'
    """ 
    if not user or not user.is_authenticated:
        return None, None
    try:
        t = user.teacher_profile
    except Exception:
        return None, None

    # Prefer class-teacher assignment if present. 
    try: 
        if getattr(t, 'is_class_teacher', False) and getattr(t, 'class_teacher_class', None): 
            lvl = getattr(t.class_teacher_class, 'level', None) 
            sec = (getattr(t, 'class_teacher_section', '') or '').strip().upper() 
            return lvl, sec 
    except Exception: 
        pass 
 
    raw = (t.assigned_class or '').strip().upper().replace(' ', '') 
    if not raw:
        return None, None

    # Sections are optional. Accept "P.4A" or "P.4".
    m = re.match(r'^(P\.?\d)([A-Z])?$', raw)
    if not m:
        return None, None

    lvl = m.group(1)
    if lvl.startswith('P') and not lvl.startswith('P.'):
        lvl = lvl.replace('P', 'P.', 1)
    sec = m.group(2) or ''
    return lvl, sec


def get_student_scope(user):
    """
    Returns (student_obj, class_level, section) for a student portal user.
    Convention: student user.username == Student.student_id
    """
    if not user or not user.is_authenticated:
        return None, None, None
    try:
        role = user.profile.role
    except Exception:
        role = None
    if role != 'student':
        return None, None, None
    sid = (user.username or '').strip()
    if not sid:
        return None, None, None
    stu = Student.objects.select_related('current_class').filter(student_id=sid).first()
    if not stu or not stu.current_class:
        return stu, None, None
    # Section can be blank for schools without sections.
    sec = (stu.section or '').strip().upper()
    return stu, stu.current_class.level, sec


def _to_decimal(value, default='0.00'):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(str(default))


def _coerce_event_datetime(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    try:
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
    except Exception:
        pass
    return value


def _payment_method_label(method):
    labels = {
        'cash': 'Cash',
        'bank': 'Bank',
        'mtn_momo': 'MTN MoMo',
        'airtel_money': 'Airtel Money',
        'other': 'Other',
    }
    key = (method or '').strip().lower()
    return labels.get(key, key or 'Other')


def _normalize_msisdn(value):
    raw = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if not raw:
        return ''
    if raw.startswith('256'):
        return raw
    if raw.startswith('0') and len(raw) >= 10:
        return '256' + raw[1:]
    if raw.startswith('7') and len(raw) == 9:
        return '256' + raw
    return raw


def _next_receipt_number(payment):
    d = timezone.localdate()
    return f"RCPT-{d.strftime('%Y%m%d')}-{payment.id:06d}"


def _mobile_provider_success(value):
    norm = str(value or '').strip().lower()
    return norm in {'success', 'successful', 'completed', 'complete', 'approved', 'received', 'paid', 'ok'}


def _mobile_provider_failure(value):
    norm = str(value or '').strip().lower()
    return norm in {'failed', 'failure', 'cancelled', 'rejected', 'declined', 'timeout', 'timed_out', 'expired', 'error'}


def _get_parent_contacts(student):
    phones = []
    emails = []
    if not student:
        return {'phones': phones, 'emails': emails}
    for phone in [getattr(student, 'parent_phone', None), getattr(student, 'parent_phone2', None)]:
        phone = (phone or '').strip()
        if phone and phone not in phones:
            phones.append(phone)
    for link in StudentGuardianLink.objects.select_related('parent_user', 'parent_user__profile').filter(student=student, is_active=True):
        try:
            prof = link.parent_user.profile
        except Exception:
            prof = None
        email = ((getattr(prof, 'email_address', None) or getattr(link.parent_user, 'email', None)) or '').strip()
        phone = (getattr(prof, 'phone_number', None) or '').strip()
        if email and email not in emails:
            emails.append(email)
        if phone and phone not in phones:
            phones.append(phone)
    return {'phones': phones, 'emails': emails}


def _record_fee_reminder_log(*, student, created_by=None, channel='sms', status_v='sent', recipient=None, message=None, invoice=None, plan=None, installment=None, promise=None, provider=None, metadata=None):
    return FeeReminderLog.objects.create(
        student=student,
        invoice=invoice,
        plan=plan,
        installment=installment,
        promise=promise,
        academic_year=getattr(invoice, 'academic_year', None) or getattr(plan, 'academic_year', None) or getattr(promise, 'academic_year', None),
        term_number=getattr(invoice, 'term_number', None) or getattr(plan, 'term_number', None) or getattr(promise, 'term_number', None),
        channel=channel,
        status=status_v,
        recipient=recipient,
        message=message,
        provider=provider,
        metadata=metadata or {},
        created_by=created_by,
    )


def _sync_installment_item_status(item, *, save=True):
    if not item:
        return item
    due = getattr(item, 'due_date', None)
    amount = _to_decimal(getattr(item, 'amount', 0))
    paid = _to_decimal(getattr(item, 'amount_paid', 0))
    today = timezone.localdate()

    if getattr(item, 'status', None) == 'cancelled':
        return item
    if paid >= amount and amount > 0:
        item.amount_paid = amount
        item.status = 'paid'
        if not item.paid_at:
            item.paid_at = timezone.now()
    elif paid > 0:
        item.status = 'partial'
        item.paid_at = None
    elif due and due < today:
        item.status = 'overdue'
        item.paid_at = None
    else:
        item.status = 'pending'
        item.paid_at = None

    if save:
        item.save(update_fields=['amount_paid', 'status', 'paid_at', 'updated_at'])
    return item


def _sync_installment_plan_status(plan, *, save=True):
    if not plan or getattr(plan, 'status', None) == 'cancelled':
        return plan
    items = list(plan.items.all())
    if items and all((it.status == 'paid') for it in items):
        plan.status = 'completed'
    elif any((it.status == 'overdue') for it in items):
        plan.status = 'defaulted'
    else:
        plan.status = 'active'
    if save:
        plan.save(update_fields=['status', 'updated_at'])
    return plan


def _refresh_finance_commitments(student, academic_year, term_number):
    if not student or not academic_year or not term_number:
        return
    total_paid = _to_decimal(
        Payment.objects.filter(
            student=student,
            academic_year=academic_year,
            term_number=term_number,
            status__in=['received', 'approved'],
        ).aggregate(s=Sum('amount'))['s']
        or Decimal('0.00')
    )
    remaining = total_paid
    items = list(
        InstallmentPlanItem.objects.select_related('plan')
        .filter(plan__student=student, plan__academic_year=academic_year, plan__term_number=term_number)
        .exclude(plan__status='cancelled')
        .order_by('due_date', 'plan__created_at', 'id')
    )
    touched_plan_ids = set()
    for item in items:
        amount = _to_decimal(item.amount)
        paid_now = min(amount, remaining) if remaining > 0 else Decimal('0.00')
        remaining = (remaining - paid_now).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if remaining > 0 else Decimal('0.00')
        if item.amount_paid != paid_now:
            item.amount_paid = paid_now
        _sync_installment_item_status(item, save=True)
        touched_plan_ids.add(item.plan_id)

    for plan_id in touched_plan_ids:
        plan = InstallmentPlan.objects.filter(id=plan_id).first()
        if plan:
            _sync_installment_plan_status(plan, save=True)

    promises = FeePromise.objects.select_related('installment').filter(student=student, academic_year=academic_year, term_number=term_number)
    today = timezone.localdate()
    for promise in promises:
        if promise.status == 'cancelled':
            continue
        new_status = promise.status
        fulfilled_at = promise.fulfilled_at
        if promise.installment_id and promise.installment:
            inst_status = promise.installment.status
            if inst_status == 'paid':
                new_status = 'kept'
                fulfilled_at = promise.installment.paid_at or timezone.now()
            elif inst_status == 'cancelled':
                new_status = 'cancelled'
            elif promise.promised_for and promise.promised_for < today and inst_status in ['pending', 'overdue']:
                new_status = 'missed'
                fulfilled_at = None
            else:
                new_status = 'open'
                fulfilled_at = None
        elif promise.promised_for and promise.promised_for < today and promise.status == 'open':
            new_status = 'missed'
        if new_status != promise.status or fulfilled_at != promise.fulfilled_at:
            promise.status = new_status
            promise.fulfilled_at = fulfilled_at
            promise.save(update_fields=['status', 'fulfilled_at', 'updated_at'])


def _build_cashbook_snapshot(close_date, *, cashier=None, opening_cash=None, counted_cash_on_hand=None):
    close_date = close_date or timezone.localdate()
    opening_cash = _to_decimal(opening_cash or 0)
    counted_cash_on_hand = _to_decimal(counted_cash_on_hand or 0)

    payments_qs = Payment.objects.select_related('student', 'received_by', 'deposit_batch').filter(
        received_at__date=close_date,
        status__in=['received', 'approved'],
    ).order_by('received_at', 'id')
    if cashier:
        payments_qs = payments_qs.filter(received_by=cashier)

    expenses_qs = Expense.objects.select_related('category', 'created_by').filter(
        expense_date=close_date,
        status='approved',
    ).order_by('expense_date', 'id')
    if cashier:
        expenses_qs = expenses_qs.filter(created_by=cashier)

    method_rows = {}
    cashier_rows = {}
    cash_received_total = Decimal('0.00')
    non_cash_received_total = Decimal('0.00')
    payment_count = 0
    for payment in payments_qs:
        amount = _to_decimal(payment.amount)
        payment_count += 1
        method_key = (payment.method or 'other').strip().lower() or 'other'
        method_rec = method_rows.setdefault(method_key, {'method': method_key, 'method_label': _payment_method_label(method_key), 'count': 0, 'total_amount': Decimal('0.00')})
        method_rec['count'] += 1
        method_rec['total_amount'] += amount

        cashier_name = getattr(getattr(payment, 'received_by', None), 'username', None) or 'Unassigned'
        cashier_rec = cashier_rows.setdefault(cashier_name, {'cashier_name': cashier_name, 'count': 0, 'total_amount': Decimal('0.00')})
        cashier_rec['count'] += 1
        cashier_rec['total_amount'] += amount

        if method_key == 'cash':
            cash_received_total += amount
        else:
            non_cash_received_total += amount

    expense_total = Decimal('0.00')
    expense_count = 0
    expenses_by_category = {}
    for expense in expenses_qs:
        amount = _to_decimal(expense.amount)
        expense_count += 1
        expense_total += amount
        cat_name = getattr(getattr(expense, 'category', None), 'name', None) or 'Uncategorised'
        cat_rec = expenses_by_category.setdefault(cat_name, {'category': cat_name, 'count': 0, 'total_amount': Decimal('0.00')})
        cat_rec['count'] += 1
        cat_rec['total_amount'] += amount

    batch_qs = DepositBatch.objects.filter(deposit_date=close_date).order_by('id')
    if cashier:
        batch_qs = batch_qs.filter(payments__received_by=cashier).distinct()
    deposit_batches = []
    deposit_batch_total = Decimal('0.00')
    for batch in batch_qs:
        total = _to_decimal(batch.payments.filter(status__in=['received', 'approved']).aggregate(s=Sum('amount'))['s'] or 0)
        count = batch.payments.filter(status__in=['received', 'approved']).count()
        deposit_batch_total += total
        deposit_batches.append({
            'batch_id': batch.id,
            'batch_name': batch.name or f'Batch #{batch.id}',
            'payments_count': count,
            'total_amount': str(total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'is_posted': bool(batch.is_posted),
            'reference': batch.reference,
        })

    expected_cash_on_hand = (opening_cash + cash_received_total - expense_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    variance_amount = (counted_cash_on_hand - expected_cash_on_hand).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        'close_date': close_date.isoformat(),
        'cashier_id': getattr(cashier, 'id', None),
        'cashier_username': getattr(cashier, 'username', None),
        'opening_cash': str(opening_cash.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'counted_cash_on_hand': str(counted_cash_on_hand.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'cash_received_total': str(cash_received_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'non_cash_received_total': str(non_cash_received_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'approved_expense_total': str(expense_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'expected_cash_on_hand': str(expected_cash_on_hand),
        'variance_amount': str(variance_amount),
        'deposit_batch_total': str(deposit_batch_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'payment_count': payment_count,
        'expense_count': expense_count,
        'by_method': [
            {
                'method': r['method'],
                'method_label': r['method_label'],
                'count': r['count'],
                'total_amount': str(r['total_amount'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            }
            for r in sorted(method_rows.values(), key=lambda x: x['method_label'])
        ],
        'by_cashier': [
            {
                'cashier_name': r['cashier_name'],
                'count': r['count'],
                'total_amount': str(r['total_amount'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            }
            for r in sorted(cashier_rows.values(), key=lambda x: x['cashier_name'])
        ],
        'deposit_batches': deposit_batches,
        'expenses_by_category': [
            {
                'category': r['category'],
                'count': r['count'],
                'total_amount': str(r['total_amount'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            }
            for r in sorted(expenses_by_category.values(), key=lambda x: x['category'])
        ],
    }


def _build_credential_health_summary():
    def gateway_item(code, label, service_name):
        cred = APICredential.objects.filter(service_name=service_name).order_by('-is_active', '-updated_at').first()
        if not cred:
            return {
                'code': code,
                'label': label,
                'configured': False,
                'verified': False,
                'callback_ready': False,
                'callback_url': None,
                'readiness_label': 'Not configured',
                'detail': 'No credential saved yet.',
            }
        extra = cred.extra_data if isinstance(cred.extra_data, dict) else {}
        callback_url = str(extra.get('callback_url') or '').strip() or None
        callback_ready = bool(
            callback_url
            and callback_url.startswith('https://')
            and 'localhost' not in callback_url
            and '127.0.0.1' not in callback_url
        )
        verified = bool(cred.is_active and cred.last_verify_ok is True)
        detail_bits = [
            'configured' if cred.is_active else 'inactive',
            'verified' if verified else 'not verified',
            'callback ready' if callback_ready else 'callback missing/private',
        ]
        return {
            'code': code,
            'label': label,
            'configured': True,
            'verified': verified,
            'callback_ready': callback_ready,
            'callback_url': callback_url,
            'readiness_label': 'Ready' if (verified and callback_ready) else 'Needs attention',
            'detail': ', '.join(detail_bits),
        }

    def item(code, label, service_names):
        cred = (
            APICredential.objects.filter(service_name__in=service_names)
            .order_by('-is_active', '-updated_at')
            .first()
        )
        last_failure = (
            APICredentialHealthLog.objects.filter(service_name__in=service_names, is_ok=False)
            .order_by('-verified_at', '-id')
            .first()
        )
        if not cred:
            return {
                'code': code,
                'label': label,
                'configured': False,
                'is_active': False,
                'status': 'missing',
                'status_label': 'Not configured',
                'service_name': None,
                'service_label': None,
                'last_verified_at': None,
                'last_verify_ok': None,
                'detail': 'No credential saved yet.',
                'updated_at': None,
                'last_failure_at': getattr(last_failure, 'verified_at', None),
                'last_failure_detail': getattr(last_failure, 'detail', None),
            }

        if not cred.is_active:
            status_key = 'inactive'
            status_label = 'Inactive'
        elif cred.last_verify_ok is True:
            status_key = 'healthy'
            status_label = 'Verified'
        elif cred.last_verify_ok is False:
            status_key = 'failing'
            status_label = 'Attention'
        else:
            status_key = 'unverified'
            status_label = 'Needs verification'

        detail = (cred.last_verify_detail or '').strip()
        if not detail:
            detail = {
                'inactive': 'Credential is saved but currently disabled.',
                'healthy': 'Credential is active and last verification succeeded.',
                'failing': 'Last verification failed. Check provider settings.',
                'unverified': 'Credential is saved but has not been verified yet.',
            }.get(status_key, '')

        return {
            'code': code,
            'label': label,
            'configured': True,
            'is_active': bool(cred.is_active),
            'status': status_key,
            'status_label': status_label,
            'service_name': cred.service_name,
            'service_label': cred.get_service_name_display(),
            'last_verified_at': cred.last_verified_at,
            'last_verify_ok': cred.last_verify_ok,
            'detail': detail,
            'updated_at': cred.updated_at,
            'last_failure_at': getattr(last_failure, 'verified_at', None),
            'last_failure_detail': getattr(last_failure, 'detail', None),
        }

    providers = [
        item('gmail', 'Gmail / Email', ['gmail_smtp', 'email_smtp']),
        item('mtn', 'MTN MoMo', ['mtn_momo']),
        item('airtel', 'Airtel Money', ['airtel_money']),
        item('sms', 'SMS Gateway', ['megasms', 'twilio_sms']),
    ]
    healthy_count = sum(1 for p in providers if p['status'] == 'healthy')
    attention_count = sum(1 for p in providers if p['status'] in ['failing', 'missing'])
    recent_failures = [
        {
            'service_name': log.service_name,
            'service_label': APICredential(service_name=log.service_name).get_service_name_display(),
            'detail': log.detail,
            'verified_at': log.verified_at,
            'verified_by_username': getattr(getattr(log, 'verified_by', None), 'username', None),
        }
        for log in APICredentialHealthLog.objects.select_related('verified_by').filter(is_ok=False).order_by('-verified_at', '-id')[:8]
    ]
    return {
        'providers': providers,
        'gateways': [
            gateway_item('mtn', 'MTN MoMo', 'mtn_momo'),
            gateway_item('airtel', 'Airtel Money', 'airtel_money'),
        ],
        'summary': {
            'healthy_count': healthy_count,
            'attention_count': attention_count,
            'configured_count': sum(1 for p in providers if p['configured']),
            'total_count': len(providers),
        },
        'recent_failures': recent_failures,
        'notifications': {
            'send_credentials_email_enabled': bool(get_system_setting('send_credentials_email', True)),
            'send_credentials_sms_enabled': bool(get_system_setting('send_credentials_sms', True)),
            'send_fee_reminder_sms_enabled': bool(get_system_setting('send_fee_reminder_sms', True)),
        },
    }


def _build_cashbook_handover(close_date, *, cashier=None):
    close_date = close_date or timezone.localdate()

    prior_qs = CashbookClose.objects.select_related('cashier', 'closed_by').filter(
        status='closed',
        close_date__lt=close_date,
    ).order_by('-close_date', '-created_at')
    if cashier:
        prior_qs = prior_qs.filter(cashier=cashier)
    prior_close = prior_qs.first()

    opening_cash_suggestion = _to_decimal(getattr(prior_close, 'counted_cash_on_hand', 0))

    pending_deposit_qs = DepositBatch.objects.filter(
        is_posted=False,
        deposit_date__lte=close_date,
    ).order_by('deposit_date', 'id')
    if cashier:
        pending_deposit_qs = pending_deposit_qs.filter(
            Q(created_by=cashier) | Q(payments__received_by=cashier)
        ).distinct()

    pending_deposits = []
    pending_deposit_total = Decimal('0.00')
    for batch in pending_deposit_qs[:12]:
        payments_qs = batch.payments.filter(status__in=['received', 'approved'])
        if cashier:
            payments_qs = payments_qs.filter(received_by=cashier)
        total = _to_decimal(payments_qs.aggregate(s=Sum('amount'))['s'] or 0)
        count = payments_qs.count()
        if cashier and count == 0:
            continue
        pending_deposit_total += total
        pending_deposits.append({
            'batch_id': batch.id,
            'batch_name': batch.name or f'Batch #{batch.id}',
            'deposit_date': batch.deposit_date.isoformat() if batch.deposit_date else None,
            'payments_count': count,
            'total_amount': str(total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'is_posted': bool(batch.is_posted),
            'reference': batch.reference,
        })

    promise_qs = FeePromise.objects.select_related('student', 'installment').filter(
        status__in=['open', 'missed']
    )
    unresolved_promise_total = _to_decimal(promise_qs.aggregate(s=Sum('amount'))['s'] or 0)
    unresolved_promise_count = promise_qs.count()
    overdue_promise_count = promise_qs.filter(promised_for__lt=close_date).count()
    unresolved_promises = []
    for promise in promise_qs.order_by('promised_for', 'created_at')[:10]:
        unresolved_promises.append({
            'id': promise.id,
            'student_id': promise.student_id,
            'student_name': f"{promise.student.first_name} {promise.student.last_name}".strip(),
            'promised_for': promise.promised_for.isoformat() if promise.promised_for else None,
            'status': promise.status,
            'amount': str(_to_decimal(promise.amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'installment_label': getattr(getattr(promise, 'installment', None), 'label', None),
            'notes': promise.notes,
        })

    return {
        'close_date': close_date.isoformat(),
        'cashier_id': getattr(cashier, 'id', None),
        'cashier_username': getattr(cashier, 'username', None),
        'opening_cash_suggestion': str(opening_cash_suggestion.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'prior_close': {
            'id': getattr(prior_close, 'id', None),
            'close_date': prior_close.close_date.isoformat() if getattr(prior_close, 'close_date', None) else None,
            'counted_cash_on_hand': str(_to_decimal(getattr(prior_close, 'counted_cash_on_hand', 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'variance_amount': str(_to_decimal(getattr(prior_close, 'variance_amount', 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            'cashier_username': getattr(getattr(prior_close, 'cashier', None), 'username', None),
            'notes': getattr(prior_close, 'notes', None),
        } if prior_close else None,
        'pending_deposit_count': len(pending_deposits),
        'pending_deposit_total': str(pending_deposit_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'pending_deposits': pending_deposits,
        'unresolved_promise_count': unresolved_promise_count,
        'overdue_promise_count': overdue_promise_count,
        'unresolved_promise_total': str(unresolved_promise_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'unresolved_promises': unresolved_promises,
    }


def _handover_alert_context(summary):
    summary = summary or {}
    alerts = []
    pending_deposit_count = int(summary.get('pending_deposit_count') or 0)
    unresolved_promise_count = int(summary.get('unresolved_promise_count') or 0)
    overdue_promise_count = int(summary.get('overdue_promise_count') or 0)
    prior_close = summary.get('prior_close') or {}
    prior_variance = _to_decimal((prior_close or {}).get('variance_amount') or 0)

    if pending_deposit_count > 0:
        alerts.append({
            'code': 'pending_deposits',
            'title': f'{pending_deposit_count} pending deposit batch(es)',
            'detail': f"UGX {float(summary.get('pending_deposit_total') or 0):,.0f} still waiting to be posted to bank.",
        })
    if unresolved_promise_count > 0:
        suffix = f' ({overdue_promise_count} overdue)' if overdue_promise_count > 0 else ''
        alerts.append({
            'code': 'fee_promises',
            'title': f'{unresolved_promise_count} unresolved fee promise(s){suffix}',
            'detail': f"UGX {float(summary.get('unresolved_promise_total') or 0):,.0f} still outstanding from parent commitments.",
        })
    if prior_variance != Decimal('0.00'):
        alerts.append({
            'code': 'prior_variance',
            'title': 'Previous cashbook closed with variance',
            'detail': f"Last recorded variance was UGX {float(prior_variance):,.0f}.",
        })
    return alerts


def _handover_alert_is_due(now=None):
    enabled = bool(get_system_setting('cashier_handover_alert_enabled', True))
    if not enabled:
        return False, 'disabled'
    now = now or timezone.localtime()
    cutoff_raw = str(get_system_setting('cashier_handover_alert_time', '16:30') or '16:30').strip()
    try:
        hh, mm = cutoff_raw.split(':', 1)
        cutoff_minutes = int(hh) * 60 + int(mm)
    except Exception:
        cutoff_raw = '16:30'
        cutoff_minutes = 16 * 60 + 30
    now_minutes = now.hour * 60 + now.minute
    return now_minutes >= cutoff_minutes, cutoff_raw


def _ensure_cashbook_handover_notification(request_user, summary):
    if not request_user or not getattr(request_user, 'is_authenticated', False):
        return None
    role = get_role(request_user)
    if role not in (['bursar', 'superadmin'] + ADMIN_ROLE_LIST):
        return None
    due, cutoff_raw = _handover_alert_is_due()
    if not due:
        return None
    alerts = _handover_alert_context(summary)
    if not alerts:
        return None
    close_date = str((summary or {}).get('close_date') or timezone.localdate().isoformat())
    cashier_scope = str((summary or {}).get('cashier_id') or 'school')
    event_key = f"cashier_handover:{cashier_scope}:{close_date}"
    title = f'Cashier handover reminder for {close_date}'
    message = ' · '.join(a['title'] for a in alerts[:3])
    meta = {
        'close_date': close_date,
        'cutoff_time': cutoff_raw,
        'alerts': alerts,
        'scope': cashier_scope,
        'pending_deposit_count': summary.get('pending_deposit_count'),
        'unresolved_promise_count': summary.get('unresolved_promise_count'),
    }
    return notify_user(
        request_user,
        category='finance',
        title=title,
        message=message,
        link_page='cashbook',
        meta=meta,
        event_key=event_key,
        force=True,
    )


def _build_student_finance_timeline(student, *, limit=300):
    events = []

    def push_event(event_at, kind, title, detail=None, amount=None, extra=None):
        dt = _coerce_event_datetime(event_at)
        if not dt:
            return
        events.append({
            'event_at': dt,
            'kind': kind,
            'title': title,
            'detail': detail,
            'amount': str(_to_decimal(amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) if amount is not None else None,
            'extra': extra or {},
        })

    invoices = Invoice.objects.filter(student=student).order_by('-academic_year', '-term_number')
    for inv in invoices:
        push_event(
            inv.created_at or inv.updated_at,
            'invoice',
            f"Invoice opened for Term {inv.term_number} {inv.academic_year}",
            detail=f"Status: {inv.status}",
            amount=inv.amount_due,
            extra={
                'invoice_id': inv.id,
                'amount_paid': str(_to_decimal(inv.amount_paid).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'results_blocked': bool(inv.results_blocked),
            },
        )
        if inv.results_blocked and not inv.hold_logs.exists():
            push_event(
                inv.results_blocked_at or inv.updated_at,
                'results_hold',
                f"Results held for Term {inv.term_number} {inv.academic_year}",
                detail=inv.results_block_reason or 'Outstanding fees',
                extra={'invoice_id': inv.id, 'action': 'held'},
            )

    for payment in Payment.objects.filter(student=student).select_related('deposit_batch', 'approved_by', 'received_by').order_by('-received_at')[:200]:
        detail = f"Method: {_payment_method_label(payment.method)} | Status: {payment.status}"
        if payment.receipt_number:
            detail += f" | Receipt: {payment.receipt_number}"
        push_event(
            payment.received_at,
            'payment',
            f"Payment recorded for Term {payment.term_number or '-'} {payment.academic_year or ''}".strip(),
            detail=detail,
            amount=payment.amount,
            extra={
                'payment_id': payment.id,
                'status': payment.status,
                'reference': payment.reference,
                'deposit_batch_id': payment.deposit_batch_id,
            },
        )
        if payment.deposit_batch_id:
            push_event(
                getattr(payment.deposit_batch, 'deposit_date', None) or payment.received_at,
                'deposit_batch',
                f"Assigned to deposit batch {payment.deposit_batch.name or ('#' + str(payment.deposit_batch_id))}",
                detail=f"Batch reference: {payment.deposit_batch.reference or '-'}",
                amount=payment.amount,
                extra={'payment_id': payment.id, 'deposit_batch_id': payment.deposit_batch_id},
            )

    for adj in InvoiceAdjustment.objects.filter(student=student).order_by('-created_at')[:120]:
        push_event(
            adj.created_at,
            'adjustment',
            f"Adjustment: {adj.title or adj.kind}",
            detail=f"Term {adj.term_number} {adj.academic_year} | {'Active' if adj.is_active else 'Inactive'}",
            amount=adj.amount,
            extra={'adjustment_id': adj.id, 'kind': adj.kind},
        )

    for plan in InstallmentPlan.objects.filter(student=student).prefetch_related('items').order_by('-created_at')[:40]:
        push_event(
            plan.created_at,
            'installment_plan',
            plan.title or 'Installment plan created',
            detail=f"Term {plan.term_number} {plan.academic_year} | Status: {plan.status}",
            amount=plan.total_amount,
            extra={'plan_id': plan.id, 'status': plan.status},
        )
        for item in plan.items.all().order_by('due_date', 'id'):
            push_event(
                item.due_date,
                'installment_due',
                item.label or f"Installment due",
                detail=f"Plan #{plan.id} | Status: {item.status}",
                amount=item.amount,
                extra={'plan_id': plan.id, 'installment_id': item.id, 'status': item.status},
            )

    for promise in FeePromise.objects.filter(student=student).select_related('installment').order_by('-created_at')[:80]:
        push_event(
            promise.created_at,
            'fee_promise',
            f"Fee promise created for {promise.promised_for}",
            detail=f"Status: {promise.status}",
            amount=promise.amount,
            extra={'promise_id': promise.id, 'status': promise.status},
        )
        if promise.fulfilled_at:
            push_event(
                promise.fulfilled_at,
                'fee_promise_kept',
                f"Fee promise kept",
                detail=f"Originally promised for {promise.promised_for}",
                amount=promise.amount,
                extra={'promise_id': promise.id},
            )

    for reminder in FeeReminderLog.objects.filter(student=student).order_by('-created_at')[:120]:
        push_event(
            reminder.created_at,
            'reminder',
            f"Reminder sent via {reminder.channel.upper()}",
            detail=f"Status: {reminder.status} | Recipient: {reminder.recipient or '-'}",
            extra={'reminder_id': reminder.id, 'channel': reminder.channel, 'status': reminder.status},
        )

    for hold_log in ResultsHoldLog.objects.filter(invoice__student=student).select_related('invoice', 'acted_by').order_by('-acted_at')[:120]:
        inv = hold_log.invoice
        push_event(
            hold_log.acted_at,
            'results_hold',
            f"Results {hold_log.action} for Term {inv.term_number} {inv.academic_year}",
            detail=hold_log.reason or hold_log.source or '',
            extra={'invoice_id': inv.id, 'action': hold_log.action, 'acted_by': getattr(hold_log.acted_by, 'username', None)},
        )

    events.sort(key=lambda x: x['event_at'], reverse=True)
    out = []
    for ev in events[:limit]:
        item = dict(ev)
        item['event_at'] = timezone.localtime(ev['event_at']).isoformat()
        out.append(item)
    return out

@ensure_csrf_cookie
def index(request):
    return render(request, 'school/index.html')

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def get_user_agent(request):
    return request.META.get('HTTP_USER_AGENT', 'Unknown')

def resolve_user_and_profile(identifier):
    ident = (identifier or '').strip()
    if not ident:
        return None, None

    user = None
    profile = None
    if '@' in ident:
        profile = (
            UserProfile.objects.select_related('user')
            .filter(Q(email_address__iexact=ident) | Q(user__email__iexact=ident))
            .first()
        )
        user = profile.user if profile else None
    elif ident.isdigit() and len(ident) >= 9:
        profile = UserProfile.objects.select_related('user').filter(phone_number=ident).first()
        user = profile.user if profile else None

    if not user:
        user = User.objects.filter(username__iexact=ident).first()
        if user and not profile:
            profile = UserProfile.objects.filter(user=user).first()

    return user, profile


def _clean_optional_email(value):
    email = (value or '').strip()
    if not email:
        return None
    validate_email(email)
    return email


def _guardian_contacts_for_student(student, parent_user=None):
    parent_user = parent_user or None
    parent_profile = None
    if parent_user is not None:
        parent_profile = UserProfile.objects.filter(user=parent_user).first()
    elif getattr(student, 'parent_phone', None):
        parent_profile = UserProfile.objects.filter(role='parent', phone_number=student.parent_phone).first()
        parent_user = parent_profile.user if parent_profile else None

    parent_email = None
    if parent_profile and parent_profile.email_address:
        parent_email = parent_profile.email_address
    elif parent_user and getattr(parent_user, 'email', None):
        parent_email = parent_user.email

    return {
        'parent_user': parent_user,
        'parent_profile': parent_profile,
        'parent_email': parent_email,
        'parent_phone': getattr(student, 'parent_phone', None),
        'parent_name': getattr(student, 'parent_name', None) or 'Parent/Guardian',
    }


def _build_portal_bundle_context(student, request, parent_email=None, parent_password=None, student_username=None, student_password=None):
    login_url = request.build_absolute_uri('/')
    return {
        'parent_name': student.parent_name or 'Parent/Guardian',
        'student_name': f'{student.first_name} {student.last_name}'.strip(),
        'student_id': student.student_id,
        'login_url': login_url,
        'phone_number': student.parent_phone,
        'email_address': parent_email,
        'password': parent_password or '(unchanged)',
        'student_username': student_username or student.student_id,
        'student_password': student_password or '(unchanged)',
        'password_reset_supported': True,
        'support_phone': student.parent_phone or '',
    }


def _build_staff_portal_bundle_context(*, request, display_name, role_label, username, password, email=None, phone=None):
    login_url = request.build_absolute_uri('/')
    return {
        'display_name': display_name or username,
        'role_label': role_label,
        'username': username,
        'password': password,
        'login_url': login_url,
        'email_address': email or '',
        'phone_number': phone or '',
        'password_reset_supported': True,
        'support_phone': phone or '',
    }


def _send_parent_portal_bundle(request, student, *, parent_email=None, parent_password=None, student_username=None, student_password=None, subject, mode_label):
    context = _build_portal_bundle_context(
        student,
        request,
        parent_email=parent_email,
        parent_password=parent_password,
        student_username=student_username,
        student_password=student_password,
    )
    context['mode_label'] = mode_label
    delivery = {
        'email_sent': False,
        'sms_sent': False,
        'email_attempted': False,
        'sms_attempted': False,
        **_email_transport_meta(),
        **_sms_transport_meta(),
    }

    email_enabled = bool(get_system_setting('send_credentials_email', True))
    if email_enabled and parent_email:
        delivery['email_attempted'] = True
        delivery['email_sent'] = bool(send_email(
            subject=subject,
            recipient_list=[parent_email],
            template_name='school/emails/parent_credentials_email.html',
            context=context,
        ))

    sms_enabled = bool(get_system_setting('send_credentials_sms', True))
    if sms_enabled and student.parent_phone:
        delivery['sms_attempted'] = True
        sms_lines = [
            f"Bitende Junior School {mode_label.lower()}:",
            f"Parent login phone: {student.parent_phone}",
        ]
        if parent_email:
            sms_lines.append(f"Parent login email: {parent_email}")
        sms_lines.append(
            f"Parent password: {parent_password}" if parent_password else "Parent password: unchanged"
        )
        if student_username:
            sms_lines.append(f"Student login: {student_username}")
            sms_lines.append(
                f"Student password: {student_password}" if student_password else "Student password: unchanged"
            )
        sms_lines.append("Reset password using the registered phone/email if forgotten.")
        sms_lines.append("Login: " + context['login_url'])
        try:
            delivery['sms_sent'] = bool(send_sms(student.parent_phone, " | ".join(sms_lines)))
        except Exception:
            delivery['sms_sent'] = False

    return context, delivery


def _send_staff_portal_bundle(
    request,
    *,
    display_name,
    role_label,
    username,
    password,
    email=None,
    phone=None,
    subject,
    mode_label,
):
    context = _build_staff_portal_bundle_context(
        request=request,
        display_name=display_name,
        role_label=role_label,
        username=username,
        password=password,
        email=email,
        phone=phone,
    )
    context['mode_label'] = mode_label
    delivery = {
        'email_sent': False,
        'sms_sent': False,
        'email_attempted': False,
        'sms_attempted': False,
        **_email_transport_meta(),
        **_sms_transport_meta(),
    }

    email_enabled = bool(get_system_setting('send_credentials_email', True))
    if email_enabled and email:
        delivery['email_attempted'] = True
        delivery['email_sent'] = bool(send_email(
            subject=subject,
            recipient_list=[email],
            template_name='school/emails/staff_credentials_email.html',
            context=context,
        ))

    sms_enabled = bool(get_system_setting('send_credentials_sms', True))
    if sms_enabled and phone:
        delivery['sms_attempted'] = True
        sms_lines = [
            f"Bitende Junior School {mode_label.lower()}:",
            f"Role: {role_label}",
            f"Username: {username}",
            f"Temporary password: {password}",
            f"Login: {context['login_url']}",
            "Change password after first login.",
            "Reset password using the registered phone/email if forgotten.",
        ]
        try:
            delivery['sms_sent'] = bool(send_sms(phone, " | ".join(sms_lines)))
        except Exception:
            delivery['sms_sent'] = False

    return context, delivery

# Helper for permission checks
def has_promotion_permission(user):
    try:
        r = user.profile.role
        return user.is_superuser or r == 'superadmin' or is_admin_role(r)
    except UserProfile.DoesNotExist:
        return user.is_superuser # Fallback for users without a profile

def has_term_management_permission(user):
    try:
        r = user.profile.role
        # Term management is reserved for super admin and the special admin roles.
        return user.is_superuser or r == 'superadmin' or is_admin_role(r)
    except UserProfile.DoesNotExist:
        return user.is_superuser # Fallback for users without a profile

def has_report_card_permission(user):
    try:
        r = user.profile.role
        return user.is_superuser or r == 'superadmin' or is_admin_role(r) or r in ['reception', 'teacher', 'parent', 'student']
    except UserProfile.DoesNotExist:
        return user.is_superuser

def has_grading_permission(user):
    try:
        r = user.profile.role
        return user.is_superuser or r in ['superadmin', 'director', 'headteacher', 'dos']
    except UserProfile.DoesNotExist:
        return user.is_superuser


def has_assessment_policy_permission(user):
    try:
        r = user.profile.role
        return user.is_superuser or r in ['superadmin', 'director', 'headteacher', 'dos']
    except UserProfile.DoesNotExist:
        return user.is_superuser


def _default_assessment_config():
    return {
        'selected_exam_type_ids': [],
        'weights': {},
        'promotion_threshold': 50,
        'remark_mode': 'grade_band',
    }


def _normalize_assessment_config(term, config):
    raw = config if isinstance(config, dict) else {}
    out = _default_assessment_config()
    exam_ids_raw = raw.get('selected_exam_type_ids') or []
    selected_ids = []
    if isinstance(exam_ids_raw, list):
        for item in exam_ids_raw:
            try:
                selected_ids.append(int(item))
            except Exception:
                continue
    selected_ids = list(dict.fromkeys(selected_ids))

    qs = ExamType.objects.filter(id__in=selected_ids, is_active=True)
    valid_ids = list(qs.values_list('id', flat=True))
    valid_id_set = set(valid_ids)

    weights_raw = raw.get('weights') or {}
    weights = {}
    if isinstance(weights_raw, dict):
        for key, value in weights_raw.items():
            try:
                exam_id = int(key)
                weight_value = float(value)
            except Exception:
                continue
            if exam_id in valid_id_set and weight_value >= 0:
                weights[str(exam_id)] = round(weight_value, 2)

    if not valid_ids:
        fallback = list(ExamType.objects.filter(is_active=True, exam_type__in=['midterm', 'endterm']).values_list('id', flat=True)[:2])
        if not fallback:
            fallback = list(ExamType.objects.filter(is_active=True).values_list('id', flat=True)[:3])
        valid_ids = fallback
        valid_id_set = set(valid_ids)
        if len(valid_ids) == 2:
            weights = {str(valid_ids[0]): 50.0, str(valid_ids[1]): 50.0}
        elif len(valid_ids) == 3:
            weights = {str(valid_ids[0]): 20.0, str(valid_ids[1]): 30.0, str(valid_ids[2]): 50.0}
        elif len(valid_ids) == 1:
            weights = {str(valid_ids[0]): 100.0}

    if valid_ids:
        missing = [exam_id for exam_id in valid_ids if str(exam_id) not in weights]
        if missing:
            remaining = max(0.0, 100.0 - sum(weights.values()))
            even_share = round((remaining / len(missing)) if missing else 0.0, 2)
            for exam_id in missing:
                weights[str(exam_id)] = even_share
        total_weight = sum(weights.values())
        if total_weight <= 0:
            even_share = round(100.0 / len(valid_ids), 2)
            weights = {str(exam_id): even_share for exam_id in valid_ids}
            total_weight = sum(weights.values())
        if total_weight and abs(total_weight - 100.0) > 0.01:
            factor = 100.0 / total_weight
            weights = {key: round(val * factor, 2) for key, val in weights.items()}
            total_weight = sum(weights.values())
            if valid_ids and abs(total_weight - 100.0) > 0.01:
                first_key = str(valid_ids[0])
                weights[first_key] = round(weights[first_key] + (100.0 - total_weight), 2)

    try:
        threshold = int(raw.get('promotion_threshold', 50))
    except Exception:
        threshold = 50
    threshold = max(0, min(100, threshold))

    remark_mode = str(raw.get('remark_mode') or 'grade_band').strip().lower()
    if remark_mode not in ['grade_band', 'average']:
        remark_mode = 'grade_band'

    out.update({
        'selected_exam_type_ids': valid_ids,
        'weights': weights,
        'promotion_threshold': threshold,
        'remark_mode': remark_mode,
    })
    return out

class SchoolClassViewSet(viewsets.ModelViewSet):
    queryset = SchoolClass.objects.all()
    serializer_class = SchoolClassSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def destroy(self, request, *args, **kwargs):
        if not IsSuperUser().has_permission(request, self):
            return Response({'detail': 'Only super admin can delete classes.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

class TeacherViewSet(viewsets.ModelViewSet):
    queryset = Teacher.objects.all()
    serializer_class = TeacherSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def destroy(self, request, *args, **kwargs):
        if not IsSuperUser().has_permission(request, self):
            return Response({'detail': 'Only super admin can delete teachers.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        phone = request.data.get('phone')
        email = request.data.get('email')
        subjects = request.data.get('subjects', [])
        assigned_class = request.data.get('assigned_class', None)
        employment_type = request.data.get('employment_type', 'Permanent')
        password_mode = (request.data.get('password_mode') or 'auto').strip().lower()
        manual_password = request.data.get('password')

        email = (str(email).strip() if email is not None else '')
        email = email or None

        # Email can be optional (SMS + print handover still works).
        if not all([first_name, last_name, phone]):
            return Response({'detail': 'Missing required teacher details.'}, status=status.HTTP_400_BAD_REQUEST)

        if password_mode not in ['auto', 'manual']:
            return Response({'detail': 'password_mode must be auto or manual.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Generate Employee ID
            id_counter, created = IDCounter.objects.get_or_create(entity_type='teacher', defaults={'current_count': 0})
            id_counter.current_count += 1
            id_counter.save()
            employee_id = f"T{id_counter.current_count:03d}" # T001, T002, etc.

            # Generate a readable username and keep it unique.
            username = _unique_username(
                _recommended_username(first_name=first_name, last_name=last_name, role='teacher'),
                fallback='teacher',
            )

            # Generate or accept a temporary password (never stored in plain text; only returned once).
            if password_mode == 'manual':
                if not manual_password:
                    return Response({'detail': 'Manual password is required.'}, status=status.HTTP_400_BAD_REQUEST)
                try:
                    validate_password(str(manual_password))
                except ValidationError as e:
                    return Response({'detail': 'Password does not meet security requirements.', 'errors': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
                temporary_password = str(manual_password)
            else:
                temporary_password = generate_random_password(12)

            # Create Django User
            user = User.objects.create_user(username=username, password=temporary_password, first_name=first_name, last_name=last_name, email=(email or ''))
            
            # Create UserProfile
            UserProfile.objects.create(
                user=user,
                role='teacher',
                avatar=(first_name[:2]).upper(),
                phone_number=phone,
                email_address=email,
                must_change_password=True,
            )

            # Create Teacher profile
            teacher_instance = Teacher.objects.create(
                user=user,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                email=email,
                subjects=subjects,
                assigned_class=assigned_class or '',
                employment_type=employment_type,
                employee_id=employee_id
            )

            # Send credentials (Email/SMS) and issue a short-lived print token for handover.
            login_url = request.build_absolute_uri('/') # Adjust as needed for your frontend login page
            _, delivery = _send_staff_portal_bundle(
                request,
                display_name=f'{first_name} {last_name}'.strip() or username,
                role_label='Teacher',
                username=username,
                password=temporary_password,
                email=email,
                phone=phone,
                subject='Your Bitende Junior School login details',
                mode_label='Teacher account setup',
            )
            if delivery['email_sent']:
                SecurityAuditLog.objects.create(user=request.user, event_type='CREDENTIALS_EMAIL_SENT', ip_address=get_client_ip(request), details=f'Teacher credentials email sent to {email} for {username}.')
            elif delivery['email_attempted']:
                SecurityAuditLog.objects.create(user=request.user, event_type='CREDENTIALS_EMAIL_FAILED', ip_address=get_client_ip(request), details=f'Failed to send teacher credentials email to {email} for {username}.')
            if delivery['sms_sent']:
                SecurityAuditLog.objects.create(user=request.user, event_type='CREDENTIALS_SMS_SENT', ip_address=get_client_ip(request), details=f'Teacher credentials SMS sent to {phone} for {username}.')
            elif delivery['sms_attempted']:
                SecurityAuditLog.objects.create(user=request.user, event_type='CREDENTIALS_SMS_FAILED', ip_address=get_client_ip(request), details=f'Failed to send teacher credentials SMS to {phone} for {username}.')

            token = _issue_handover_token('teacher', teacher_instance.id, { 
                'username': username, 
                'password': temporary_password, 
                'login_url': login_url, 
            }) 
 
            # Persistent print queue item for Reception (auto-wiped after printing or expiry). 
            try: 
                PrintQueueItem.objects.create( 
                    kind='teacher_credentials', 
                    status='queued', 
                    title=f"Teacher credentials: {first_name} {last_name}".strip(), 
                    teacher=teacher_instance, 
                    payload={'username': username, 'password': temporary_password, 'login_url': login_url}, 
                    is_sensitive=True, 
                    expires_at=timezone.now() + timedelta(hours=24), 
                    requested_by=request.user, 
                ) 
            except Exception as e: 
                SecurityAuditLog.objects.create( 
                    user=request.user, 
                    event_type='PRINTQ_ENQUEUE_FAILED', 
                    ip_address=get_client_ip(request), 
                    details=f'Failed to enqueue teacher credentials for teacher_id={teacher_instance.id}: {e}', 
                ) 

            SecurityAuditLog.objects.create(user=request.user, event_type='TEACHER_REGISTERED', ip_address=get_client_ip(request), details=f'Teacher {first_name} {last_name} ({employee_id}) registered by {request.user.username}.')
            try:
                notify_roles(
                    list(dict.fromkeys(['superadmin', 'reception'] + ADMIN_ROLE_LIST)),
                    category='system',
                    title='Teacher registered',
                    message=f'{first_name} {last_name} was added as a teacher account.',
                    link_page='teachers',
                    link_object_id=teacher_instance.id,
                    meta={'teacher_id': teacher_instance.id, 'username': username, 'employee_id': employee_id},
                    event_key=f'teacher_registered:{teacher_instance.id}',
                )
                notify_user(
                    user,
                    category='system',
                    title='Your teacher account is ready',
                    message='Your portal account has been created. Use the issued credentials to sign in and change your password on first login.',
                    link_page='dashboard',
                    link_object_id=teacher_instance.id,
                    meta={'username': username, 'employee_id': employee_id},
                    force=True,
                    event_key=f'teacher_account_ready:{teacher_instance.id}',
                )
            except Exception:
                pass
            data = dict(TeacherSerializer(teacher_instance).data)
            data['credentials'] = {
                'username': username,
                'temp_password': temporary_password,
                'email_address': email,
                'phone_number': phone,
            }
            data['delivery'] = delivery
            data['handover'] = {
                'token': token,
                'expires_minutes': 15,
                'print_teacher_credentials_url': f"/api/teachers/{teacher_instance.id}/print-credentials/?token={token}",
            }
            return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='print-credentials') 
    def print_credentials(self, request, pk=None): 
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role in ['reception']):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        teacher = self.get_object()
        token = request.query_params.get('token')
        payload = _get_handover_payload('teacher', teacher.id, token)
        if not payload:
            return Response({'detail': 'Handover token missing or expired. Re-generate credentials to print.'}, status=status.HTTP_400_BAD_REQUEST)
        pdf_buffer = generate_teacher_credential_pdf(teacher, payload.get('username'), payload.get('password'), payload.get('login_url')) 
        fn = f"teacher_credentials_{teacher.employee_id or teacher.id}.pdf" 
        return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf') 
 
    @action(detail=True, methods=['post'], url_path='assign-class-teacher') 
    def assign_class_teacher(self, request, pk=None): 
        """ 
        Promote a teacher to be Class Teacher for a class/section. DOS/Superadmin only. 
        """ 
        role = get_role(request.user) 
        if not (role == 'superadmin' or role == 'dos' or request.user.is_superuser): 
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN) 
 
        teacher = self.get_object() 
        class_id = (request.data or {}).get('class_id') 
        section = ((request.data or {}).get('section') or '').strip().upper() or None 
        if not str(class_id).isdigit(): 
            return Response({'detail': 'class_id is required.'}, status=status.HTTP_400_BAD_REQUEST) 
        school_class = SchoolClass.objects.filter(id=int(class_id)).first() 
        if not school_class: 
            return Response({'detail': 'Class not found.'}, status=status.HTTP_404_NOT_FOUND) 
 
        with transaction.atomic(): 
            # Ensure only one active class teacher per class/section. 
            Teacher.objects.filter( 
                class_teacher_class=school_class, 
                class_teacher_section=section, 
                is_class_teacher=True, 
            ).exclude(id=teacher.id).update(is_class_teacher=False, class_teacher_class=None, class_teacher_section=None) 
 
            teacher.class_teacher_class = school_class 
            teacher.class_teacher_section = section 
            teacher.is_class_teacher = True 
            teacher.save(update_fields=['class_teacher_class', 'class_teacher_section', 'is_class_teacher']) 
 
            # Keep the legacy SchoolClass.teacher_a string in sync (best-effort). 
            try: 
                school_class.teacher_a = f"{teacher.first_name} {teacher.last_name}".strip() 
                school_class.save(update_fields=['teacher_a']) 
            except Exception: 
                pass 
 
        SecurityAuditLog.objects.create( 
            user=request.user, 
            event_type='CLASS_TEACHER_ASSIGNED', 
            ip_address=get_client_ip(request), 
            details=f'Assigned teacher_id={teacher.id} as class teacher for class_id={school_class.id} section={(section or "(none)")}.', 
        ) 
        return Response(TeacherSerializer(teacher).data) 
 
    @action(detail=True, methods=['post'], url_path='unassign-class-teacher') 
    def unassign_class_teacher(self, request, pk=None): 
        role = get_role(request.user) 
        if not (role == 'superadmin' or role == 'dos' or request.user.is_superuser): 
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN) 
        teacher = self.get_object() 
        teacher.is_class_teacher = False 
        teacher.class_teacher_class = None 
        teacher.class_teacher_section = None 
        teacher.save(update_fields=['is_class_teacher', 'class_teacher_class', 'class_teacher_section']) 
        SecurityAuditLog.objects.create( 
            user=request.user, 
            event_type='CLASS_TEACHER_UNASSIGNED', 
            ip_address=get_client_ip(request), 
            details=f'Unassigned teacher_id={teacher.id} from class teacher.', 
        ) 
        return Response(TeacherSerializer(teacher).data) 
 
    @action(detail=False, methods=['get'], url_path='class-teacher/overview') 
    def class_teacher_overview(self, request): 
        """Teacher-only: overview for the class teacher's assigned class.""" 
        if get_role(request.user) != 'teacher': 
            return Response({'detail': 'Only teachers can access this.'}, status=status.HTTP_403_FORBIDDEN) 
        try: 
            t = request.user.teacher_profile 
        except Exception: 
            return Response({'detail': 'Teacher profile not found.'}, status=status.HTTP_404_NOT_FOUND) 
        if not getattr(t, 'is_class_teacher', False) or not getattr(t, 'class_teacher_class_id', None): 
            return Response({'detail': 'You are not assigned as a class teacher.'}, status=status.HTTP_403_FORBIDDEN) 
 
        school_class = t.class_teacher_class 
        section = (t.class_teacher_section or '').strip().upper() 
 
        active_term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number').first() 
        if not active_term: 
            return Response({'detail': 'No active term.'}, status=status.HTTP_400_BAD_REQUEST) 
 
        qs = Student.objects.filter(current_class=school_class, status__in=['active', 'repeating']) 
        if section: 
            qs = qs.filter(section__iexact=section) 
        students = list(qs.order_by('first_name', 'last_name')) 
        ids = [s.id for s in students] 
 
        marks = Mark.objects.filter(student_id__in=ids, term=active_term.term_number, year=active_term.academic_year) 
        avgs = marks.values('student_id').annotate(avg_score=Avg('score')) 
        avg_map = {a['student_id']: float(a['avg_score'] or 0) for a in avgs} 
        class_avg = float(sum(avg_map.values()) / max(1, len(avg_map))) if avg_map else 0.0 
 
        # Attendance trend (last 7 days). 
        trend = [] 
        today = timezone.localdate() 
        for i in range(6, -1, -1): 
            d = today - timedelta(days=i) 
            day_qs = Attendance.objects.filter(student_id__in=ids, date=d) 
            present = day_qs.filter(status__iexact='Present').count() 
            total = day_qs.count() 
            trend.append({ 
                'date': d.isoformat(), 
                'present': int(present), 
                'marked': int(total), 
            }) 
 
        # Top/bottom performers. 
        ranked = sorted([ 
            { 
                'student_id': s.id, 
                'student_name': f"{s.first_name} {s.last_name}".strip(), 
                'avg': float(avg_map.get(s.id, 0.0)), 
            } for s in students 
        ], key=lambda x: x['avg'], reverse=True) 
 
        return Response({ 
            'class': { 
                'id': school_class.id, 
                'level': school_class.level, 
                'section': section, 
            }, 
            'term': { 
                'academic_year': active_term.academic_year, 
                'term_number': active_term.term_number, 
                'start_date': str(active_term.start_date), 
                'end_date': str(active_term.end_date), 
            }, 
            'stats': { 
                'students': len(students), 
                'class_average': class_avg, 
            }, 
            'attendance_trend': trend, 
            'top_students': ranked[:5], 
            'bottom_students': list(reversed(ranked[-5:])) if len(ranked) >= 5 else sorted(ranked, key=lambda x: x['avg'])[:5], 
        }) 

    def update(self, request, *args, **kwargs):
        """
        Keep the linked Django User/UserProfile in sync when teacher details change.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        teacher = serializer.instance
        if teacher.user:
            u = teacher.user
            u.first_name = teacher.first_name
            u.last_name = teacher.last_name
            if teacher.email:
                u.email = teacher.email
            u.save()
            try:
                p = u.profile
                p.phone_number = teacher.phone
                p.email_address = teacher.email
                p.avatar = (teacher.first_name[:2] if teacher.first_name else u.username[:2]).upper()
                p.save()
            except Exception:
                pass

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TEACHER_UPDATED',
            ip_address=get_client_ip(request),
            details=f'Teacher {teacher.employee_id} updated by {request.user.username}.',
        )
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.select_related('current_class', 'previous_class').all().order_by('current_class__level', 'section', 'student_id')
    serializer_class = StudentSerializer

    def _can_edit_student_profiles(self, user) -> bool:
        role = get_role(user)
        return bool(user and user.is_authenticated and (role == 'superadmin' or is_admin_role(role)))

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def destroy(self, request, *args, **kwargs):
        if not IsSuperUser().has_permission(request, self):
            return Response({'detail': 'Only super admin can delete students.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'], url_path='print-admission-letter')
    def print_admission_letter(self, request, pk=None):
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role in ['reception']):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        student = self.get_object()
        token = request.query_params.get('token')
        payload = _get_handover_payload('student', student.id, token)
        if not payload:
            return Response({'detail': 'Handover token missing or expired. Re-generate credentials to print.'}, status=status.HTTP_400_BAD_REQUEST)
        tmpl = None
        try:
            v = SystemSetting.objects.filter(key='admission_letter_template').values_list('value', flat=True).first()
            if isinstance(v, dict):
                tmpl = v.get('text') or None
            elif isinstance(v, str):
                tmpl = v or None
        except Exception:
            tmpl = None
        pdf_buffer = generate_admission_letter_pdf(
            student,
            payload.get('login_url') or request.build_absolute_uri('/'),
            parent_username=payload.get('parent_username'),
            parent_password=payload.get('parent_password'),
            student_username=payload.get('student_username'),
            student_password=payload.get('student_password'),
            template_text=tmpl,
        )
        fn = f"admission_letter_{student.student_id}.pdf"
        return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

    @action(detail=True, methods=['get'], url_path='print-credentials', permission_classes=[permissions.IsAuthenticated])
    def print_credentials(self, request, pk=None):
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role in ['reception']):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        student = self.get_object()
        token = request.query_params.get('token')
        payload = _get_handover_payload('student', student.id, token)
        if not payload:
            return Response({'detail': 'Handover token missing or expired. Re-generate credentials to print.'}, status=status.HTTP_400_BAD_REQUEST)
        login_url = payload.get('login_url') or request.build_absolute_uri('/')
        if not (payload.get('parent_username') or payload.get('student_username')):
            return Response({'detail': 'No credentials available in handover token.'}, status=status.HTTP_400_BAD_REQUEST)

        pdf_buffer = generate_family_credential_pdf(
            parent_name=student.parent_name or 'Parent/Guardian',
            student_name=f"{student.first_name} {student.last_name}",
            student_id=student.student_id,
            login_url=login_url,
            parent_phone=payload.get('parent_username') or student.parent_phone,
            parent_email=payload.get('parent_email'),
            parent_password=payload.get('parent_password'),
            student_username=payload.get('student_username'),
            student_password=payload.get('student_password'),
        )
        fn = f"family_credentials_{student.student_id}.pdf"
        return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)

        if role == 'parent':
            phone = getattr(getattr(self.request.user, 'profile', None), 'phone_number', None)
            linked_ids = list(StudentGuardianLink.objects.filter(parent_user=self.request.user, is_active=True).values_list('student_id', flat=True))
            if not phone and not linked_ids:
                return qs.none()
            q = Q(id__in=linked_ids)
            if phone:
                q = q | Q(parent_phone=phone) | Q(parent_phone2=phone)
            return qs.filter(q)

        if role == 'teacher':
            lvl, sec = get_teacher_scope(self.request.user)
            if not lvl or not sec:
                return qs.none()
            return qs.filter(current_class__level=lvl, section=sec)

        if role == 'student':
            stu, _, _ = get_student_scope(self.request.user)
            if not stu:
                return qs.none()
            qs = qs.filter(id=stu.id)

        q = (self.request.query_params.get('q') or '').strip()
        class_id = (self.request.query_params.get('class_id') or '').strip()
        class_level = (self.request.query_params.get('class_level') or '').strip()
        section = (self.request.query_params.get('section') or '').strip()
        status_v = (self.request.query_params.get('status') or '').strip()

        if q:
            qs = qs.filter(
                Q(student_id__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(parent_name__icontains=q)
                | Q(parent_phone__icontains=q)
                | Q(parent_phone2__icontains=q)
            )
        if class_id.isdigit():
            qs = qs.filter(current_class_id=int(class_id))
        if class_level:
            qs = qs.filter(current_class__level__iexact=class_level)
        if section:
            qs = qs.filter(section__iexact=section)
        if status_v:
            qs = qs.filter(status__iexact=status_v)
        return qs

    @action(detail=False, methods=['get'], url_path='parent-candidates')
    def parent_candidates(self, request):
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role == 'reception'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response([])
        profiles = (
            UserProfile.objects.select_related('user')
            .filter(role='parent')
            .filter(
                Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(phone_number__icontains=q)
                | Q(email_address__icontains=q)
                | Q(user__username__icontains=q)
            )
            .order_by('user__first_name', 'user__last_name')[:15]
        )
        rows = []
        for p in profiles:
            user = p.user
            linked = list(
                StudentGuardianLink.objects.filter(parent_user=user, is_active=True)
                .select_related('student')
                .values_list('student__student_id', flat=True)[:8]
            )
            rows.append({
                'id': p.id,
                'user_id': user.id,
                'username': user.username,
                'name': f"{user.first_name} {user.last_name}".strip(),
                'phone_number': p.phone_number,
                'email_address': p.email_address or user.email,
                'linked_students': linked,
            })
        return Response(rows)

    @action(detail=False, methods=['get'], url_path='mine')
    def mine(self, request):
        if get_role(request.user) != 'parent':
            return Response({'detail': 'Only parent users can access this.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='history')
    def history(self, request, pk=None):
        """
        Student "full history" for dashboards:
        - payments
        - marks
        - attendance
        Access is constrained by get_queryset()/permissions.
        """
        student = self.get_object()

        # Results hold: parents/students can be blocked from seeing marks/report data for a term due to fees.
        role = get_role(request.user)
        if role in ['parent', 'student']:
            active_term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number').first()
            if active_term:
                inv = Invoice.objects.filter(student=student, academic_year=active_term.academic_year, term_number=active_term.term_number).first()
                if inv and getattr(inv, 'results_blocked', False):
                    # Still return payments/attendance so parent can see balances and make payment.
                    payments = Payment.objects.filter(student=student).order_by('-received_at')[:60]
                    attendance = Attendance.objects.filter(student=student).order_by('-date')[:90]
                    return Response({
                        'student': StudentSerializer(student).data,
                        'payments': PaymentSerializer(payments, many=True).data,
                        'marks': [],
                        'attendance': AttendanceSerializer(attendance, many=True).data,
                        'results_blocked': True,
                        'results_block_reason': inv.results_block_reason or 'Results are temporarily unavailable.',
                        'term': {'academic_year': active_term.academic_year, 'term_number': active_term.term_number},
                    }, status=status.HTTP_200_OK)

        payments = Payment.objects.filter(student=student).order_by('-received_at')[:60]
        marks = Mark.objects.filter(student=student).order_by('-year', '-term', 'subject')[:200]
        attendance = Attendance.objects.filter(student=student).order_by('-date')[:90]
        return Response({
            'student': StudentSerializer(student).data,
            'payments': PaymentSerializer(payments, many=True).data,
            'marks': MarkSerializer(marks, many=True).data,
            'attendance': AttendanceSerializer(attendance, many=True).data,
        })

    @action(detail=True, methods=['get'], url_path='finance-timeline')
    def finance_timeline(self, request, pk=None):
        student = self.get_object()
        pairs = InstallmentPlan.objects.filter(student=student).values_list('academic_year', 'term_number').distinct()
        for year_v, term_v in pairs:
            _refresh_finance_commitments(student, year_v, term_v)

        plans = InstallmentPlan.objects.filter(student=student).prefetch_related('items').order_by('-created_at')[:40]
        promises = FeePromise.objects.filter(student=student).select_related('installment').order_by('-created_at')[:80]
        reminders = FeeReminderLog.objects.filter(student=student).order_by('-created_at')[:120]
        invoices = Invoice.objects.filter(student=student).order_by('-academic_year', '-term_number')[:20]

        return Response({
            'student': StudentSerializer(student).data,
            'plans': InstallmentPlanSerializer(plans, many=True).data,
            'promises': FeePromiseSerializer(promises, many=True).data,
            'reminders': FeeReminderLogSerializer(reminders, many=True).data,
            'invoices': InvoiceSerializer(invoices, many=True).data,
            'timeline': _build_student_finance_timeline(student),
        })

    def create(self, request, *args, **kwargs):
        if not self._can_edit_student_profiles(request.user):
            return Response({'detail': 'Only administrators can create or edit student profiles.'}, status=status.HTTP_403_FORBIDDEN)
        parent_name = request.data.get('parent_name')
        parent_relationship = request.data.get('parent_relationship')
        parent_phone = request.data.get('parent_phone')
        existing_parent_user_id = (request.data.get('existing_parent_user') or '').strip()
        try:
            parent_email = _clean_optional_email(request.data.get('parent_email'))
        except ValidationError:
            return Response({'detail': 'Enter a valid parent email address.'}, status=status.HTTP_400_BAD_REQUEST)
        parent_password_mode = (request.data.get('parent_password_mode') or 'auto').strip().lower()
        parent_manual_password = request.data.get('parent_password')
        student_password_mode = (request.data.get('student_password_mode') or 'auto').strip().lower()
        student_manual_password = request.data.get('student_password')
        photo_url = request.data.get('photo_url')
        student_data = request.data.copy()
        # `parent_email` is used for creating/updating the parent portal profile, but Student has no such field.
        student_data.pop('parent_email', None)
        student_data.pop('parent_password_mode', None)
        student_data.pop('parent_password', None)
        student_data.pop('student_password_mode', None)
        student_data.pop('student_password', None)
        student_data.pop('existing_parent_user', None)
        student_data.pop('photo_url', None)

        if parent_password_mode not in ['auto', 'manual']:
            return Response({'detail': 'parent_password_mode must be auto or manual.'}, status=status.HTTP_400_BAD_REQUEST)
        if student_password_mode not in ['auto', 'manual']:
            return Response({'detail': 'student_password_mode must be auto or manual.'}, status=status.HTTP_400_BAD_REQUEST)
        if parent_email:
            email_owner = UserProfile.objects.filter(email_address__iexact=parent_email).exclude(phone_number=parent_phone).first()
            if email_owner:
                return Response({'detail': 'That parent email is already linked to another portal account.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Generate Student ID (BJS-YYYY-XXXX)
            current_year = date.today().year
            id_counter, created = IDCounter.objects.get_or_create(entity_type='student', defaults={'current_count': 0})
            id_counter.current_count += 1
            id_counter.save()
            student_id = f"BJS-{current_year}-{id_counter.current_count:04d}"
            student_data['student_id'] = student_id

            # Create/Get Parent User and UserProfile
            parent_username = parent_phone
            temporary_password = None
            parent_user_profile = None
            if existing_parent_user_id.isdigit():
                parent_user_profile = UserProfile.objects.filter(id=int(existing_parent_user_id), role='parent').first()
                if not parent_user_profile:
                    return Response({'detail': 'Selected parent account was not found.'}, status=status.HTTP_400_BAD_REQUEST)
                parent_user = parent_user_profile.user
                parent_phone = parent_phone or parent_user_profile.phone_number or parent_user.username
                parent_username = parent_user.username
                if not parent_email:
                    parent_email = parent_user_profile.email_address or parent_user.email
            elif parent_phone:
                parent_user_profile = UserProfile.objects.filter(phone_number=parent_phone).first()

            if not parent_user_profile:
                parent_user = User.objects.filter(username=parent_username).first()
                if not parent_user:
                    if parent_password_mode == 'manual':
                        if not parent_manual_password:
                            return Response({'detail': 'Manual parent password is required.'}, status=status.HTTP_400_BAD_REQUEST)
                        try:
                            validate_password(str(parent_manual_password))
                        except ValidationError as e:
                            return Response({'detail': 'Parent password does not meet security requirements.', 'errors': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
                        temporary_password = str(parent_manual_password)
                    else:
                        temporary_password = generate_random_password(12)
                    parent_user = User.objects.create_user(
                        username=parent_username,
                        password=temporary_password,
                        first_name=parent_name,
                        email=parent_email or '',
                    )

                if parent_email and parent_user.email != parent_email:
                    parent_user.email = parent_email
                    parent_user.save(update_fields=['email'])

                parent_user_profile = UserProfile.objects.create(
                    user=parent_user,
                    role='parent',
                    avatar=(parent_name[:2]).upper(),
                    phone_number=parent_phone,
                    email_address=parent_email,
                    must_change_password=True,
                )
                SecurityAuditLog.objects.create(user=parent_user, event_type='PARENT_ACCOUNT_CREATED', ip_address=get_client_ip(request), details=f'Parent account {parent_username} created during student registration.')
            else:
                parent_user = parent_user_profile.user
                # If parent user exists, ensure profile is updated with new student's parent info if needed
                update_fields = []
                if parent_email and parent_user_profile.email_address != parent_email:
                    parent_user_profile.email_address = parent_email
                    update_fields.append('email_address')
                if parent_phone and parent_user_profile.phone_number != parent_phone:
                    parent_user_profile.phone_number = parent_phone
                    update_fields.append('phone_number')
                if update_fields:
                    parent_user_profile.save(update_fields=update_fields)
                if parent_email and parent_user.email != parent_email:
                    parent_user.email = parent_email
                    parent_user.save(update_fields=['email'])
                # temporary_password remains None if account already exists
            # Create Student instance
            serializer = self.get_serializer(data=student_data)
            serializer.is_valid(raise_exception=True)
            student_instance = serializer.save(student_id=student_id)
            if photo_url is not None:
                try:
                    _apply_uploaded_media_to_field(student_instance, 'photo', photo_url)
                except ValidationError as e:
                    return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

            # Always create an explicit guardian link for the parent account to this student.
            # This makes "one parent account, many children" work even if phone numbers change later.
            try:
                StudentGuardianLink.objects.get_or_create(
                    parent_user=parent_user,
                    student=student_instance,
                    defaults={'relationship': (parent_relationship or 'parent'), 'is_active': True, 'created_by': request.user},
                )
            except Exception:
                pass

            # Deliver parent credentials if new parent account and no email (PDF handover).
            # If email exists, we send a combined parent+student credential message later (after student account is ensured).
            if temporary_password and not parent_email:
                login_url = request.build_absolute_uri('/') # Adjust as needed
                pdf_buffer = generate_parent_credential_pdf(
                    parent_name=parent_name,
                    student_name=f'{student_instance.first_name} {student_instance.last_name}',
                    student_id=student_instance.student_id,
                    login_url=login_url,
                    phone_number=parent_phone,
                    password=temporary_password
                )
                # In a real application, you might save this PDF or return it as a download.
                # For now, we'll just log that it was generated.
                logger.info(f"Parent credential PDF generated for {parent_name} (student: {student_instance.first_name} {student_instance.last_name})")

            # Create/Get Student portal account (username = student_id)
            student_username = student_instance.student_id
            student_temp_password = None
            student_user = User.objects.filter(username=student_username).first()
            if not student_user:
                if student_password_mode == 'manual':
                    if not student_manual_password:
                        return Response({'detail': 'Manual student password is required.'}, status=status.HTTP_400_BAD_REQUEST)
                    try:
                        validate_password(str(student_manual_password))
                    except ValidationError as e:
                        return Response({'detail': 'Student password does not meet security requirements.', 'errors': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
                    student_temp_password = str(student_manual_password)
                else:
                    student_temp_password = generate_random_password(12)
                student_user = User.objects.create_user(
                    username=student_username,
                    password=student_temp_password,
                    first_name=student_instance.first_name,
                    last_name=student_instance.last_name,
                )
                UserProfile.objects.create(
                    user=student_user,
                    role='student',
                    avatar=((student_instance.first_name[:1] + student_instance.last_name[:1]).upper() if student_instance.first_name and student_instance.last_name else student_username[:2].upper()),
                    must_change_password=True,
                )
                SecurityAuditLog.objects.create(
                    user=student_user,
                    event_type='STUDENT_ACCOUNT_CREATED',
                    ip_address=get_client_ip(request),
                    details=f'Student portal account created for {student_instance.student_id}.',
                )

            login_url = request.build_absolute_uri('/')
            _, delivery = _send_parent_portal_bundle(
                request,
                student_instance,
                parent_email=parent_email,
                parent_password=temporary_password,
                student_username=student_username,
                student_password=student_temp_password,
                subject='Bitende Junior School registration confirmation and portal access',
                mode_label='Registration confirmation',
            )
            if delivery['email_sent']:
                SecurityAuditLog.objects.create(
                    user=request.user,
                    event_type='CREDENTIALS_EMAIL_SENT',
                    ip_address=get_client_ip(request),
                    details=f'Credentials email sent to {parent_email} for {student_instance.student_id}.',
                )
            elif parent_email and bool(get_system_setting('send_credentials_email', True)):
                SecurityAuditLog.objects.create(
                    user=request.user,
                    event_type='CREDENTIALS_EMAIL_FAILED',
                    ip_address=get_client_ip(request),
                    details=f'Failed to send credentials email to {parent_email} for {student_instance.student_id}.',
                )
            if delivery['sms_sent']:
                SecurityAuditLog.objects.create(
                    user=request.user,
                    event_type='CREDENTIALS_SMS_SENT',
                    ip_address=get_client_ip(request),
                    details=f'Credentials SMS sent to {student_instance.parent_phone} for {student_instance.student_id}.',
                )
            elif student_instance.parent_phone and bool(get_system_setting('send_credentials_sms', True)):
                SecurityAuditLog.objects.create(
                    user=request.user,
                    event_type='CREDENTIALS_SMS_FAILED',
                    ip_address=get_client_ip(request),
                    details=f'Failed to send credentials SMS to {student_instance.parent_phone} for {student_instance.student_id}.',
                )
            
            SecurityAuditLog.objects.create(user=request.user, event_type='STUDENT_REGISTERED', ip_address=get_client_ip(request), details=f'Student {student_instance.first_name} {student_instance.last_name} ({student_instance.student_id}) registered by {request.user.username}.')
            try:
                notify_roles(
                    list(dict.fromkeys(['superadmin', 'reception', 'bursar'] + ADMIN_ROLE_LIST)),
                    category='system',
                    title='Student registered',
                    message=f'{student_instance.first_name} {student_instance.last_name} joined {getattr(getattr(student_instance, "current_class", None), "level", "school")} {student_instance.section}.',
                    link_page='students',
                    link_object_id=student_instance.id,
                    student=student_instance,
                    school_class=getattr(student_instance, 'current_class', None),
                    meta={'student_id': student_instance.id, 'student_system_id': student_instance.student_id},
                    event_key=f'student_registered:{student_instance.id}',
                )
                notify_user(
                    parent_user,
                    category='system',
                    title='Student registration complete',
                    message=f'{student_instance.first_name} {student_instance.last_name} has been linked to your parent portal.',
                    link_page='profile',
                    link_object_id=student_instance.id,
                    student=student_instance,
                    school_class=getattr(student_instance, 'current_class', None),
                    meta={'student_system_id': student_instance.student_id},
                    force=True,
                    event_key=f'parent_student_registered:{student_instance.id}:{parent_user.id}',
                )
                notify_user(
                    student_user,
                    category='system',
                    title='Your student portal is ready',
                    message='Your school portal account has been created. Sign in using the issued credentials and change your password after first login.',
                    link_page='dashboard',
                    link_object_id=student_instance.id,
                    student=student_instance,
                    school_class=getattr(student_instance, 'current_class', None),
                    meta={'student_system_id': student_instance.student_id},
                    force=True,
                    event_key=f'student_portal_ready:{student_instance.id}',
                )
            except Exception:
                pass
            headers = self.get_success_headers(serializer.data)
            data = dict(serializer.data)
            # One-time display for admin/reception to hand over credentials if email isn't used.
            data['credentials'] = {
                'parent_username': parent_username,
                'parent_email': parent_email,
                'parent_temp_password': temporary_password,
                'student_username': student_username,
                'student_temp_password': student_temp_password,
            }
            # Short-lived token to allow printing admission letter / credential sheets with passwords.
            token = _issue_handover_token('student', student_instance.id, { 
                'login_url': login_url, 
                'parent_username': parent_username, 
                'parent_email': parent_email,
                'parent_password': temporary_password, 
                'student_username': student_username, 
                'student_password': student_temp_password, 
            }) 
            data['handover'] = { 
                'token': token, 
                'expires_minutes': 15, 
                'print_admission_letter_url': f"/api/students/{student_instance.id}/print-admission-letter/?token={token}", 
                'print_credentials_url': f"/api/students/{student_instance.id}/print-credentials/?token={token}", 
            } 
 
            # Persistent print queue items for Reception (auto-wiped after printing or expiry). 
            try: 
                expires_at = timezone.now() + timedelta(hours=24) 
                base_payload = { 
                    'login_url': login_url, 
                    'parent_username': parent_username, 
                    'parent_email': parent_email,
                    'parent_password': temporary_password, 
                    'student_username': student_username, 
                    'student_password': student_temp_password, 
                } 
                PrintQueueItem.objects.create( 
                    kind='admission_letter', 
                    status='queued', 
                    title=f"Admission letter: {student_instance.first_name} {student_instance.last_name}".strip(), 
                    student=student_instance, 
                    payload=base_payload, 
                    is_sensitive=True, 
                    expires_at=expires_at, 
                    requested_by=request.user, 
                ) 
                PrintQueueItem.objects.create( 
                    kind='parent_credentials', 
                    status='queued', 
                    title=f"Parent credentials: {student_instance.first_name} {student_instance.last_name}".strip(), 
                    student=student_instance, 
                    payload=base_payload, 
                    is_sensitive=True, 
                    expires_at=expires_at, 
                    requested_by=request.user, 
                ) 
                PrintQueueItem.objects.create( 
                    kind='student_credentials', 
                    status='queued', 
                    title=f"Student credentials: {student_instance.first_name} {student_instance.last_name}".strip(), 
                    student=student_instance, 
                    payload=base_payload, 
                    is_sensitive=True, 
                    expires_at=expires_at, 
                    requested_by=request.user, 
                ) 
            except Exception as e: 
                SecurityAuditLog.objects.create( 
                    user=request.user, 
                    event_type='PRINTQ_ENQUEUE_FAILED', 
                    ip_address=get_client_ip(request), 
                    details=f'Failed to enqueue student prints for student_id={student_instance.id}: {e}', 
                ) 
            data['delivery'] = delivery
            return Response(data, status=status.HTTP_201_CREATED, headers=headers) 

    @action(detail=True, methods=['post'], url_path='reset-portals')
    def reset_portals(self, request, pk=None):
        """
        Resets parent and/or student portal passwords and returns new temporary credentials.
        Only superadmin, headteacher, or DOS can do this.
        """
        if not can_manage_passwords(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        student = self.get_object()
        reset_parent = bool(request.data.get('reset_parent', True))
        reset_student = bool(request.data.get('reset_student', True))

        parent_username = student.parent_phone
        parent_user = None
        try:
            parent_profile = UserProfile.objects.filter(phone_number=student.parent_phone, role='parent').first()
            parent_user = parent_profile.user if parent_profile else User.objects.filter(username=parent_username).first()
        except Exception:
            parent_user = User.objects.filter(username=parent_username).first()

        student_username = student.student_id
        student_user = User.objects.filter(username=student_username).first()

        out = {
            'parent_username': parent_username,
            'parent_email': None,
            'student_username': student_username,
            'parent_temp_password': None,
            'student_temp_password': None,
        }

        with transaction.atomic():
            if reset_parent and parent_user:
                pw = generate_random_password()
                parent_user.set_password(pw)
                parent_user.save()
                out['parent_temp_password'] = pw
                try:
                    pp = parent_user.profile
                    pp.must_change_password = True
                    pp.save(update_fields=['must_change_password'])
                except Exception:
                    pass
                SecurityAuditLog.objects.create(user=request.user, event_type='PARENT_PASSWORD_RESET', ip_address=get_client_ip(request), details=f'Parent password reset for {parent_username}.')

            if reset_student:
                if not student_user:
                    pw = generate_random_password()
                    student_user = User.objects.create_user(username=student_username, password=pw, first_name=student.first_name, last_name=student.last_name)
                    UserProfile.objects.create(user=student_user, role='student', avatar=((student.first_name[:1] + student.last_name[:1]).upper() if student.first_name and student.last_name else student_username[:2].upper()))
                    out['student_temp_password'] = pw
                    SecurityAuditLog.objects.create(user=request.user, event_type='STUDENT_ACCOUNT_CREATED', ip_address=get_client_ip(request), details=f'Student account created during reset for {student_username}.')
                else:
                    pw = generate_random_password()
                    student_user.set_password(pw)
                    student_user.save()
                    out['student_temp_password'] = pw
                    try:
                        sp = student_user.profile
                        sp.must_change_password = True
                        sp.save(update_fields=['must_change_password'])
                    except Exception:
                        pass
                    SecurityAuditLog.objects.create(user=request.user, event_type='STUDENT_PASSWORD_RESET', ip_address=get_client_ip(request), details=f'Student password reset for {student_username}.')

        # Optional email to parent if available.
        parent_email = None
        try:
            pp = UserProfile.objects.filter(phone_number=student.parent_phone, role='parent').first()
            parent_email = pp.email_address if pp else None
        except Exception:
            parent_email = None
        out['parent_email'] = parent_email

        _, delivery = _send_parent_portal_bundle(
            request,
            student,
            parent_email=parent_email,
            parent_password=out['parent_temp_password'],
            student_username=out['student_username'],
            student_password=out['student_temp_password'],
            subject='Bitende Junior School portal password reset',
            mode_label='Password reset',
        )
        out['delivery'] = delivery
        if delivery['email_sent']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_EMAIL_SENT',
                ip_address=get_client_ip(request),
                details=f'Password reset email sent to {parent_email} for {student.student_id}.',
            )
        elif parent_email and bool(get_system_setting('send_credentials_email', True)):
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_EMAIL_FAILED',
                ip_address=get_client_ip(request),
                details=f'Failed to send reset email to {parent_email} for {student.student_id}.',
            )
        if delivery['sms_sent']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_SMS_SENT',
                ip_address=get_client_ip(request),
                details=f'Password reset SMS sent to {student.parent_phone} for {student.student_id}.',
            )
        elif student.parent_phone and bool(get_system_setting('send_credentials_sms', True)):
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_SMS_FAILED',
                ip_address=get_client_ip(request),
                details=f'Failed to send reset SMS to {student.parent_phone} for {student.student_id}.',
            )
 
        # Persistent print queue items for Reception (only when a temp password was generated). 
        try: 
            if out.get('parent_temp_password') or out.get('student_temp_password'): 
                login_url = request.build_absolute_uri('/') 
                payload = { 
                    'login_url': login_url, 
                    'parent_username': out.get('parent_username'), 
                    'parent_email': parent_email,
                    'parent_password': out.get('parent_temp_password'), 
                    'student_username': out.get('student_username'), 
                    'student_password': out.get('student_temp_password'), 
                } 
                expires_at = timezone.now() + timedelta(hours=24) 
                ids = [] 
                ids.append(PrintQueueItem.objects.create( 
                    kind='parent_credentials', 
                    status='queued', 
                    title=f"Parent credentials reset: {student.first_name} {student.last_name}".strip(), 
                    student=student, 
                    payload=payload, 
                    is_sensitive=True, 
                    expires_at=expires_at, 
                    requested_by=request.user, 
                ).id) 
                ids.append(PrintQueueItem.objects.create( 
                    kind='student_credentials', 
                    status='queued', 
                    title=f"Student credentials reset: {student.first_name} {student.last_name}".strip(), 
                    student=student, 
                    payload=payload, 
                    is_sensitive=True, 
                    expires_at=expires_at, 
                    requested_by=request.user, 
                ).id) 
                out['print_queue_ids'] = ids 
        except Exception as e: 
            SecurityAuditLog.objects.create( 
                user=request.user, 
                event_type='PRINTQ_ENQUEUE_FAILED', 
                ip_address=get_client_ip(request), 
                details=f'Failed to enqueue reset credentials prints for student_id={student.id}: {e}', 
            ) 
 
        return Response(out, status=status.HTTP_200_OK) 

    @action(detail=True, methods=['post'], url_path='send-fee-reminder')
    def send_fee_reminder(self, request, pk=None):
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role in ['bursar', 'reception']):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        student = self.get_object()
        term_number = request.data.get('term_number')
        academic_year = request.data.get('academic_year')
        if not term_number or not academic_year:
            return Response({'detail': 'term_number and academic_year are required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            term_number = int(term_number)
            academic_year = int(academic_year)
        except Exception:
            return Response({'detail': 'Invalid term_number/academic_year.'}, status=status.HTTP_400_BAD_REQUEST)

        inv = Invoice.objects.filter(student=student, term_number=term_number, academic_year=academic_year).first()
        if not inv:
            return Response({'detail': 'No invoice found for that term/year.'}, status=status.HTTP_404_NOT_FOUND)

        balance = (inv.amount_due or 0) - (inv.amount_paid or 0)
        if balance < 0:
            balance = 0
        msg = (
            f"Bitende Junior School: Fees reminder for {student.first_name} {student.last_name} "
            f"({student.student_id}) Term {term_number} {academic_year}. "
            f"Due: UGX {inv.amount_due}. Paid: UGX {inv.amount_paid}. Balance: UGX {balance}. "
            f"Please clear the balance. Thank you."
        )
        if not student.parent_phone:
            return Response({'detail': 'Student has no parent phone number.'}, status=status.HTTP_400_BAD_REQUEST)

        if not bool(get_system_setting('send_fee_reminder_sms', True)):
            return Response({'detail': 'Fee reminder SMS is disabled by system settings.'}, status=status.HTTP_400_BAD_REQUEST)

        send_sms(student.parent_phone, msg)
        _record_fee_reminder_log(
            student=student,
            created_by=request.user,
            channel='sms',
            status_v='sent',
            recipient=student.parent_phone,
            message=msg,
            invoice=inv,
            provider='system_sms',
        )
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='FEE_REMINDER_SENT',
            ip_address=get_client_ip(request),
            details=f'SMS fee reminder sent to {student.parent_phone} for {student.student_id} T{term_number}/{academic_year}.',
        )
        return Response({'detail': 'Reminder sent.'}, status=status.HTTP_200_OK)

    def _ensure_parent_portal(self, parent_name, parent_phone, parent_email, request):
        if not parent_phone:
            return None
        parent_username = parent_phone
        parent_user_profile = UserProfile.objects.filter(phone_number=parent_phone).first()
        if not parent_user_profile:
            parent_user = User.objects.filter(username=parent_username).first()
            if not parent_user:
                # Create a parent account if it doesn't exist yet.
                temporary_password = generate_random_password()
                parent_user = User.objects.create_user(username=parent_username, password=temporary_password, first_name=parent_name or parent_username)
                SecurityAuditLog.objects.create(user=parent_user, event_type='PARENT_ACCOUNT_CREATED', ip_address=get_client_ip(request), details=f'Parent account {parent_username} created during student update.')
            UserProfile.objects.create(
                user=parent_user,
                role='parent',
                avatar=((parent_name or parent_username)[:2]).upper(),
                phone_number=parent_phone,
                email_address=parent_email,
            )
            return parent_user
        else:
            if parent_email:
                parent_user_profile.email_address = parent_email
                parent_user_profile.save()
            return parent_user_profile.user

    def update(self, request, *args, **kwargs):
        if not self._can_edit_student_profiles(request.user):
            return Response({'detail': 'Only administrators can create or edit student profiles.'}, status=status.HTTP_403_FORBIDDEN)
        parent_email = request.data.get('parent_email')
        photo_url = request.data.get('photo_url')
        data = request.data.copy()
        data.pop('parent_email', None)
        data.pop('photo_url', None)

        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        if photo_url is not None:
            try:
                _apply_uploaded_media_to_field(serializer.instance, 'photo', photo_url)
            except ValidationError as e:
                return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        parent_user = self._ensure_parent_portal(
            parent_name=serializer.instance.parent_name,
            parent_phone=serializer.instance.parent_phone,
            parent_email=parent_email,
            request=request,
        )
        if parent_user:
            try:
                StudentGuardianLink.objects.update_or_create(
                    parent_user=parent_user,
                    student=serializer.instance,
                    defaults={
                        'relationship': (serializer.instance.parent_relationship or 'parent'),
                        'is_active': True,
                        'created_by': request.user,
                    },
                )
            except Exception:
                pass

        # Keep student portal user names in sync (username == student_id).
        try:
            student_user = User.objects.filter(username=serializer.instance.student_id).first()
            if student_user:
                student_user.first_name = serializer.instance.first_name
                student_user.last_name = serializer.instance.last_name
                student_user.save()
        except Exception:
            pass
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

class FeeStructureViewSet(viewsets.ModelViewSet):
    queryset = FeeStructure.objects.all()
    serializer_class = FeeStructureSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role) or role == 'bursar':
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]


class ClassChargeViewSet(viewsets.ModelViewSet):
    queryset = ClassCharge.objects.select_related('school_class', 'created_by').all().order_by('-academic_year', '-term_number', 'school_class__level', 'title')
    serializer_class = ClassChargeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _is_staff_role(self, role):
        return role in ['superadmin', 'bursar', 'reception'] or is_admin_role(role)

    def get_permissions(self):
        role = get_role(self.request.user)
        if self.action == 'mine':
            return [permissions.IsAuthenticated()]
        if self.request.method in permissions.SAFE_METHODS:
            if self._is_staff_role(role):
                return [permissions.IsAuthenticated()]
            return [permissions.IsAdminUser()]
        if role in ['superadmin', 'bursar'] or is_admin_role(role):
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def perform_create(self, serializer):
        data = serializer.validated_data
        active_term = _current_term()
        year = data.get('academic_year')
        term_number = data.get('term_number')
        if year is None and active_term:
            year = active_term.academic_year
        if term_number is None and active_term:
            term_number = active_term.term_number
        if year is not None and term_number is not None:
            term_obj = _require_active_term_target(year, term_number, label='term_number')
            due_date = data.get('due_date')
            if due_date is not None and not _term_covers_range(term_obj, due_date):
                raise DRFValidationError({'due_date': f'due_date must fall within Term {term_obj.term_number} {term_obj.academic_year}.'})
        obj = serializer.save(created_by=self.request.user, academic_year=year, term_number=term_number)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='CLASS_CHARGE_CREATED',
            ip_address=get_client_ip(self.request),
            details=f'Class charge created: {obj.school_class.level}{(obj.section or "")} - {obj.title}',
        )

    def perform_update(self, serializer):
        data = serializer.validated_data
        year = data.get('academic_year', serializer.instance.academic_year)
        term_number = data.get('term_number', serializer.instance.term_number)
        if year is not None and term_number is not None:
            term_obj = _require_active_term_target(year, term_number, label='term_number')
            due_date = data.get('due_date', serializer.instance.due_date)
            if due_date is not None and not _term_covers_range(term_obj, due_date):
                raise DRFValidationError({'due_date': f'due_date must fall within Term {term_obj.term_number} {term_obj.academic_year}.'})
        obj = serializer.save(academic_year=year, term_number=term_number)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='CLASS_CHARGE_UPDATED',
            ip_address=get_client_ip(self.request),
            details=f'Class charge updated: {obj.school_class.level}{(obj.section or "")} - {obj.title}',
        )

    def perform_destroy(self, instance):
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='CLASS_CHARGE_DELETED',
            ip_address=get_client_ip(self.request),
            details=f'Class charge deleted: {instance.school_class.level}{(instance.section or "")} - {instance.title}',
        )
        return super().perform_destroy(instance)

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)
        if not self._is_staff_role(role):
            # Do not allow non-staff to browse charges via list/retrieve. They must use /mine/.
            return qs.none()

        class_id = (self.request.query_params.get('class_id') or '').strip()
        year = (self.request.query_params.get('year') or '').strip()
        term = (self.request.query_params.get('term') or '').strip()
        active = (self.request.query_params.get('active') or '').strip()
        published = (self.request.query_params.get('published') or '').strip()

        if class_id.isdigit():
            qs = qs.filter(school_class_id=int(class_id))
        if year.isdigit():
            qs = qs.filter(academic_year=int(year))
        if term.isdigit():
            qs = qs.filter(term_number=int(term))
        if active:
            qs = qs.filter(is_active=_truthy(active))
        if published:
            qs = qs.filter(is_published=_truthy(published))
        return qs

    @action(detail=False, methods=['get'], url_path='mine')
    def mine(self, request):
        """
        Parent/student view of charges for their own class(es) only.
        Returns grouped results per student for convenience in the SPA.
        """
        role = get_role(request.user)
        if role not in ['parent', 'student']:
            return Response({'detail': 'Only parent/student users can access this.'}, status=status.HTTP_403_FORBIDDEN)

        active_term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number').first()
        year = active_term.academic_year if active_term else None
        term = active_term.term_number if active_term else None

        def charges_for_student(stu):
            if not stu or not stu.current_class_id:
                return []
            sec = (stu.section or '').strip().upper()
            q = ClassCharge.objects.filter(
                school_class_id=stu.current_class_id,
                is_active=True,
                is_published=True,
            ).filter(Q(section__isnull=True) | Q(section='') | Q(section=sec))
            if year is not None and term is not None:
                q = q.filter(
                    Q(academic_year__isnull=True) | Q(academic_year=year)
                ).filter(
                    Q(term_number__isnull=True) | Q(term_number=term)
                )
            return ClassChargeSerializer(q.order_by('due_date', 'title'), many=True).data

        if role == 'student':
            stu, _, _ = get_student_scope(request.user)
            if not stu:
                return Response({'students': []})
            return Response({
                'term': AcademicTermSerializer(active_term).data if active_term else None,
                'students': [{
                    'student': StudentSerializer(stu).data,
                    'charges': charges_for_student(stu),
                }]
            })

        # parent
        phone = getattr(getattr(request.user, 'profile', None), 'phone_number', None)
        if not phone:
            return Response({'students': []})
        kids = Student.objects.select_related('current_class').filter(Q(parent_phone=phone) | Q(parent_phone2=phone)).order_by('current_class__level', 'section', 'student_id')
        out = []
        for s in kids:
            out.append({
                'student': StudentSerializer(s).data,
                'charges': charges_for_student(s),
            })
        return Response({'term': AcademicTermSerializer(active_term).data if active_term else None, 'students': out})

class MarkViewSet(viewsets.ModelViewSet):
    queryset = Mark.objects.all()
    serializer_class = MarkSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role) or role in ['reception', 'teacher']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)

        # Optional filters (helpful for teacher dashboards).
        year_q = (self.request.query_params.get('year') or '').strip()
        term_q = (self.request.query_params.get('term') or '').strip()
        subj_q = (self.request.query_params.get('subject') or '').strip()
        student_q = (self.request.query_params.get('student') or '').strip()
        exam_type_q = (self.request.query_params.get('exam_type') or '').strip()
        if year_q.isdigit():
            qs = qs.filter(year=int(year_q))
        if term_q.isdigit():
            qs = qs.filter(term=int(term_q))
        if subj_q:
            qs = qs.filter(subject__iexact=subj_q)
        if student_q.isdigit():
            qs = qs.filter(student_id=int(student_q))
        if exam_type_q.isdigit():
            qs = qs.filter(exam_type_id=int(exam_type_q))

        if role == 'teacher':
            try:
                teacher = self.request.user.teacher_profile
            except Exception:
                return qs.none()
            return qs.filter(teacher=teacher)
        return qs

    def perform_create(self, serializer):
        role = get_role(self.request.user)
        if role == 'teacher':
            try:
                teacher = self.request.user.teacher_profile
            except Exception:
                raise PermissionDenied('Teacher profile not found.')

            student = serializer.validated_data.get('student')
            lvl, sec = get_teacher_scope(self.request.user)
            if not student or not lvl or not sec or not student.current_class or student.current_class.level != lvl or student.section != sec:
                raise PermissionDenied('Cannot enter marks for students outside your class.')

            # Term marks locking (DOS/special admin). If locked, teachers cannot write marks.
            try:
                year = int(serializer.validated_data.get('year'))
                term = int(serializer.validated_data.get('term'))
                _require_active_term_target(year, term)
                if AcademicTerm.objects.filter(academic_year=year, term_number=term, marks_locked=True).exists():
                    raise PermissionDenied(f'Marks are locked for Term {term} - {year}.')
            except PermissionDenied:
                raise
            except DRFValidationError:
                raise
            except Exception:
                pass

            exam_type = serializer.validated_data.get('exam_type')
            if exam_type and not getattr(exam_type, 'is_active', False):
                raise DRFValidationError({'exam_type': 'Selected exam type is inactive.'})
            serializer.save(teacher=teacher)
            return

        exam_type = serializer.validated_data.get('exam_type')
        if exam_type and not getattr(exam_type, 'is_active', False):
            raise DRFValidationError({'exam_type': 'Selected exam type is inactive.'})
        serializer.save()

    @action(detail=False, methods=['post'], url_path='bulk-upsert', permission_classes=[permissions.IsAuthenticated])
    def bulk_upsert(self, request):
        """
        Teacher/staff: bulk upsert marks for a class.
        Payload:
          {
            "year": 2026,
            "term": 1,
            "subject": "Mathematics",
            "items": [{"student": 123, "score": 78, "remarks": "Good"}, ...]
          }
        """
        role = get_role(request.user)
        if role not in ['superadmin', 'teacher'] and not is_admin_role(role) and role not in ['reception', 'dos', 'headteacher', 'deputy']:
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data or {}
        year = data.get('year')
        term = data.get('term')
        subject = (data.get('subject') or '').strip()
        exam_type_id = data.get('exam_type')
        items = data.get('items') or []
        if not (str(year).isdigit() and str(term).isdigit() and subject and isinstance(items, list)):
            return Response({'detail': 'year, term, subject, and items[] are required.'}, status=status.HTTP_400_BAD_REQUEST)
        year = int(year)
        term = int(term)
        if term not in [1, 2, 3]:
            return Response({'detail': 'term must be 1..3.'}, status=status.HTTP_400_BAD_REQUEST)
        _require_active_term_target(year, term)

        if AcademicTerm.objects.filter(academic_year=year, term_number=term, marks_locked=True).exists():
            return Response({'detail': f'Marks are locked for Term {term} - {year}.'}, status=status.HTTP_400_BAD_REQUEST)

        exam_type = None
        if str(exam_type_id).strip():
            if not str(exam_type_id).isdigit():
                return Response({'detail': 'exam_type must be a valid exam type id.'}, status=status.HTTP_400_BAD_REQUEST)
            exam_type = ExamType.objects.filter(id=int(exam_type_id), is_active=True).first()
            if exam_type is None:
                return Response({'detail': 'Selected exam type was not found or is inactive.'}, status=status.HTTP_400_BAD_REQUEST)

        teacher = None
        lvl = sec = None
        if role == 'teacher':
            try:
                teacher = request.user.teacher_profile
            except Exception:
                return Response({'detail': 'Teacher profile not found.'}, status=status.HTTP_400_BAD_REQUEST)
            lvl, sec = get_teacher_scope(request.user)
            if not lvl or not sec:
                return Response({'detail': 'Teacher class/section not assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        saved = 0
        with transaction.atomic():
            for it in items:
                try:
                    sid = int(it.get('student'))
                except Exception:
                    continue
                try:
                    score = int(it.get('score'))
                except Exception:
                    continue
                remarks = (it.get('remarks') or '').strip() or None

                stu = Student.objects.select_related('current_class').filter(id=sid).first()
                if not stu:
                    continue
                if role == 'teacher':
                    if not stu.current_class or stu.current_class.level != lvl or (stu.section or '').strip() != (sec or '').strip():
                        continue

                # Upsert by teacher+student+subject+term+year (delete dupes if any).
                base_q = Mark.objects.filter(student_id=sid, subject__iexact=subject, term=term, year=year)
                if exam_type is None:
                    base_q = base_q.filter(exam_type__isnull=True)
                else:
                    base_q = base_q.filter(exam_type=exam_type)
                if teacher is not None:
                    base_q = base_q.filter(teacher=teacher)
                existing = list(base_q.order_by('id')[:5])
                if existing:
                    m = existing[0]
                    m.score = score
                    m.remarks = remarks
                    m.exam_type = exam_type
                    if teacher is not None and m.teacher_id is None:
                        m.teacher = teacher
                    m.save(update_fields=['score', 'remarks', 'exam_type', 'teacher'])
                    if len(existing) > 1:
                        Mark.objects.filter(id__in=[x.id for x in existing[1:]]).delete()
                else:
                    Mark.objects.create(
                        student_id=sid,
                        subject=subject,
                        score=score,
                        term=term,
                        year=year,
                        exam_type=exam_type,
                        teacher=teacher,
                        remarks=remarks,
                    )
                saved += 1

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='MARKS_BULK_UPSERT',
            ip_address=get_client_ip(request),
            details=f'Bulk upsert marks subject={subject} exam_type={getattr(exam_type, "name", "term-average")} term={term}/{year} items={len(items)} saved={saved}.',
        )
        return Response({'saved': saved})

class AttendanceViewSet(viewsets.ModelViewSet):
    queryset = Attendance.objects.select_related('student').all()
    serializer_class = AttendanceSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role) or role in ['reception', 'teacher']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)
        include_archived = _truthy(self.request.query_params.get('include_archived'))

        if not include_archived:
            qs = qs.filter(is_archived=False)

        # Optional date filter for dashboards.
        d = (self.request.query_params.get('date') or '').strip()
        if d:
            try:
                qs = qs.filter(date=date.fromisoformat(d))
            except Exception:
                pass
        year_q = (self.request.query_params.get('year') or '').strip()
        term_q = (self.request.query_params.get('term') or '').strip()
        if year_q.isdigit():
            qs = qs.filter(academic_year=int(year_q))
        if term_q.isdigit():
            qs = qs.filter(term_number=int(term_q))

        if role == 'teacher':
            lvl, sec = get_teacher_scope(self.request.user)
            if not lvl or not sec:
                return qs.none()
            return qs.filter(student__current_class__level=lvl, student__section=sec)
        if role == 'parent':
            phone = getattr(getattr(self.request.user, 'profile', None), 'phone_number', None)
            if not phone:
                return qs.none()
            return qs.filter(Q(student__parent_phone=phone) | Q(student__parent_phone2=phone))
        return qs

    def perform_create(self, serializer):
        marked_date = serializer.validated_data.get('date') or timezone.localdate()
        term = _exact_term_for_date(marked_date)
        if not term or term.is_archived:
            raise DRFValidationError({'date': 'Attendance can only be recorded for a live configured term date.'})
        serializer.save(
            marked_by=self.request.user,
            academic_year=(term.academic_year if term else None),
            term_number=(term.term_number if term else None),
            is_archived=(bool(term.is_archived) if term else False),
        )

    @action(detail=False, methods=['post'], url_path='bulk-upsert', permission_classes=[permissions.IsAuthenticated])
    def bulk_upsert(self, request):
        """
        Teacher/staff: bulk upsert student attendance for a date.
        Payload:
          { "date": "2026-03-15", "items": [{"student": 1, "status": "present"}, ...] }
        """
        role = get_role(request.user)
        if role not in ['superadmin', 'teacher'] and not is_admin_role(role) and role not in ['reception', 'dos', 'headteacher', 'deputy']:
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data or {}
        d_raw = data.get('date')
        items = data.get('items') or []
        try:
            d = date.fromisoformat(str(d_raw)) if d_raw else timezone.localdate()
        except Exception:
            return Response({'detail': 'Invalid date.'}, status=status.HTTP_400_BAD_REQUEST)
        att_term = _exact_term_for_date(d)
        if not att_term or att_term.is_archived:
            return Response({'detail': 'Attendance can only be recorded for a live configured term date.'}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(items, list) or not items:
            return Response({'detail': 'items[] is required.'}, status=status.HTTP_400_BAD_REQUEST)

        lvl = sec = None
        if role == 'teacher':
            lvl, sec = get_teacher_scope(request.user)
            if not lvl or not sec:
                return Response({'detail': 'Teacher class/section not assigned.'}, status=status.HTTP_400_BAD_REQUEST)

        saved = 0
        with transaction.atomic():
            for it in items:
                try:
                    sid = int(it.get('student'))
                except Exception:
                    continue
                status_v = (it.get('status') or 'present').strip().lower()
                if status_v not in ['present', 'absent', 'late', 'excused']:
                    status_v = 'present'

                stu = Student.objects.select_related('current_class').filter(id=sid).first()
                if not stu:
                    continue
                if role == 'teacher':
                    if not stu.current_class or stu.current_class.level != lvl or (stu.section or '').strip() != (sec or '').strip():
                        continue

                # Enforce uniqueness by (student,date) in application layer.
                existing = list(Attendance.objects.filter(student_id=sid, date=d).order_by('id')[:5])
                if existing:
                    a = existing[0]
                    a.status = status_v
                    a.marked_by = request.user
                    a.academic_year = att_term.academic_year if att_term else a.academic_year
                    a.term_number = att_term.term_number if att_term else a.term_number
                    a.is_archived = bool(att_term.is_archived) if att_term else a.is_archived
                    a.save(update_fields=['status', 'marked_by', 'academic_year', 'term_number', 'is_archived'])
                    if len(existing) > 1:
                        Attendance.objects.filter(id__in=[x.id for x in existing[1:]]).delete()
                else:
                    Attendance.objects.create(
                        student_id=sid,
                        date=d,
                        status=status_v,
                        marked_by=request.user,
                        academic_year=(att_term.academic_year if att_term else None),
                        term_number=(att_term.term_number if att_term else None),
                        is_archived=(bool(att_term.is_archived) if att_term else False),
                    )
                saved += 1

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='STUDENT_ATTENDANCE_BULK_UPSERT',
            ip_address=get_client_ip(request),
            details=f'Bulk upsert student attendance date={d.isoformat()} items={len(items)} saved={saved}.',
        )
        return Response({'saved': saved, 'date': d.isoformat()})


class TeacherAttendanceViewSet(viewsets.ModelViewSet):
    queryset = TeacherAttendance.objects.select_related('teacher').all()
    serializer_class = TeacherAttendanceSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role) or role == 'reception':
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)

        # Optional date filter for all roles.
        d = (self.request.query_params.get('date') or '').strip()
        if d:
            try:
                qs = qs.filter(date=date.fromisoformat(d))
            except Exception:
                pass

        if role == 'teacher':
            try:
                t = self.request.user.teacher_profile
            except Exception:
                return qs.none()
            return qs.filter(teacher=t)

        return qs

    def perform_create(self, serializer):
        # Ensure method defaults to manual for human marking.
        serializer.save(marked_by=self.request.user, method=(serializer.validated_data.get('method') or 'manual'))

    @action(detail=False, methods=['get'], url_path='for-date')
    def for_date(self, request):
        """
        Reception/Admin helper: returns a full teacher list for a given date,
        including existing attendance or a default "not marked" record shape.
        """
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role == 'reception'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        d = (request.query_params.get('date') or '').strip()
        try:
            target_date = date.fromisoformat(d) if d else timezone.localdate()
        except Exception:
            return Response({'detail': 'Invalid date (use YYYY-MM-DD).'}, status=status.HTTP_400_BAD_REQUEST)

        teachers = Teacher.objects.all().order_by('first_name', 'last_name')
        existing = {a.teacher_id: a for a in TeacherAttendance.objects.filter(date=target_date)}

        out = []
        for t in teachers:
            a = existing.get(t.id)
            if a:
                out.append(TeacherAttendanceSerializer(a).data)
            else:
                out.append({
                    'id': None,
                    'teacher': t.id,
                    'teacher_name': f"{t.first_name} {t.last_name}".strip(),
                    'date': target_date.isoformat(),
                    'status': 'absent',  # default until marked
                    'method': 'manual',
                    'notes': '',
                })
        return Response(out)

    @action(detail=False, methods=['post'], url_path='upsert-bulk')
    def upsert_bulk(self, request):
        """
        Reception/Admin: bulk upsert entries.
        Payload: { items: [{teacher, date, status, notes?}, ...] }
        """
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role == 'reception'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        items = (request.data or {}).get('items', [])
        if not isinstance(items, list) or not items:
            return Response({'detail': 'items must be a non-empty list.'}, status=status.HTTP_400_BAD_REQUEST)

        saved = 0
        with transaction.atomic():
            for it in items:
                try:
                    tid = int(it.get('teacher'))
                    d = date.fromisoformat(str(it.get('date')))
                except Exception:
                    continue
                status_v = (it.get('status') or 'present').strip().lower()
                notes = (it.get('notes') or '').strip() or None

                obj, _ = TeacherAttendance.objects.update_or_create(
                    teacher_id=tid,
                    date=d,
                    defaults={
                        'status': status_v,
                        'method': 'manual',
                        'marked_by': request.user,
                        'notes': notes,
                    }
                )
                saved += 1 if obj else 0

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TEACHER_ATTENDANCE_BULK_UPSERT',
            ip_address=get_client_ip(request),
            details=f'Bulk upsert teacher attendance items={len(items)} saved={saved}.',
        )
        return Response({'saved': saved})

    @action(detail=False, methods=['post'], url_path='qr/generate')
    def qr_generate(self, request):
        """
        Reception/Admin: create a QR token and return a QR image for scanning.
        Teachers must be authenticated; scanning marks THEIR attendance for that date.
        """
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role == 'reception'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        d = (request.data or {}).get('date')
        expires_minutes = int((request.data or {}).get('expires_minutes') or 180)
        try:
            target_date = date.fromisoformat(str(d)) if d else timezone.localdate()
        except Exception:
            return Response({'detail': 'Invalid date.'}, status=status.HTTP_400_BAD_REQUEST)

        expires_at = timezone.now() + timedelta(minutes=max(10, min(expires_minutes, 24 * 60)))
        tok = TeacherAttendanceQRToken.objects.create(date=target_date, expires_at=expires_at, created_by=request.user)

        scan_url = request.build_absolute_uri('/') + f'?teacher_qr={tok.token}'
        img = qrcode.make(scan_url)
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TEACHER_ATTENDANCE_QR_GENERATED',
            ip_address=get_client_ip(request),
            details=f'Generated teacher attendance QR for date={target_date} exp={expires_at.isoformat()}.',
        )

        return Response({
            'token': str(tok.token),
            'date': target_date.isoformat(),
            'expires_at': expires_at.isoformat(),
            'scan_url': scan_url,
            'qr_png_base64': b64,
        })

    @action(detail=False, methods=['post'], url_path='qr/scan', permission_classes=[permissions.IsAuthenticated])
    def qr_scan(self, request):
        """
        Teacher-only: scan a token to mark attendance.
        Payload: { token: 'uuid' }
        """
        if get_role(request.user) != 'teacher':
            return Response({'detail': 'Only teachers can scan this QR.'}, status=status.HTTP_403_FORBIDDEN)

        token = (request.data or {}).get('token')
        if not token:
            return Response({'detail': 'token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        tok = TeacherAttendanceQRToken.objects.filter(token=token, is_active=True).first()
        if not tok:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_400_BAD_REQUEST)
        if tok.expires_at <= timezone.now():
            return Response({'detail': 'Token expired.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            t = request.user.teacher_profile
        except Exception:
            return Response({'detail': 'Teacher profile not linked.'}, status=status.HTTP_400_BAD_REQUEST)

        obj, created = TeacherAttendance.objects.update_or_create(
            teacher=t,
            date=tok.date,
            defaults={
                'status': 'present',
                'method': 'qr',
                'marked_by': request.user,
            }
        )

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TEACHER_ATTENDANCE_QR_SCANNED',
            ip_address=get_client_ip(request),
            details=f'Teacher attendance marked via QR date={tok.date} created={created}.',
        )

        return Response(TeacherAttendanceSerializer(obj).data)

    @action(detail=False, methods=['get'], url_path='mine')
    def mine(self, request):
        """
        Teacher-only: returns attendance history for the currently logged-in teacher.
        Query params:
          - days: int (default 30, max 180)
        """
        if get_role(request.user) != 'teacher':
            return Response({'detail': 'Only teachers can view this.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            t = request.user.teacher_profile
        except Exception:
            return Response({'detail': 'Teacher profile not linked.'}, status=status.HTTP_400_BAD_REQUEST)

        days = int((request.query_params.get('days') or 30) or 30)
        days = max(1, min(days, 180))
        start = timezone.localdate() - timedelta(days=days - 1)

        qs = TeacherAttendance.objects.filter(teacher=t, date__gte=start).order_by('-date')
        return Response(TeacherAttendanceSerializer(qs, many=True).data)

class TimetableViewSet(viewsets.ModelViewSet):
    queryset = Timetable.objects.select_related('school_class').all()
    serializer_class = TimetableSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role) or role == 'reception':
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)
        active_term = _current_term()
        year_q = (self.request.query_params.get('academic_year') or '').strip()
        term_q = (self.request.query_params.get('term_number') or '').strip()
        target_year = int(year_q) if year_q.isdigit() else (active_term.academic_year if active_term else None)
        target_term = int(term_q) if term_q.isdigit() else (active_term.term_number if active_term else None)

        # Optional filters for admins/reception to find a timetable quickly.
        class_id = (self.request.query_params.get('school_class') or '').strip()
        section_q = self.request.query_params.get('section', None)
        section = (section_q or '').strip().upper()
        is_active_q = self.request.query_params.get('is_active')
        if is_active_q is not None:
            qs = qs.filter(is_active=_truthy(is_active_q))
        else:
            qs = qs.filter(is_active=True)
        if target_year and target_term:
            qs = qs.filter(
                Q(academic_year=target_year, term_number=target_term)
                | Q(academic_year__isnull=True, term_number__isnull=True)
            )
        if role == 'superadmin' or is_admin_role(role) or role == 'reception':
            if class_id.isdigit():
                qs = qs.filter(school_class_id=int(class_id))
            # If the client provided the section param, filter even if it's blank.
            if section_q is not None:
                qs = qs.filter(section=section)
            return qs.order_by('school_class__level', 'section', '-academic_year', '-term_number', 'id')

        if role == 'teacher':
            lvl, sec = get_teacher_scope(self.request.user)
            if not lvl or not sec:
                return qs.none()
            return qs.filter(school_class__level=lvl, section=sec).order_by('-academic_year', '-term_number', 'id')

        if role == 'parent':
            phone = getattr(getattr(self.request.user, 'profile', None), 'phone_number', None)
            if not phone:
                return qs.none()
            children = Student.objects.filter(Q(parent_phone=phone) | Q(parent_phone2=phone)).select_related('current_class')
            pairs = {(c.current_class_id, (c.section or '').upper()) for c in children if c.current_class_id}
            if not pairs:
                return qs.none()
            q = Q()
            for (cid, sec) in pairs:
                q |= Q(school_class_id=cid, section=sec)
            return qs.filter(q).order_by('-academic_year', '-term_number', 'id')

        # Student accounts are not linked to Student records yet.
        if role == 'student':
            stu, lvl, sec = get_student_scope(self.request.user)
            if not lvl or sec is None or not stu or not stu.current_class_id:
                return qs.none()
            return qs.filter(school_class_id=stu.current_class_id, section=sec).order_by('-academic_year', '-term_number', 'id')

        return qs.none()

    @action(detail=False, methods=['get'], url_path='mine')
    def mine(self, request):
        chosen: Dict[tuple[int, str], Timetable] = {}
        rows = list(cast(Any, self.get_queryset()))
        for row in rows:
            key = (row.school_class_id, (row.section or '').strip().upper())
            if key not in chosen:
                chosen[key] = row
        data = TimetableSerializer(list(chosen.values()), many=True).data
        return Response(data)

    @action(detail=False, methods=['get'], url_path=r'for-class/(?P<class_id>\d+)/(?P<section>[A-Za-z])')
    def for_class(self, request, class_id, section):
        role = get_role(request.user)
        if role not in (['superadmin', 'reception', 'teacher', 'parent'] + list(ADMIN_ROLES)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        section = (section or '').upper()
        active_term = _current_term()
        tt = None
        if active_term:
            tt = Timetable.objects.filter(
                school_class_id=int(class_id),
                section=section,
                academic_year=active_term.academic_year,
                term_number=active_term.term_number,
                is_active=True,
            ).order_by('id').first()
        if tt is None:
            tt = Timetable.objects.filter(
                school_class_id=int(class_id),
                section=section,
                academic_year__isnull=True,
                term_number__isnull=True,
                is_active=True,
            ).order_by('id').first()
        if not tt:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(TimetableSerializer(tt).data)

    @action(detail=False, methods=['post'], url_path='upsert')
    def upsert(self, request):
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role == 'reception'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        school_class = request.data.get('school_class')
        section = (request.data.get('section') or '').strip().upper()
        academic_year = request.data.get('academic_year')
        term_number = request.data.get('term_number')
        slots = request.data.get('slots', None)
        cells = request.data.get('cells', None)

        if not school_class or not str(school_class).isdigit():
            return Response({'detail': 'school_class is required.'}, status=status.HTTP_400_BAD_REQUEST)
        # Sections are optional for schools that don't use A/B streams.
        if section and len(section) != 1:
            return Response({'detail': 'section must be a single letter (or leave blank if your school has no sections).'}, status=status.HTTP_400_BAD_REQUEST)
        if slots is None or cells is None:
            return Response({'detail': 'slots and cells are required.'}, status=status.HTTP_400_BAD_REQUEST)
        active_term = _current_term()
        if not str(academic_year or '').isdigit() and active_term:
            academic_year = active_term.academic_year
        if not str(term_number or '').isdigit() and active_term:
            term_number = active_term.term_number
        academic_year = int(academic_year) if str(academic_year or '').isdigit() else None
        term_number = int(term_number) if str(term_number or '').isdigit() else None

        obj, created = Timetable.objects.update_or_create(
            school_class_id=int(school_class),
            section=section,
            academic_year=academic_year,
            term_number=term_number,
            defaults={'slots': slots, 'cells': cells, 'is_active': True},
        )
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TIMETABLE_UPSERTED',
            ip_address=get_client_ip(request),
            details=f'Timetable saved for class_id={school_class} section={section} term={term_number}/{academic_year} (created={created}).',
        )
        return Response(TimetableSerializer(obj).data, status=status.HTTP_200_OK)

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsSuperUser]

    def create(self, request, *args, **kwargs):
        role = request.data.get('role', 'admin')
        username = (request.data.get('username') or '').strip()
        password_mode = (request.data.get('password_mode') or '').strip().lower()
        auto_password = _truthy(request.data.get('auto_password')) or password_mode == 'auto'
        password = request.data.get('password')
        first_name = (request.data.get('first_name') or '').strip()
        last_name = (request.data.get('last_name') or '').strip()
        # Normalize optional contact fields: never store empty string into unique columns.
        phone_number = (request.data.get('phone_number') or '').strip() or None
        email_address = (request.data.get('email_address') or '').strip().lower() or None

        if role in ['student', 'parent']:
            return Response({'detail': "Create student/parent accounts via Students registration (it auto-creates portals)."}, status=status.HTTP_400_BAD_REQUEST)

        if not username:
            username = _unique_username(
                _recommended_username(first_name=first_name, last_name=last_name, role=role),
                fallback=role or 'user',
            )

        generated_password = None
        if auto_password:
            generated_password = generate_random_password(12)
            password = generated_password
        else:
            if password is None or str(password).strip() == '':
                return Response({'detail': 'password is required (or choose auto-generate).'}, status=status.HTTP_400_BAD_REQUEST)
            password = str(password)
            try:
                validate_password(password)
            except ValidationError as e:
                return Response({'detail': 'Password does not meet security requirements.', 'errors': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        # Pre-check common uniqueness conflicts (still keep IntegrityError catch for races).
        if User.objects.filter(username=username).exists():
            return Response({'detail': 'Username already exists.'}, status=status.HTTP_400_BAD_REQUEST)
        if email_address and UserProfile.objects.filter(email_address=email_address).exists():
            return Response({'detail': 'Email address already in use.'}, status=status.HTTP_400_BAD_REQUEST)
        if phone_number and UserProfile.objects.filter(phone_number=phone_number).exists():
            return Response({'detail': 'Phone number already in use.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            login_url = request.build_absolute_uri('/')
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )
                UserProfile.objects.create(
                    user=user,
                    role=role,
                    avatar=(first_name[:2] if first_name else username[:2]).upper(),
                    phone_number=phone_number,
                    email_address=email_address,
                    must_change_password=True,
                )

                # Handover token + persistent print queue (Reception).
                handover = None
                final_password = password
                token = _issue_handover_token('user', user.id, {
                    'staff_name': f"{first_name} {last_name}".strip() or username,
                    'role': role,
                    'username': username,
                    'password': final_password,
                    'login_url': login_url,
                })
                handover = {
                    'token': token,
                    'expires_minutes': 15,
                    'print_credentials_url': f"/api/users/{user.id}/print-credentials/?token={token}",
                }
                try:
                    PrintQueueItem.objects.create(
                        kind='staff_credentials',
                        status='queued',
                        title=f"Staff credentials: {first_name} {last_name}".strip() or f"Staff credentials: {username}",
                        payload={
                            'staff_name': f"{first_name} {last_name}".strip() or username,
                            'role': role,
                            'username': username,
                            'password': final_password,
                            'login_url': login_url,
                        },
                        is_sensitive=True,
                        expires_at=timezone.now() + timedelta(hours=24),
                        requested_by=request.user,
                    )
                except Exception as e:
                    SecurityAuditLog.objects.create(
                        user=request.user,
                        event_type='PRINTQ_ENQUEUE_FAILED',
                        ip_address=get_client_ip(request),
                        details=f'Failed to enqueue staff credentials for user_id={user.id}: {e}',
                    )

                SecurityAuditLog.objects.create(
                    user=user,
                    event_type='USER_CREATED',
                    ip_address=get_client_ip(request),
                    details=f'User {username} created with role {role}',
                )
        except IntegrityError as e:
            msg = str(e).lower()
            if 'userprofile.email_address' in msg:
                return Response({'detail': 'Email address already in use.'}, status=status.HTTP_400_BAD_REQUEST)
            if 'userprofile.phone_number' in msg:
                return Response({'detail': 'Phone number already in use.'}, status=status.HTTP_400_BAD_REQUEST)
            if 'auth_user.username' in msg or 'username' in msg:
                return Response({'detail': 'Username already exists.'}, status=status.HTTP_400_BAD_REQUEST)
            raise

        role_label = (role or 'staff').replace('_', ' ').title()
        _, delivery = _send_staff_portal_bundle(
            request,
            display_name=f"{first_name} {last_name}".strip() or username,
            role_label=role_label,
            username=username,
            password=password,
            email=email_address,
            phone=phone_number,
            subject='Your Bitende Junior School login details',
            mode_label='Account setup',
        )
        if delivery['email_sent']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_EMAIL_SENT',
                ip_address=get_client_ip(request),
                details=f'Staff credentials email sent to {email_address} for {username}.',
            )
        elif delivery['email_attempted']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_EMAIL_FAILED',
                ip_address=get_client_ip(request),
                details=f'Failed to send staff credentials email to {email_address} for {username}.',
            )
        if delivery['sms_sent']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_SMS_SENT',
                ip_address=get_client_ip(request),
                details=f'Staff credentials SMS sent to {phone_number} for {username}.',
            )
        elif delivery['sms_attempted']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_SMS_FAILED',
                ip_address=get_client_ip(request),
                details=f'Failed to send staff credentials SMS to {phone_number} for {username}.',
            )

        try:
            notify_roles(
                list(dict.fromkeys(['superadmin'] + ADMIN_ROLE_LIST)),
                category='system',
                title='Staff account created',
                message=f'{role_label}: {first_name} {last_name}'.strip(': ') + f' ({username}) is ready.',
                link_page='users',
                link_object_id=user.id,
                meta={'user_id': user.id, 'role': role, 'username': username},
                event_key=f'user_created:{user.id}',
            )
            notify_user(
                user,
                category='system',
                title='Your staff account is ready',
                message='An administrator created your portal account. Sign in with the issued credentials and change your password immediately.',
                link_page='dashboard',
                link_object_id=user.id,
                meta={'role': role, 'username': username},
                force=True,
                event_key=f'user_account_ready:{user.id}',
            )
        except Exception:
            pass

        data = dict(UserSerializer(user).data)
        if generated_password:
            data['_initial_password'] = generated_password
        data['credentials'] = {
            'username': username,
            'temp_password': password,
            'email_address': email_address,
            'phone_number': phone_number,
        }
        data['delivery'] = delivery
        data['handover'] = handover
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='print-credentials')
    def print_credentials(self, request, pk=None):
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role in ['reception'] or request.user.is_superuser):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        user = self.get_object()
        token = request.query_params.get('token')
        payload = _get_handover_payload('user', user.id, token)
        if not payload:
            return Response({'detail': 'Handover token missing or expired. Re-generate credentials to print.'}, status=status.HTTP_400_BAD_REQUEST)
        pdf_buffer = generate_staff_credential_pdf(
            payload.get('staff_name'),
            payload.get('role'),
            payload.get('username') or user.username,
            payload.get('password'),
            payload.get('login_url') or request.build_absolute_uri('/'),
        )
        fn = f"staff_credentials_{user.username}.pdf"
        return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

    @action(detail=True, methods=['post'], url_path='reset-password', permission_classes=[permissions.IsAuthenticated])
    def reset_password(self, request, pk=None):
        """
        Superadmin, headteacher, or DOS can reset a staff user's password (manual or auto-generated),
        return a short-lived handover token for printing credentials, and enqueue a sensitive print item.
        """
        if not can_manage_passwords(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        user = self.get_object()
        data = request.data or {}
        password_mode = (data.get('password_mode') or '').strip().lower()
        auto_password = _truthy(data.get('auto_password')) or password_mode == 'auto'
        new_password = data.get('password')

        if auto_password:
            new_password = generate_random_password(12)
        else:
            if new_password is None or str(new_password).strip() == '':
                return Response({'detail': 'password is required (or choose auto-generate).'}, status=status.HTTP_400_BAD_REQUEST)
            new_password = str(new_password)
            try:
                validate_password(new_password, user=user)
            except ValidationError as e:
                return Response({'detail': 'Password does not meet security requirements.', 'errors': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            user.set_password(new_password)
            user.save(update_fields=['password'])
            UserProfile.objects.update_or_create(user=user, defaults={'must_change_password': True})

        login_url = request.build_absolute_uri('/')
        token = _issue_handover_token('user', user.id, {
            'staff_name': f"{user.first_name} {user.last_name}".strip() or user.username,
            'role': (getattr(getattr(user, 'profile', None), 'role', None) or '').strip() or 'staff',
            'username': user.username,
            'password': new_password,
            'login_url': login_url,
        })
        try:
            PrintQueueItem.objects.create(
                kind='staff_credentials',
                status='queued',
                title=f"Staff credentials: {user.first_name} {user.last_name}".strip() or f"Staff credentials: {user.username}",
                payload={
                    'staff_name': f"{user.first_name} {user.last_name}".strip() or user.username,
                    'role': (getattr(getattr(user, 'profile', None), 'role', None) or '').strip() or 'staff',
                    'username': user.username,
                    'password': new_password,
                    'login_url': login_url,
                },
                is_sensitive=True,
                expires_at=timezone.now() + timedelta(hours=24),
                requested_by=request.user,
            )
        except Exception as e:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='PRINTQ_ENQUEUE_FAILED',
                ip_address=get_client_ip(request),
                details=f'Failed to enqueue staff credentials for user_id={user.id} (reset): {e}',
            )

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='USER_PASSWORD_RESET',
            ip_address=get_client_ip(request),
            details=f'Password reset for {user.username} by {request.user.username}.',
        )

        role_label = (getattr(getattr(user, 'profile', None), 'role', None) or 'staff').replace('_', ' ').title()
        _, delivery = _send_staff_portal_bundle(
            request,
            display_name=f"{user.first_name} {user.last_name}".strip() or user.username,
            role_label=role_label,
            username=user.username,
            password=new_password,
            email=(getattr(getattr(user, 'profile', None), 'email_address', None) or user.email or None),
            phone=getattr(getattr(user, 'profile', None), 'phone_number', None),
            subject='Your Bitende Junior School login details',
            mode_label='Password reset',
        )
        if delivery['email_sent']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_EMAIL_SENT',
                ip_address=get_client_ip(request),
                details=f'Staff reset credentials email sent to {user.username}.',
            )
        elif delivery['email_attempted']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_EMAIL_FAILED',
                ip_address=get_client_ip(request),
                details=f'Failed to send staff reset credentials email for {user.username}.',
            )
        if delivery['sms_sent']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_SMS_SENT',
                ip_address=get_client_ip(request),
                details=f'Staff reset credentials SMS sent for {user.username}.',
            )
        elif delivery['sms_attempted']:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='CREDENTIALS_SMS_FAILED',
                ip_address=get_client_ip(request),
                details=f'Failed to send staff reset credentials SMS for {user.username}.',
            )

        try:
            notify_user(
                user,
                category='security',
                title='Password reset completed',
                message='Your portal password was reset by an administrator. Use the latest temporary password and change it after signing in.',
                link_page='dashboard',
                link_object_id=user.id,
                meta={'username': user.username},
                force=True,
                event_key=f'user_password_reset:{user.id}',
            )
        except Exception:
            pass

        resp = UserSerializer(user).data
        resp['_initial_password'] = new_password
        resp['credentials'] = {
            'username': user.username,
            'temp_password': new_password,
            'email_address': getattr(getattr(user, 'profile', None), 'email_address', None) or user.email or None,
            'phone_number': getattr(getattr(user, 'profile', None), 'phone_number', None),
        }
        resp['delivery'] = delivery
        resp['handover'] = {
            'token': token,
            'expires_minutes': 15,
            'print_credentials_url': f"/api/users/{user.id}/print-credentials/?token={token}",
        }
        return Response(resp)

    def update(self, request, *args, **kwargs):
        role = request.data.get('role', None)
        phone_number = request.data.get('phone_number', None)
        email_address = request.data.get('email_address', None)

        data = request.data.copy()
        # These belong to UserProfile, not auth.User.
        data.pop('role', None)
        data.pop('phone_number', None)
        data.pop('email_address', None)

        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # Update profile (create if missing).
        defaults = {}
        if role is not None:
            defaults['role'] = role
        if phone_number is not None:
            defaults['phone_number'] = (str(phone_number).strip() or None)
        if email_address is not None:
            defaults['email_address'] = (str(email_address).strip().lower() or None)
        if defaults:
            defaults['avatar'] = (serializer.instance.first_name[:2] if serializer.instance.first_name else serializer.instance.username[:2]).upper()
            try:
                UserProfile.objects.update_or_create(user=serializer.instance, defaults=defaults)
            except IntegrityError as e:
                msg = str(e).lower()
                if 'userprofile.email_address' in msg:
                    return Response({'detail': 'Email address already in use.'}, status=status.HTTP_400_BAD_REQUEST)
                if 'userprofile.phone_number' in msg:
                    return Response({'detail': 'Phone number already in use.'}, status=status.HTTP_400_BAD_REQUEST)
                raise

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='USER_UPDATED',
            ip_address=get_client_ip(request),
            details=f'User {serializer.instance.username} updated by {request.user.username}.',
        )
        return Response(UserSerializer(serializer.instance).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

class AuthViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    def _finalize_login(self, request, authenticated_user, ip_address, user_agent):
        """
        Common post-auth login flow:
        - Django login()
        - ensure profile exists + update last login IP/UA
        - upsert UserSession (unique session_key)
        - audit log
        """
        if not request.session.session_key:
            request.session.save()
        login(request, authenticated_user)
        # Ensure we have a stable session key after login() (Django may rotate keys).
        if not request.session.session_key:
            request.session.save()

        # Preserve existing role if present; don't overwrite teachers/parents into "admin".
        try:
            existing_profile = authenticated_user.profile
            role = existing_profile.role
        except UserProfile.DoesNotExist:
            role = 'superadmin' if authenticated_user.is_superuser else 'admin'

        UserProfile.objects.update_or_create(
            user=authenticated_user,
            defaults={
                'role': role,
                'avatar': (authenticated_user.first_name[:2] if authenticated_user.first_name else authenticated_user.username[:2]).upper(),
                'last_login_ip': ip_address,
                'last_login_ua': user_agent,
            }
        )
        # session_key is unique in our UserSession table; don't crash on repeated logins.
        UserSession.objects.update_or_create(
            session_key=request.session.session_key,
            defaults={
                'user': authenticated_user,
                'ip_address': ip_address,
                'user_agent': user_agent,
                'is_active': True,
                'logout_time': None,
                'login_time': timezone.now(),
            }
        )
        SecurityAuditLog.objects.create(
            user=authenticated_user,
            event_type='LOGIN_SUCCESS',
            ip_address=ip_address,
            details=f'User {authenticated_user.username} logged in successfully.',
        )
        return Response({'status': 'logged in', 'user': UserSerializer(authenticated_user).data})

    @action(detail=False, methods=['get'], authentication_classes=[], permission_classes=[permissions.AllowAny], url_path='csrf')
    @method_decorator(ensure_csrf_cookie)
    def csrf(self, request):
        """
        Returns a fresh CSRF token and ensures the CSRF cookie is set.
        Useful for SPA clients that may have a stale token/cookie pair.
        """
        return Response({'csrfToken': get_token(request)})

    # Explicitly protect sensitive unauthenticated endpoints as DRF viewsets are
    # CSRF-exempt by default unless the action is decorated.
    @action(detail=False, methods=['post'], authentication_classes=[])
    @method_decorator(csrf_protect)
    def login(self, request):
        identifier = request.data.get('identifier')
        password = request.data.get('password')
        if not identifier or not password:
            return Response({'detail': 'identifier and password are required.'}, status=status.HTTP_400_BAD_REQUEST)
        ip_address = get_client_ip(request)
        user_agent = get_user_agent(request)

        # Basic brute-force rate limiting (per IP + identifier).
        # This is intentionally simple (cache-based) to work without Redis.
        # Production can swap to a stronger rate limiter.
        ident_key = re.sub(r'[^a-zA-Z0-9@.+_-]', '_', str(identifier))[:80]
        rl_key = f'login_rl:{ip_address}:{ident_key}'
        fails = int(cache.get(rl_key, 0) or 0)
        if fails >= 8:
            SecurityAuditLog.objects.create(
                user=None,
                event_type='LOGIN_RATE_LIMITED',
                ip_address=ip_address,
                details=f'Rate limit hit for identifier={identifier}.',
            )
            return Response({'detail': 'Too many failed attempts. Try again in 15 minutes.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        user, user_profile = resolve_user_and_profile(identifier)
        
        if user:
            # Account lock (per user) after repeated failures.
            lock_key = f'login_lock:user:{user.id}'
            if cache.get(lock_key):
                SecurityAuditLog.objects.create(
                    user=user,
                    event_type='ACCOUNT_LOCKED',
                    ip_address=ip_address,
                    details=f'Login blocked: account is temporarily locked for {user.username}.',
                )
                return Response({'detail': 'Account temporarily locked due to repeated failed attempts. Try again later.'}, status=status.HTTP_423_LOCKED)

            authenticated_user = authenticate(username=user.username, password=password)
            if authenticated_user:
                cache.delete(rl_key)

                # New-device audit: compare previous IP/UA (best-effort).
                try:
                    prev = authenticated_user.profile
                    if (prev.last_login_ip and prev.last_login_ip != ip_address) or (prev.last_login_ua and prev.last_login_ua != user_agent):
                        SecurityAuditLog.objects.create(
                            user=authenticated_user,
                            event_type='NEW_DEVICE_LOGIN',
                            ip_address=ip_address,
                            details=f'New device/session detected for {authenticated_user.username}.',
                        )
                except Exception:
                    pass

                # Optional 2FA (OTP) enforcement when user enabled it.
                prof = user_profile or UserProfile.objects.filter(user=authenticated_user).first()
                user_role = (prof.role if prof else None) or ('superadmin' if authenticated_user.is_superuser else 'admin')
                twofa = bool(prof and prof.two_factor_enabled)
                if twofa and user_role not in ['student', 'parent']:
                    if not request.session.session_key:
                        request.session.save()
                    # Invalidate previous OTPs for login 2FA.
                    OTP.objects.filter(
                        user=authenticated_user,
                        purpose='login_2fa',
                        is_used=False,
                        expires_at__gt=timezone.now(),
                    ).update(is_used=True)
                    otp_code = generate_otp()
                    expires_at = timezone.now() + timedelta(minutes=10)
                    OTP.objects.create(user=authenticated_user, code=otp_code, purpose='login_2fa', expires_at=expires_at)

                    # Send OTP (email preferred, SMS fallback).
                    channels = []
                    to_email = (prof.email_address if prof else None) or (authenticated_user.email or None)
                    to_phone = (prof.phone_number if prof else None)
                    sent = False
                    if to_email:
                        try:
                            send_email(
                                subject='Login OTP - Bitende Junior School',
                                recipient_list=[to_email],
                                template_name='school/emails/otp_email.html',
                                context={'otp_code': otp_code, 'purpose': 'Login verification', 'expires_minutes': 10},
                            )
                            channels.append('email')
                            sent = True
                        except Exception:
                            pass
                    if (not sent) and to_phone:
                        try:
                            send_sms(to_phone, f"Your login OTP is {otp_code}. Expires in 10 minutes.")
                            channels.append('sms')
                            sent = True
                        except Exception:
                            pass
                    if not sent:
                        return Response({'detail': '2FA is enabled but no email/phone is configured. Contact admin.'}, status=status.HTTP_400_BAD_REQUEST)

                    request.session['pending_2fa_user_id'] = authenticated_user.id
                    request.session.save()
                    SecurityAuditLog.objects.create(
                        user=authenticated_user,
                        event_type='LOGIN_2FA_SENT',
                        ip_address=ip_address,
                        details=f'2FA OTP sent via {",".join(channels) or "unknown"} for {authenticated_user.username}.',
                    )
                    return Response({'status': 'otp_required', 'detail': 'OTP sent.', 'channels': channels, 'expires_minutes': 10})

                return self._finalize_login(request, authenticated_user, ip_address, user_agent)
            else:
                cache.set(rl_key, fails + 1, timeout=15 * 60)
                SecurityAuditLog.objects.create(user=user, event_type='LOGIN_FAILURE', ip_address=ip_address, details=f'Failed login attempt for user {user.username}.')
                # Per-user failures -> lock (30 mins) after 6 bad attempts (in addition to RL).
                user_fail_key = f'login_fail:user:{user.id}'
                uf = int(cache.get(user_fail_key, 0) or 0) + 1
                cache.set(user_fail_key, uf, timeout=30 * 60)
                if uf >= 6:
                    cache.set(lock_key, 1, timeout=30 * 60)
                    SecurityAuditLog.objects.create(
                        user=user,
                        event_type='ACCOUNT_LOCKED',
                        ip_address=ip_address,
                        details=f'Account locked for 30 minutes after {uf} failed attempts for {user.username}.',
                    )
        SecurityAuditLog.objects.create(user=None, event_type='LOGIN_FAILURE', ip_address=ip_address, details=f'Failed login attempt with identifier {identifier}.')
        return Response({'status': 'unauthorized', 'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)

    @action(detail=False, methods=['post'], url_path='confirm-2fa', permission_classes=[permissions.AllowAny])
    @method_decorator(csrf_protect)
    def confirm_2fa(self, request):
        """
        Confirm OTP for login when two_factor_enabled is set.
        Requires a pending user id stored in session by /auth/login/.
        """
        otp_code = (request.data.get('otp_code') or '').strip()
        ip_address = get_client_ip(request)
        user_agent = get_user_agent(request)
        if not otp_code:
            return Response({'detail': 'otp_code is required.'}, status=status.HTTP_400_BAD_REQUEST)

        uid = request.session.get('pending_2fa_user_id')
        if not uid:
            return Response({'detail': 'No pending 2FA login. Please login again.'}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(id=uid).first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_400_BAD_REQUEST)

        valid = OTP.objects.filter(
            user=user,
            code=otp_code,
            purpose='login_2fa',
            is_used=False,
            expires_at__gt=timezone.now(),
        ).first()
        if not valid:
            SecurityAuditLog.objects.create(
                user=user,
                event_type='OTP_INVALID_OR_EXPIRED',
                ip_address=ip_address,
                details=f'Invalid/expired login OTP for {user.username}.',
            )
            return Response({'detail': 'Invalid or expired OTP.'}, status=status.HTTP_400_BAD_REQUEST)

        valid.is_used = True
        valid.save(update_fields=['is_used'])
        try:
            del request.session['pending_2fa_user_id']
        except Exception:
            pass

        return self._finalize_login(request, user, ip_address, user_agent)

    @action(detail=False, methods=['post'])
    def logout(self, request):
        if request.user.is_authenticated:
            user_session = UserSession.objects.filter(user=request.user, session_key=request.session.session_key, is_active=True).first()
            if user_session:
                user_session.logout_time = timezone.now()
                user_session.is_active = False
                user_session.save()
            SecurityAuditLog.objects.create(user=request.user, event_type='LOGOUT_SUCCESS', ip_address=get_client_ip(request), details=f'User {request.user.username} logged out.')
        logout(request)
        return Response({'status': 'logged out'})

    @action(detail=False, methods=['post'], url_path='request-password-reset', authentication_classes=[])
    @method_decorator(csrf_protect)
    def request_password_reset(self, request):
        identifier = request.data.get('identifier')
        if not identifier:
            return Response({'detail': 'identifier is required.'}, status=status.HTTP_400_BAD_REQUEST)
        ip_address = get_client_ip(request)
        generic_detail = 'If an account exists for that identifier, an OTP has been sent to the registered contact.'
        ident_key = re.sub(r'[^a-zA-Z0-9@.+_-]', '_', str(identifier))[:80]
        rl_key = f'pwreset_rl:{ip_address}:{ident_key}'
        attempts = int(cache.get(rl_key, 0) or 0)
        cache.set(rl_key, attempts + 1, timeout=15 * 60)

        user, user_profile = resolve_user_and_profile(identifier)
        if user_profile and user_profile.user:
            user = user_profile.user
            OTP.objects.filter(user=user, purpose='password_reset', is_used=False, expires_at__gt=timezone.now()).update(is_used=True)

            otp_code = generate_otp()
            expires_at = timezone.now() + timedelta(minutes=15)
            OTP.objects.create(user=user, code=otp_code, purpose='password_reset', expires_at=expires_at)
            SecurityAuditLog.objects.create(user=user, event_type='OTP_REQUEST', ip_address=ip_address, details=f'Password reset OTP requested for {identifier}.')

            sent = False
            if user_profile.email_address:
                try:
                    send_email(
                        subject='Password Reset OTP - Bitende Junior School',
                        recipient_list=[user_profile.email_address],
                        template_name='school/emails/otp_email.html',
                        context={'otp_code': otp_code, 'user_name': user.first_name or user.username}
                    )
                    sent = True
                except Exception:
                    sent = False
            if user_profile.phone_number:
                try:
                    sms_message = f'Your Bitende Junior School password reset code is {otp_code}. It expires in 15 minutes.'
                    send_sms(user_profile.phone_number, sms_message)
                    sent = True
                except Exception:
                    pass
            if not sent:
                SecurityAuditLog.objects.create(
                    user=user,
                    event_type='OTP_REQUEST_FAILED',
                    ip_address=ip_address,
                    details=f'Password reset OTP could not be delivered for {identifier}.',
                )
        else:
            SecurityAuditLog.objects.create(user=None, event_type='OTP_REQUEST_FAILED', ip_address=ip_address, details=f'Password reset OTP requested for unknown identifier {identifier}.')
        return Response({'detail': generic_detail}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='confirm-password-reset', authentication_classes=[])
    @method_decorator(csrf_protect)
    def confirm_password_reset(self, request):
        identifier = request.data.get('identifier')
        otp_code = request.data.get('otp_code')
        new_password = request.data.get('new_password')
        if not identifier or not otp_code or not new_password:
            return Response({'detail': 'identifier, otp_code and new_password are required.'}, status=status.HTTP_400_BAD_REQUEST)

        user, user_profile = resolve_user_and_profile(identifier)
        if not user_profile or not user_profile.user:
            return Response({'detail': 'Invalid identifier.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            validate_password(str(new_password), user=user)
        except ValidationError as e:
            return Response({'detail': 'Password does not meet security requirements.', 'errors': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        valid_otp = OTP.objects.filter(user=user, code=otp_code, purpose='password_reset', is_used=False, expires_at__gt=timezone.now()).first()

        if valid_otp:
            user.set_password(new_password)
            user.save()
            valid_otp.is_used = True
            valid_otp.save()
            SecurityAuditLog.objects.create(user=user, event_type='PASSWORD_RESET_SUCCESS', ip_address=get_client_ip(request), details=f'Password for {user.username} reset successfully.')
            return Response({'detail': 'Password reset successfully. You can now log in with your new password.'}, status=status.HTTP_200_OK)
        else:
            SecurityAuditLog.objects.create(user=user, event_type='OTP_INVALID_OR_EXPIRED', ip_address=get_client_ip(request), details=f'Invalid or expired OTP provided for {user.username}.')
            return Response({'detail': 'Invalid or expired OTP.'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        if not request.user.is_authenticated:
            return Response({'status': 'not authenticated'}, status=status.HTTP_401_UNAUTHORIZED)

        if request.method.lower() == 'get':
            return Response(UserSerializer(request.user).data)

        # PATCH: Update basic profile fields for the currently authenticated user.
        data = request.data or {}
        u = request.user
        for f in ['first_name', 'last_name', 'email']:
            if f in data:
                setattr(u, f, (data.get(f) or '').strip())
        u.save()

        try:
            p = u.profile
        except Exception:
            p = UserProfile.objects.create(user=u, role='admin', avatar=(u.username[:2]).upper())

        if 'phone_number' in data:
            p.phone_number = (data.get('phone_number') or '').strip() or None
        if 'email_address' in data:
            p.email_address = (data.get('email_address') or '').strip() or None
        if 'profile_data' in data and isinstance(data.get('profile_data'), dict):
            # Only allow a small set of keys to avoid junk / sensitive data writes from clients.
            allowed = {'address', 'bio', 'job_title', 'theme'}
            incoming = {k: (data.get('profile_data') or {}).get(k) for k in allowed if k in (data.get('profile_data') or {})}
            existing = p.profile_data if isinstance(p.profile_data, dict) else {}
            p.profile_data = {**(existing or {}), **incoming}
        if 'two_factor_enabled' in data:
            want = bool(data.get('two_factor_enabled'))
            if want:
                # Require at least one delivery channel to be configured.
                has_email = bool((p.email_address or '').strip() or (u.email or '').strip())
                has_phone = bool((p.phone_number or '').strip())
                if not (has_email or has_phone):
                    return Response({'detail': 'Add an email address or phone number before enabling 2FA.'}, status=status.HTTP_400_BAD_REQUEST)
            p.two_factor_enabled = want
        if 'notification_prefs' in data and isinstance(data.get('notification_prefs'), dict):
            # Only allow known keys to avoid junk in DB.
            allowed = {'in_app', 'finance', 'academic', 'events', 'security', 'system'}
            incoming = {k: bool(v) for k, v in (data.get('notification_prefs') or {}).items() if k in allowed}
            existing = p.notification_prefs if isinstance(p.notification_prefs, dict) else {}
            p.notification_prefs = {**(existing or {}), **incoming}
        if 'photo_url' in data:
            v = (data.get('photo_url') or '').strip()
            p.photo_url = v or None
        p.avatar = (u.first_name[:2] if u.first_name else u.username[:2]).upper()
        p.save()

        SecurityAuditLog.objects.create(
            user=u,
            event_type='PROFILE_UPDATED',
            ip_address=get_client_ip(request),
            details='User updated their profile details.',
        )
        return Response(UserSerializer(u).data)

    @action(detail=False, methods=['get'], url_path='sessions', permission_classes=[permissions.IsAuthenticated])
    def sessions(self, request):
        sessions = UserSession.objects.filter(user=request.user).order_by('-login_time')[:20]
        logs = SecurityAuditLog.objects.filter(user=request.user).order_by('-timestamp')[:20]
        return Response({
            'sessions': UserSessionSerializer(sessions, many=True).data,
            'security_logs': SecurityAuditLogSerializer(logs, many=True).data,
        })

    @action(detail=False, methods=['post'], url_path='logout-other-sessions', permission_classes=[permissions.IsAuthenticated])
    def logout_other_sessions(self, request):
        current_key = request.session.session_key
        qs = UserSession.objects.filter(user=request.user, is_active=True).exclude(session_key=current_key)
        n = qs.update(is_active=False, logout_time=timezone.now())
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='LOGOUT_OTHER_SESSIONS',
            ip_address=get_client_ip(request),
            details=f'Logged out {n} other sessions.',
        )
        return Response({'detail': f'Logged out {n} other sessions.'})

    @action(detail=False, methods=['post'], url_path='change-password', permission_classes=[permissions.IsAuthenticated])
    def change_password(self, request):
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')

        if not current_password or not new_password:
            return Response({'detail': 'current_password and new_password are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(str(new_password), user=request.user)
        except ValidationError as e:
            return Response({'detail': 'Password does not meet security requirements.', 'errors': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        if not request.user.check_password(current_password):
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='PASSWORD_CHANGE_FAILED',
                ip_address=get_client_ip(request),
                details='Incorrect current password provided.',
            )
            return Response({'detail': 'Incorrect current password.'}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(new_password)
        request.user.save()
        # Clear must-change flag after a successful password update.
        try:
            p = request.user.profile
            if p.must_change_password:
                p.must_change_password = False
                p.save(update_fields=['must_change_password'])
        except Exception:
            pass
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PASSWORD_CHANGED',
            ip_address=get_client_ip(request),
            details=f'Password changed by {request.user.username}.',
        )
        return Response({'detail': 'Password changed successfully.'}, status=status.HTTP_200_OK)

class PromotionViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, CanManagePromotions]

    def _report_helper(self):
        return ReportCardViewSet()

    @action(detail=False, methods=['get'], url_path=r'students-for-promotion/(?P<class_id>\d+)/(?P<section>[^/.]+)')
    def list_students_for_promotion(self, request, class_id, section):
        try:
            school_class = SchoolClass.objects.get(id=class_id)
        except SchoolClass.DoesNotExist:
            return Response({'detail': 'Class not found.'}, status=status.HTTP_404_NOT_FOUND)

        current_academic_term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number').first()
        if not current_academic_term:
            return Response({'detail': 'No active academic term found.'}, status=status.HTTP_400_BAD_REQUEST)

        students = Student.objects.filter(current_class=school_class, section=section, status='active')
        helper = self._report_helper()
        assessment_config = _normalize_assessment_config(current_academic_term, getattr(current_academic_term, 'assessment_config', None) or {})
        threshold = float(assessment_config.get('promotion_threshold', 50))

        results = []
        for student in students:
            term_average = helper._term_average_for_student(student, current_academic_term.academic_year, current_academic_term.term_number) or 0
            yearly_average, yearly_term_breakdown = helper._yearly_average_for_student(student, current_academic_term.academic_year)
            decision_basis = yearly_average if current_academic_term.term_number == 3 and yearly_average is not None else term_average

            suggested_decision = 'repeat_year'
            if decision_basis >= threshold:
                if school_class.level == 'P.7':
                    suggested_decision = 'graduate'
                else:
                    suggested_decision = 'promote'
            
            results.append({
                'student_id': student.id,
                'first_name': student.first_name,
                'last_name': student.last_name,
                'student_system_id': student.student_id,
                'term_average': round(term_average, 2),
                'yearly_average': yearly_average,
                'yearly_term_breakdown': yearly_term_breakdown,
                'promotion_basis': 'yearly_average' if current_academic_term.term_number == 3 else 'term_average',
                'suggested_decision': suggested_decision,
                'current_class_level': school_class.level,
                'current_section': section,
                'promotion_notes': student.promotion_notes,
            })

        # Sort students by average score (highest first for position)
        results = sorted(results, key=lambda x: x['term_average'], reverse=True)
        for i, student_data in enumerate(results):
            student_data['class_position'] = i + 1
        
        return Response(results)

    @action(detail=False, methods=['post'], url_path='auto-promote')
    def auto_promote(self, request):
        class_id = request.data.get('class_id')
        section = request.data.get('section')

        try:
            school_class = SchoolClass.objects.get(id=class_id)
        except SchoolClass.DoesNotExist:
            return Response({'detail': 'Class not found.'}, status=status.HTTP_404_NOT_FOUND)

        current_academic_term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number').first()
        if not current_academic_term:
            return Response({'detail': 'No active academic term found.'}, status=status.HTTP_400_BAD_REQUEST)

        students = Student.objects.filter(current_class=school_class, section=section, status='active')
        helper = self._report_helper()
        assessment_config = _normalize_assessment_config(current_academic_term, getattr(current_academic_term, 'assessment_config', None) or {})
        threshold = float(assessment_config.get('promotion_threshold', 50))

        promotion_suggestions = []
        for student in students:
            term_average = helper._term_average_for_student(student, current_academic_term.academic_year, current_academic_term.term_number) or 0
            yearly_average, yearly_term_breakdown = helper._yearly_average_for_student(student, current_academic_term.academic_year)
            decision_basis = yearly_average if current_academic_term.term_number == 3 and yearly_average is not None else term_average

            decision = 'repeat_year'
            if decision_basis >= threshold:
                if school_class.level == 'P.7':
                    decision = 'graduate'
                else:
                    decision = 'promote'
            
            promotion_suggestions.append({
                'student_id': student.id,
                'decision': decision,
                'term_average': round(term_average, 2),
                'yearly_average': yearly_average,
                'yearly_term_breakdown': yearly_term_breakdown,
                'promotion_basis': 'yearly_average' if current_academic_term.term_number == 3 else 'term_average',
                'notes': student.promotion_notes,
            })
        return Response(promotion_suggestions)

    @action(detail=False, methods=['post'], url_path='confirm')
    def confirm_promotions(self, request):
        promotion_data = request.data.get('promotions', [])
        current_year = date.today().year # Assuming promotions are run at year end

        current_academic_term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number').first()
        if not current_academic_term or current_academic_term.term_number != 3: # Promotions usually after Term 3
            return Response({'detail': 'Promotions can only be confirmed at the end of Term 3.'}, status=status.HTTP_400_BAD_REQUEST)

        for item in promotion_data:
            student_id = item.get('student_id')
            decision = item.get('decision')
            notes = item.get('notes', '')

            try:
                student = Student.objects.get(id=student_id)
                old_class = student.current_class
                old_section = student.section
                new_class = None
                new_section = old_section

                student.previous_class = old_class
                student.previous_section = old_section
                student.promotion_year = current_year
                student.promotion_term = current_academic_term.term_number
                student.promotion_notes = notes

                if decision == 'promote':
                    next_level_map = {'P.1': 'P.2', 'P.2': 'P.3', 'P.3': 'P.4', 'P.4': 'P.5', 'P.5': 'P.6', 'P.6': 'P.7'}
                    next_level = next_level_map.get(old_class.level)
                    if next_level:
                        new_class = SchoolClass.objects.filter(level=next_level).first()
                        if new_class:
                            student.current_class = new_class
                            student.section = new_section
                            student.status = 'active' # Promote to active in new class
                        else:
                            logger.warning(f"Next class level {next_level} not found for student {student.id}")
                            student.status = 'promoted' # Still mark as promoted even if class not found
                    else:
                        student.status = 'promoted' # Can't promote further (e.g. P.7 should graduate)
                
                elif decision == 'repeat_year':
                    new_class = old_class
                    student.current_class = new_class
                    student.section = new_section
                    student.status = 'repeating'

                elif decision == 'graduate':
                    student.status = 'alumnus' # Update status to alumnus
                    student.current_class = None # P.7 graduates are no longer in an active class
                    student.section = None

                    # Create Alumni Register entry
                    alumni_entry = AlumniRegister.objects.create(
                        student=student,
                        graduation_year=current_year
                    )

                    # Generate certificate PDF
                    # Recalculate average and position for P.7 student for certificate
                    marks = Mark.objects.filter(student=student, year=current_academic_term.academic_year, term=current_academic_term.term_number)
                    average_score = marks.aggregate(Avg('score'))['score__avg'] if marks.exists() else 0

                    # This is a simplified class position. In a real scenario, you'd calculate this based on all P.7 students.
                    all_p7_students_marks = Mark.objects.filter(
                        student__current_class__level='P.7',
                        year=current_academic_term.academic_year,
                        term=current_academic_term.term_number
                    ).values('student').annotate(avg_score=Avg('score'))
                    sorted_p7_students = sorted(all_p7_students_marks, key=lambda x: x['avg_score'], reverse=True)
                    class_position = 0
                    for i, s in enumerate(sorted_p7_students):
                        if s['student'] == student.id:
                            class_position = i + 1
                            break

                    pdf_buffer = generate_graduation_certificate_pdf(
                        student=student,
                        academic_year=current_year,
                        average_score=average_score,
                        class_position=class_position
                    )
                    alumni_entry.certificate_pdf.save(f'certificate_{student.student_id}_{current_year}.pdf', ContentFile(pdf_buffer.getvalue()))
                    alumni_entry.save()

                    # Send SMS to parent
                    sms_message = f'Congratulations! {student.first_name} has completed P.7 at Bitende Junior School.'
                    if student.parent_phone:
                        send_sms(student.parent_phone, sms_message)

                elif decision in ['transfer_out', 'withdraw']:
                    student.status = decision # Set status to transfer_out or withdrawn
                    student.current_class = None
                    student.section = None
                
                student.save()

                PromotionAudit.objects.create(
                    student=student,
                    admin_user=request.user,
                    decision=decision,
                    old_class=old_class,
                    new_class=new_class,
                    notes=notes
                )
            except Student.DoesNotExist:
                logger.error(f"Student with ID {student_id} not found during promotion confirmation.")
                continue
            except Exception as e:
                logger.error(f"Error processing promotion for student {student_id}: {e}")
                return Response({'detail': f'Error processing some promotions: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({'detail': 'Promotions confirmed and applied successfully.'}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='audit')
    def promotion_audit(self, request):
        audit_records = PromotionAudit.objects.all().order_by('-decision_date')
        serializer = PromotionAuditSerializer(audit_records, many=True)
        return Response(serializer.data)

class AcademicTermViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, CanManageTerms]

    def list(self, request):
        active_term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number').first()
        if not active_term:
            return Response([])
        return Response(AcademicTermSerializer(active_term).data)

    @action(detail=False, methods=['get'], url_path='all')
    def all_terms(self, request):
        qs = AcademicTerm.objects.all().order_by('-academic_year', '-term_number', '-start_date')
        return Response(AcademicTermSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], url_path='active-calendar')
    def active_calendar(self, request):
        term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number', '-start_date').first()
        if not term:
            return Response({'detail': 'No active term found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_term_calendar(term))

    @action(detail=False, methods=['post'], url_path='start-new')
    def start_new_term(self, request):
        academic_year = request.data.get('academic_year')
        term_number = request.data.get('term_number')
        start_date_str = request.data.get('start_date')
        end_date_str = request.data.get('end_date')
        holiday_break_days = request.data.get('holiday_break_days', 0)
        auto_generate_invoices = request.data.get('auto_generate_invoices', False)
        sms_parents = request.data.get('sms_parents', False)
        open_mark_entry = request.data.get('open_mark_entry', False)
        assessment_config = request.data.get('assessment_config', {})

        if not all([academic_year, term_number, start_date_str, end_date_str]):
            return Response({'detail': 'Missing required term details.'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            academic_year = int(academic_year)
            term_number = int(term_number)
            holiday_break_days = max(0, int(holiday_break_days or 0))
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
        except (TypeError, ValueError):
            return Response({'detail': 'Invalid term payload. Use numeric year/term and YYYY-MM-DD dates.'}, status=status.HTTP_400_BAD_REQUEST)

        if term_number not in [1, 2, 3]:
            return Response({'detail': 'term_number must be 1, 2, or 3.'}, status=status.HTTP_400_BAD_REQUEST)
        if end_date < start_date:
            return Response({'detail': 'end_date must be after start_date.'}, status=status.HTTP_400_BAD_REQUEST)
        if AcademicTerm.objects.filter(academic_year=academic_year, term_number=term_number).exists():
            return Response({'detail': 'That academic year and term number already exist.'}, status=status.HTTP_400_BAD_REQUEST)
        if _term_overlaps_existing(start_date=start_date, end_date=end_date):
            return Response({'detail': 'The new term overlaps an existing term. Edit the existing term instead.'}, status=status.HTTP_400_BAD_REQUEST)

        # Archive previous term
        current_active_term = AcademicTerm.objects.filter(is_archived=False).first()
        if current_active_term:
            # Optional policy: auto-hold results for defaulters at term end.
            try:
                pol = SystemSetting.objects.filter(key='results_policy').values_list('value', flat=True).first()
                auto_hold = False
                if isinstance(pol, dict):
                    auto_hold = bool(pol.get('auto_hold_on_term_end', False))
                if auto_hold:
                    now_ts = timezone.now()
                    reason = (pol.get('default_reason') if isinstance(pol, dict) else None) or 'Outstanding fees'
                    qs = Invoice.objects.filter(
                        academic_year=current_active_term.academic_year,
                        term_number=current_active_term.term_number,
                        status__in=['unpaid', 'partial'],
                    )
                    invoices = list(qs[:5000])
                    n = qs.update(
                        results_blocked=True,
                        results_block_reason=reason,
                        results_blocked_by=request.user,
                        results_blocked_at=now_ts,
                    )
                    ResultsHoldLog.objects.bulk_create([
                        ResultsHoldLog(
                            invoice=inv,
                            action='held',
                            reason=reason,
                            source='term_auto_hold',
                            acted_by=request.user,
                            acted_at=now_ts,
                        )
                        for inv in invoices
                    ])
                    SecurityAuditLog.objects.create(
                        user=request.user,
                        event_type='RESULTS_AUTO_HELD',
                        ip_address=get_client_ip(request),
                        details=f'Auto-held results for {n} defaulters T{current_active_term.term_number}/{current_active_term.academic_year}.',
                    )
            except Exception:
                pass

            current_active_term.is_archived = True
            current_active_term.save()
            logger.info(f"Archived previous term: {current_active_term}")

        # Create new term
        new_term = AcademicTerm.objects.create(
            academic_year=academic_year,
            term_number=term_number,
            start_date=start_date,
            end_date=end_date,
            assessment_config=_normalize_assessment_config(None, assessment_config),
            holiday_break_days=holiday_break_days,
            auto_generate_invoices_on_start=auto_generate_invoices,
            sms_parents_on_start=sms_parents,
            open_mark_entry_on_start=open_mark_entry,
            is_archived=False # New term is active
        )
        logger.info(f"Created new term: {new_term}")
        _sync_term_calendar_events(new_term)

        # Preserve prior attendance history by archiving it into the completed term.
        if current_active_term:
            Attendance.objects.filter(is_archived=False, academic_year__isnull=True, term_number__isnull=True).update(
                academic_year=current_active_term.academic_year,
                term_number=current_active_term.term_number,
                is_archived=True,
            )
            Attendance.objects.filter(is_archived=False).update(is_archived=True)
            logger.info("Archived active attendance records for the completed term.")

        # Auto-generate invoices
        if auto_generate_invoices:
            active_students = Student.objects.filter(status__in=['active', 'repeating'])
            for student in active_students:
                try:
                    fee_structure = FeeStructure.objects.get(
                        school_class=student.current_class,
                        term=new_term.term_number,
                        year=new_term.academic_year
                    )
                    Invoice.objects.update_or_create(
                        student=student,
                        academic_year=new_term.academic_year,
                        term_number=new_term.term_number,
                        defaults={'amount_due': fee_structure.amount},
                    )
                except FeeStructure.DoesNotExist:
                    # Fallback: annual fee / 3 if fee row missing.
                    due = Decimal('0')
                    try:
                        if student.current_class and student.current_class.annual_fee is not None:
                            due = (Decimal(str(student.current_class.annual_fee)) / Decimal('3')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    except Exception:
                        due = Decimal('0')

                    Invoice.objects.update_or_create(
                        student=student,
                        academic_year=new_term.academic_year,
                        term_number=new_term.term_number,
                        defaults={'amount_due': due},
                    )
                    logger.warning(f"No fee structure found; invoice fallback used for student {student.id} in class {student.current_class.level} for term {new_term.term_number}")
            logger.info("Completed auto-generation of invoices.")

        # SMS parents
        if sms_parents:
            parent_phones = Student.objects.filter(status__in=['active', 'repeating']).exclude(parent_phone__isnull=True).values_list('parent_phone', flat=True).distinct()
            sms_message = f"Dear Parent, A new term is starting on {new_term.start_date.strftime('%Y-%m-%d')} at Bitende Junior School."
            for phone in parent_phones:
                send_sms(phone, sms_message)
            logger.info("Completed sending SMS to parents.")

        # Open mark-entry (this is more of a UI/front-end flag or a setting)
        if open_mark_entry:
            logger.info("Mark entry is now open for teachers.")
            # You might want to store this in AcademicTerm or a global setting
        
        serializer = AcademicTermSerializer(new_term)
        return Response({'detail': 'New term started successfully.', 'term': serializer.data}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='history')
    def term_history(self, request):
        archived_terms = AcademicTerm.objects.filter(is_archived=True).order_by('-academic_year', '-term_number')
        serializer = AcademicTermSerializer(archived_terms, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['patch'], url_path='edit')
    def edit_term(self, request, pk=None):
        try:
            term = AcademicTerm.objects.get(pk=pk)
        except AcademicTerm.DoesNotExist:
            return Response({'detail': 'Term not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data or {}

        if 'start_date' in data:
            try:
                term.start_date = date.fromisoformat(str(data.get('start_date')))
            except Exception:
                return Response({'detail': 'Invalid start_date.'}, status=status.HTTP_400_BAD_REQUEST)
        if 'end_date' in data:
            try:
                term.end_date = date.fromisoformat(str(data.get('end_date')))
            except Exception:
                return Response({'detail': 'Invalid end_date.'}, status=status.HTTP_400_BAD_REQUEST)

        for f in ['holiday_break_days', 'auto_generate_invoices_on_start', 'sms_parents_on_start', 'open_mark_entry_on_start']:
            if f in data:
                setattr(term, f, data.get(f))
        if 'assessment_config' in data:
            term.assessment_config = _normalize_assessment_config(term, data.get('assessment_config'))

        try:
            term.holiday_break_days = max(0, int(term.holiday_break_days or 0))
        except (TypeError, ValueError):
            return Response({'detail': 'holiday_break_days must be a whole number.'}, status=status.HTTP_400_BAD_REQUEST)

        if term.end_date and term.start_date and term.end_date < term.start_date:
            return Response({'detail': 'end_date must be after start_date.'}, status=status.HTTP_400_BAD_REQUEST)
        if _term_overlaps_existing(start_date=term.start_date, end_date=term.end_date, exclude_term_id=term.id):
            return Response({'detail': 'This term overlaps another saved term.'}, status=status.HTTP_400_BAD_REQUEST)

        term.save()
        _sync_term_calendar_events(term)
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TERM_EDITED',
            ip_address=get_client_ip(request),
            details=f'Edited term id={term.id} year={term.academic_year} term={term.term_number}.',
        )
        return Response(AcademicTermSerializer(term).data)

    @action(detail=True, methods=['post'], url_path='configure-assessment')
    def configure_assessment(self, request, pk=None):
        try:
            term = AcademicTerm.objects.get(pk=pk)
        except AcademicTerm.DoesNotExist:
            return Response({'detail': 'Term not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not has_assessment_policy_permission(request.user):
            return Response({'detail': 'Only Super Admin, Director, Head Teacher, and DOS can configure term assessments.'}, status=status.HTTP_403_FORBIDDEN)

        term.assessment_config = _normalize_assessment_config(term, (request.data or {}).get('assessment_config'))
        term.save(update_fields=['assessment_config'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TERM_ASSESSMENT_CONFIGURED',
            ip_address=get_client_ip(request),
            details=f'Configured assessment policy for term id={term.id} year={term.academic_year} term={term.term_number}.',
        )
        return Response(AcademicTermSerializer(term).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='calendar')
    def calendar(self, request, pk=None):
        try:
            term = AcademicTerm.objects.get(pk=pk)
        except AcademicTerm.DoesNotExist:
            return Response({'detail': 'Term not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_term_calendar(term))

    @action(detail=True, methods=['post'], url_path='sync-public-holidays')
    def sync_public_holidays(self, request, pk=None):
        try:
            term = AcademicTerm.objects.get(pk=pk)
        except AcademicTerm.DoesNotExist:
            return Response({'detail': 'Term not found.'}, status=status.HTTP_404_NOT_FOUND)
        _sync_public_holiday_events(term)
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TERM_PUBLIC_HOLIDAYS_SYNCED',
            ip_address=get_client_ip(request),
            details=f'Synced public holidays for term id={term.id} year={term.academic_year} term={term.term_number}.',
        )
        return Response(_serialize_term_calendar(term), status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'], url_path='delete')
    def delete_term(self, request, pk=None): 
        try:
            term = AcademicTerm.objects.get(pk=pk)
        except AcademicTerm.DoesNotExist:
            return Response({'detail': 'Term not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not term.is_archived:
            return Response({'detail': 'Cannot delete the active term. Archive it first.'}, status=status.HTTP_400_BAD_REQUEST)

        force = _truthy(request.query_params.get('force')) or _truthy((request.data or {}).get('force')) 
        inv_qs = Invoice.objects.filter(academic_year=term.academic_year, term_number=term.term_number) 
        pay_exists = Payment.objects.filter(academic_year=term.academic_year, term_number=term.term_number).exists() 
        if pay_exists: 
            return Response({'detail': 'Cannot delete: payments exist for this term.'}, status=status.HTTP_400_BAD_REQUEST) 
        if inv_qs.exists() and not force: 
            return Response({'detail': 'Cannot delete: invoices exist for this term. Use force=true to delete invoices/marks too.'}, status=status.HTTP_400_BAD_REQUEST) 
        if force and get_role(request.user) != 'superadmin' and not request.user.is_superuser: 
            return Response({'detail': 'Only super admin can force delete a term.'}, status=status.HTTP_403_FORBIDDEN) 
 
        if force: 
            # Destructive cleanup limited to this term/year. 
            Mark.objects.filter(term=term.term_number, year=term.academic_year).delete() 
            inv_qs.delete() 
            InvoiceAdjustment.objects.filter(academic_year=term.academic_year, term_number=term.term_number).delete() 

        tid = term.id
        term.delete()
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TERM_DELETED',
            ip_address=get_client_ip(request),
            details=f'Deleted term id={tid}.',
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='lock-marks')
    def lock_marks(self, request, pk=None):
        try:
            term = AcademicTerm.objects.get(pk=pk)
        except AcademicTerm.DoesNotExist:
            return Response({'detail': 'Term not found.'}, status=status.HTTP_404_NOT_FOUND)

        term.marks_locked = True
        term.marks_locked_at = timezone.now()
        term.marks_locked_by = request.user
        reason = ((request.data or {}).get('reason') or '').strip()
        term.marks_lock_reason = reason or None
        term.save(update_fields=['marks_locked', 'marks_locked_at', 'marks_locked_by', 'marks_lock_reason'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='MARKS_LOCKED',
            ip_address=get_client_ip(request),
            details=f'Locked marks for term id={term.id} T{term.term_number}/{term.academic_year}.',
        )
        return Response(AcademicTermSerializer(term).data)

    @action(detail=True, methods=['post'], url_path='unlock-marks')
    def unlock_marks(self, request, pk=None):
        try:
            term = AcademicTerm.objects.get(pk=pk)
        except AcademicTerm.DoesNotExist:
            return Response({'detail': 'Term not found.'}, status=status.HTTP_404_NOT_FOUND)

        term.marks_locked = False
        term.marks_lock_reason = None
        term.save(update_fields=['marks_locked', 'marks_lock_reason'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='MARKS_UNLOCKED',
            ip_address=get_client_ip(request),
            details=f'Unlocked marks for term id={term.id} T{term.term_number}/{term.academic_year}.',
        )
        return Response(AcademicTermSerializer(term).data)

class ReportCardViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, CanManageReportCards]

    def _term_assessment_config(self, academic_year, term_number):
        term = AcademicTerm.objects.filter(academic_year=academic_year, term_number=term_number).first()
        config = _normalize_assessment_config(term, getattr(term, 'assessment_config', None) or {})
        exam_types = list(ExamType.objects.filter(id__in=config['selected_exam_type_ids']))
        exam_type_map = {exam.id: exam for exam in exam_types}
        config['selected_exam_types'] = [
            {
                'id': exam.id,
                'name': exam.name,
                'exam_type': exam.exam_type,
                'weight': config['weights'].get(str(exam.id)),
            }
            for exam in sorted(exam_types, key=lambda item: config['selected_exam_type_ids'].index(item.id))
        ]
        config['exam_type_map'] = exam_type_map
        return config

    def _grade_for_score(self, score: float, grading_scale_data: list[dict]):
        """
        Returns (grade, points) for a 0-100 score.
        grading_scale_data items may contain: min_score, max_score, grade, points (optional).
        """
        try:
            s = float(score or 0)
        except Exception:
            s = 0.0
        grade = "N/A"
        points = None
        for gs in (grading_scale_data or []):
            try:
                mn = float(gs.get('min_score'))
                mx = float(gs.get('max_score'))
            except Exception:
                continue
            if mn <= s <= mx:
                grade = str(gs.get('grade') or 'N/A')
                pts = gs.get('points', None)
                try:
                    points = int(pts) if pts is not None and str(pts).strip() != '' else None
                except Exception:
                    points = None
                break
        return grade, points

    def _remark_for_score(self, score: float, grading_scale_data: list[dict], *, mode='grade_band'):
        selected_grade = None
        selected_remark = None
        try:
            s = float(score or 0)
        except Exception:
            s = 0.0
        for gs in (grading_scale_data or []):
            try:
                mn = float(gs.get('min_score'))
                mx = float(gs.get('max_score'))
            except Exception:
                continue
            if mn <= s <= mx:
                selected_grade = str(gs.get('grade') or 'N/A')
                selected_remark = str(gs.get('remark') or gs.get('remarks') or gs.get('implication') or '').strip() or None
                break
        if selected_remark and mode == 'grade_band':
            return selected_remark
        if s >= 85:
            return 'Excellent performance'
        if s >= 70:
            return 'Very good performance'
        if s >= 60:
            return 'Good progress'
        if s >= 50:
            return 'Fair performance'
        if s >= 40:
            return 'Needs more support'
        return 'Below expectation'

    def _grading_scale_for_student(self, student):
        grading_scale = GradingScale.objects.filter(school_class=student.current_class, is_default=False).first()
        if not grading_scale:
            grading_scale = GradingScale.objects.filter(is_default=True).first()
        return grading_scale.scale_data if grading_scale else []

    def _group_student_term_marks(self, student, term_number, academic_year):
        marks = list(
            Mark.objects.filter(student=student, term=term_number, year=academic_year)
            .select_related('exam_type')
            .order_by('subject', 'exam_type__name', 'id')
        )
        assessment_config = self._term_assessment_config(academic_year, term_number)
        selected_ids = [int(x) for x in assessment_config.get('selected_exam_type_ids', [])]
        selected_set = set(selected_ids)
        weight_map = assessment_config.get('weights', {})
        grouped = {}
        for mark in marks:
            subject_key = str(getattr(mark, 'subject', '') or '').strip()
            if not subject_key:
                continue
            bucket = grouped.setdefault(subject_key, {
                'subject': subject_key,
                'scores': [],
                'exam_types': [],
                'remarks': [],
                'weighted_total': 0.0,
                'weight_used': 0.0,
            })
            score = float(getattr(mark, 'score', 0) or 0)
            bucket['scores'].append(score)
            exam_name = getattr(getattr(mark, 'exam_type', None), 'name', None) or 'Term entry'
            bucket['exam_types'].append(exam_name)
            exam_id = getattr(mark, 'exam_type_id', None)
            if exam_id and exam_id in selected_set:
                try:
                    weight = float(weight_map.get(str(int(exam_id)), 0))
                except Exception:
                    weight = 0.0
                bucket['weighted_total'] += (score * weight)
                bucket['weight_used'] += weight
            remark = str(getattr(mark, 'remarks', '') or '').strip()
            if remark:
                bucket['remarks'].append(remark)

        rows = []
        for _, bucket in sorted(grouped.items(), key=lambda item: item[0].lower()):
            if bucket['weight_used'] > 0:
                avg_score = round(bucket['weighted_total'] / bucket['weight_used'], 2)
            else:
                avg_score = round(sum(bucket['scores']) / len(bucket['scores']), 2) if bucket['scores'] else 0.0
            rows.append({
                'subject': bucket['subject'],
                'score': avg_score,
                'exam_count': len(bucket['scores']),
                'exam_types': bucket['exam_types'],
                'remarks': ' | '.join(bucket['remarks'][:3]),
            })
        return marks, rows, assessment_config

    def _subject_analytics(self, subject_rows, grading_scale_data, *, remark_mode='grade_band'):
        enriched = []
        total_points = 0
        points_known = False
        for row in subject_rows:
            grade, pts = self._grade_for_score(row['score'], grading_scale_data)
            if pts is not None:
                points_known = True
                total_points += int(pts)
            enriched.append({
                'subject': row['subject'],
                'score': float(row['score']),
                'max_score': 100,
                'percentage': float(row['score']),
                'grade': grade,
                'points': pts,
                'remarks': row.get('remarks') or self._remark_for_score(float(row['score']), grading_scale_data, mode=remark_mode),
                'exam_count': int(row.get('exam_count') or 0),
                'exam_types': row.get('exam_types') or [],
            })
        return enriched, (int(total_points) if points_known else None)

    def _term_average_for_student(self, student, academic_year, term_number):
        _, rows, _ = self._group_student_term_marks(student, term_number, academic_year)
        if not rows:
            return None
        return round(sum(row['score'] for row in rows) / len(rows), 2)

    def _yearly_average_for_student(self, student, academic_year):
        averages = []
        term_breakdown = []
        for term_number in [1, 2, 3]:
            avg = self._term_average_for_student(student, academic_year, term_number)
            term_breakdown.append({'term_number': term_number, 'average': avg})
            if avg is not None:
                averages.append(avg)
        yearly_average = round(sum(averages) / len(averages), 2) if averages else None
        return yearly_average, term_breakdown

    def _attendance_impact_label(self, attendance_percentage):
        pct = float(attendance_percentage or 0)
        if pct >= 90:
            return 'Strong attendance support'
        if pct >= 75:
            return 'Attendance is acceptable'
        if pct >= 60:
            return 'Attendance may be affecting performance'
        return 'Low attendance is a risk factor'

    def _class_position_for_student(self, student, term_number, academic_year):
        peers = Student.objects.filter(current_class=student.current_class, section=student.section, status='active')
        ranked = []
        for peer in peers:
            _, rows, _ = self._group_student_term_marks(peer, term_number, academic_year)
            if not rows:
                continue
            avg = sum(r['score'] for r in rows) / len(rows)
            ranked.append({'student_id': peer.id, 'avg_score': avg})
        ranked.sort(key=lambda item: item['avg_score'], reverse=True)
        for idx, row in enumerate(ranked, start=1):
            if row['student_id'] == student.id:
                return idx
        return 0

    def _attendance_percentage(self, student, academic_term):
        total_school_days = 100
        days_present = Attendance.objects.filter(
            student=student,
            date__range=(academic_term.start_date, academic_term.end_date),
            status__iexact='present',
        ).count()
        return (days_present / total_school_days) * 100 if total_school_days > 0 else 0

    def _strengths_and_weaknesses(self, enriched_rows):
        ordered = sorted(enriched_rows, key=lambda row: row['score'], reverse=True)
        strengths = [
            {'subject': row['subject'], 'score': row['score'], 'grade': row['grade']}
            for row in ordered[:3]
        ]
        weaknesses = [
            {'subject': row['subject'], 'score': row['score'], 'grade': row['grade']}
            for row in sorted(enriched_rows, key=lambda row: row['score'])[:3]
        ]
        return strengths, weaknesses

    def _class_level_analytics(self, school_class, term_number, academic_year, *, section=None):
        students = Student.objects.filter(current_class=school_class, status='active')
        if section:
            students = students.filter(section=section)
        try:
            academic_term = AcademicTerm.objects.get(term_number=term_number, academic_year=academic_year)
        except AcademicTerm.DoesNotExist:
            academic_term = None

        assessment_config = self._term_assessment_config(academic_year, term_number)
        threshold = float(assessment_config.get('promotion_threshold', 50) or 50)
        previous_term = int(term_number) - 1 if int(term_number) > 1 else None
        subject_buckets = {}
        student_rows = []
        for student in students:
            _, subject_rows, _ = self._group_student_term_marks(student, term_number, academic_year)
            if not subject_rows:
                continue
            term_average = round(sum(row['score'] for row in subject_rows) / len(subject_rows), 2)
            previous_average = self._term_average_for_student(student, academic_year, previous_term) if previous_term else None
            trend_delta = round(term_average - float(previous_average or 0), 2) if previous_average is not None else None
            attendance_percentage = self._attendance_percentage(student, academic_term) if academic_term else 0
            student_rows.append({
                'student_id': student.id,
                'student_name': f"{student.first_name} {student.last_name}".strip(),
                'student_system_id': student.student_id,
                'section': student.section,
                'term_average': term_average,
                'previous_term_average': previous_average,
                'trend_delta': trend_delta,
                'attendance_percentage': round(float(attendance_percentage or 0), 2),
                'attendance_impact': self._attendance_impact_label(attendance_percentage),
            })
            for row in subject_rows:
                bucket = subject_buckets.setdefault(row['subject'], [])
                bucket.append(float(row['score'] or 0))

        class_average = round(sum(row['term_average'] for row in student_rows) / len(student_rows), 2) if student_rows else 0
        ranked_students = sorted(student_rows, key=lambda row: row['term_average'], reverse=True)
        for idx, row in enumerate(ranked_students, start=1):
            row['class_position'] = idx

        top_improvers = [
            row for row in sorted(
                [item for item in ranked_students if item['trend_delta'] is not None],
                key=lambda item: item['trend_delta'],
                reverse=True,
            )[:5]
        ]
        at_risk_students = []
        for row in sorted(ranked_students, key=lambda item: item['term_average']):
            risk_reasons = []
            if row['term_average'] < threshold:
                risk_reasons.append('Below promotion threshold')
            if row['attendance_percentage'] < 75:
                risk_reasons.append('Attendance concern')
            if risk_reasons:
                at_risk_students.append({**row, 'risk_reasons': risk_reasons})
        subject_heatmap = []
        for subject, scores in sorted(subject_buckets.items(), key=lambda item: item[0].lower()):
            if not scores:
                continue
            avg_score = round(sum(scores) / len(scores), 2)
            pass_rate = round((sum(1 for score in scores if score >= threshold) / len(scores)) * 100, 2)
            subject_heatmap.append({
                'subject': subject,
                'average_score': avg_score,
                'highest_score': round(max(scores), 2),
                'lowest_score': round(min(scores), 2),
                'pass_rate': pass_rate,
                'performance_band': self._attendance_impact_label(avg_score),
            })

        strongest_subject = max(subject_heatmap, key=lambda item: item['average_score']) if subject_heatmap else None
        weakest_subject = min(subject_heatmap, key=lambda item: item['average_score']) if subject_heatmap else None
        return {
            'class_id': school_class.id,
            'class_level': school_class.level,
            'section': section,
            'term_number': int(term_number),
            'academic_year': int(academic_year),
            'students_with_results': len(ranked_students),
            'class_average': class_average,
            'promotion_threshold': threshold,
            'top_improvers': top_improvers,
            'at_risk_students': at_risk_students[:8],
            'subject_heatmap': subject_heatmap,
            'strongest_subject': strongest_subject,
            'weakest_subject': weakest_subject,
        }

    @action(detail=False, methods=['get'], url_path=r'generate/(?P<student_id>\d+)/(?P<term_number>\d+)/(?P<academic_year>\d+)')
    def generate_single_report_card(self, request, student_id, term_number, academic_year):
        try:
            student = Student.objects.get(id=student_id)
            academic_term = AcademicTerm.objects.get(term_number=term_number, academic_year=academic_year)
        except (Student.DoesNotExist, AcademicTerm.DoesNotExist):
            return Response({'detail': 'Student or Academic Term not found.'}, status=status.HTTP_404_NOT_FOUND)
        
        # Permissions check: Parents/Students can only view their own report cards
        # Note: Student accounts are not linked to Student records in this codebase yet.
        try:
            role = request.user.profile.role
            parent_phone = request.user.profile.phone_number
        except UserProfile.DoesNotExist:
            role = 'superadmin' if request.user.is_superuser else None
            parent_phone = None

        if role == 'parent':
            linked = StudentGuardianLink.objects.filter(parent_user=request.user, student=student, is_active=True).exists()
            phone_ok = bool(parent_phone and parent_phone in [student.parent_phone, student.parent_phone2])
            if not (linked or phone_ok):
                return Response({'detail': "Permission denied to view this student's report card."}, status=status.HTTP_403_FORBIDDEN)
        if role == 'student':
            # Convention: student portal username == Student.student_id
            if (request.user.username or '').strip() != student.student_id:
                return Response({'detail': "Permission denied to view another student's report card."}, status=status.HTTP_403_FORBIDDEN)

        # Results hold due to fees (only enforced for parent/student views).
        if role in ['parent', 'student']:
            inv = Invoice.objects.filter(student=student, academic_year=academic_year, term_number=term_number).first()
            if inv and getattr(inv, 'results_blocked', False):
                msg = inv.results_block_reason or 'Results are temporarily unavailable. Please clear outstanding fees.'
                return Response({'detail': msg}, status=status.HTTP_403_FORBIDDEN)
            

        raw_marks, subject_rows, assessment_config = self._group_student_term_marks(student, term_number, academic_year)
        if not raw_marks:
            return Response({'detail': 'No marks found for this student in the specified term.'}, status=status.HTTP_404_NOT_FOUND)

        overall_average = (sum(row['score'] for row in subject_rows) / len(subject_rows)) if subject_rows else 0
        class_position = self._class_position_for_student(student, term_number, academic_year)
        attendance_percentage = self._attendance_percentage(student, academic_term)
        grading_scale_data = self._grading_scale_for_student(student)
        marks_rows, aggregate_points = self._subject_analytics(subject_rows, grading_scale_data, remark_mode=assessment_config.get('remark_mode', 'grade_band'))
        overall_grade, _ = self._grade_for_score(float(overall_average or 0), grading_scale_data)

        pdf_buffer = generate_report_card_pdf(
            student=student,
            academic_term=academic_term,
            marks_rows=marks_rows,
            overall_average=float(overall_average or 0),
            overall_grade=overall_grade,
            aggregate_points=aggregate_points,
            class_position=class_position,
            attendance_percentage=float(attendance_percentage or 0),
            grading_scale_data=grading_scale_data,
        )

        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="report_card_{student.student_id}_Term{term_number}_{academic_year}.pdf"'
        SecurityAuditLog.objects.create(user=request.user, event_type='REPORT_CARD_GENERATED', ip_address=get_client_ip(request), details=f'Report card generated for {student.first_name} {student.last_name} by {request.user.username}.')
        return response

    @action(detail=False, methods=['get'], url_path=r'summary/(?P<student_id>\d+)/(?P<term_number>\d+)/(?P<academic_year>\d+)')
    def summary(self, request, student_id, term_number, academic_year):
        """
        Partial-release endpoint: returns summary metrics even when PDF is held due to fees.
        Parent/student can access their own summary; staff can access any.
        """
        try:
            student = Student.objects.get(id=student_id)
            academic_term = AcademicTerm.objects.get(term_number=term_number, academic_year=academic_year)
        except (Student.DoesNotExist, AcademicTerm.DoesNotExist):
            return Response({'detail': 'Student or Academic Term not found.'}, status=status.HTTP_404_NOT_FOUND)

        role = get_role(request.user)
        if role == 'parent':
            parent_phone = getattr(getattr(request.user, 'profile', None), 'phone_number', None)
            linked = StudentGuardianLink.objects.filter(parent_user=request.user, student=student, is_active=True).exists()
            phone_ok = bool(parent_phone and parent_phone in [student.parent_phone, student.parent_phone2])
            if not (linked or phone_ok):
                return Response({'detail': "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
        if role == 'student':
            if (request.user.username or '').strip() != student.student_id:
                return Response({'detail': "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        raw_marks, subject_rows, assessment_config = self._group_student_term_marks(student, term_number, academic_year)
        if not raw_marks:
            return Response({'detail': 'No marks found for this student in the specified term.'}, status=status.HTTP_404_NOT_FOUND)

        grading_scale_data = self._grading_scale_for_student(student)
        marks_rows, aggregate_points = self._subject_analytics(subject_rows, grading_scale_data, remark_mode=assessment_config.get('remark_mode', 'grade_band'))
        overall_average = (sum(row['score'] for row in subject_rows) / len(subject_rows)) if subject_rows else 0
        overall_grade, _ = self._grade_for_score(float(overall_average or 0), grading_scale_data)
        class_position = self._class_position_for_student(student, term_number, academic_year)
        attendance_percentage = self._attendance_percentage(student, academic_term)
        strengths, weaknesses = self._strengths_and_weaknesses(marks_rows)
        yearly_average, yearly_term_breakdown = self._yearly_average_for_student(student, int(academic_year))
        previous_term = int(term_number) - 1 if int(term_number) > 1 else None
        previous_term_average = self._term_average_for_student(student, int(academic_year), previous_term) if previous_term else None
        trend_delta = round(float(overall_average or 0) - float(previous_term_average or 0), 2) if previous_term_average is not None else None

        inv = Invoice.objects.filter(student=student, academic_year=academic_year, term_number=term_number).first()
        held = bool(inv and getattr(inv, 'results_blocked', False)) if role in ['parent', 'student'] else False
        return Response({
            'student_id': student.id,
            'student_system_id': student.student_id,
            'student_name': f"{student.first_name} {student.last_name}".strip(),
            'academic_year': int(academic_year),
            'term_number': int(term_number),
            'overall_average': float(overall_average or 0),
            'overall_grade': overall_grade,
            'aggregate_points': aggregate_points,
            'class_position': class_position,
            'attendance_percentage': float(attendance_percentage or 0),
            'subjects_count': len(subject_rows),
            'exam_entries_count': len(raw_marks),
            'strengths': strengths,
            'weaknesses': weaknesses,
            'subject_breakdown': marks_rows,
            'automatic_remark': self._remark_for_score(float(overall_average or 0), grading_scale_data, mode=assessment_config.get('remark_mode', 'grade_band')),
            'trend_from_previous_term': {
                'previous_term_number': previous_term,
                'previous_term_average': previous_term_average,
                'delta': trend_delta,
            },
            'attendance_impact': self._attendance_impact_label(attendance_percentage),
            'yearly_average': yearly_average,
            'yearly_term_breakdown': yearly_term_breakdown,
            'assessment_config': {
                'selected_exam_types': assessment_config.get('selected_exam_types', []),
                'promotion_threshold': assessment_config.get('promotion_threshold', 50),
                'remark_mode': assessment_config.get('remark_mode', 'grade_band'),
            },
            'results_blocked': held,
            'results_block_reason': (inv.results_block_reason if inv else None),
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path=r'class-analytics/(?P<class_id>\d+)/(?P<term_number>\d+)/(?P<academic_year>\d+)')
    def class_analytics(self, request, class_id, term_number, academic_year):
        try:
            school_class = SchoolClass.objects.get(id=class_id)
            AcademicTerm.objects.get(term_number=term_number, academic_year=academic_year)
        except SchoolClass.DoesNotExist:
            return Response({'detail': 'Class not found.'}, status=status.HTTP_404_NOT_FOUND)
        except AcademicTerm.DoesNotExist:
            return Response({'detail': 'Academic term not found.'}, status=status.HTTP_404_NOT_FOUND)

        section = str(request.query_params.get('section') or '').strip().upper() or None
        data = self._class_level_analytics(school_class, int(term_number), int(academic_year), section=section)
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='email-all-parents')
    def email_all_parents(self, request):
        class_id = request.data.get('class_id')
        term_number = request.data.get('term_number')
        academic_year = request.data.get('academic_year')

        if not all([class_id, term_number, academic_year]):
            return Response({'detail': 'Missing class, term, or academic year.'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            school_class = SchoolClass.objects.get(id=class_id)
            academic_term = AcademicTerm.objects.get(term_number=term_number, academic_year=academic_year)
        except (SchoolClass.DoesNotExist, AcademicTerm.DoesNotExist):
            return Response({'detail': 'Class or Academic Term not found.'}, status=status.HTTP_404_NOT_FOUND)

        students_in_class = Student.objects.filter(current_class=school_class, status='active')
        emails_sent_count = 0
        not_emailed_students = []

        for student in students_in_class:
            parent_profile = UserProfile.objects.filter(user__first_name=student.parent_name, role='parent').first() # Simplified lookup
            if parent_profile and parent_profile.email_address:
                raw_marks, subject_rows, assessment_config = self._group_student_term_marks(student, term_number, academic_year)
                if raw_marks:
                    overall_average = (sum(row['score'] for row in subject_rows) / len(subject_rows)) if subject_rows else 0
                    class_position = self._class_position_for_student(student, term_number, academic_year)
                    attendance_percentage = self._attendance_percentage(student, academic_term)
                    grading_scale_data = self._grading_scale_for_student(student)
                    marks_rows, aggregate_points = self._subject_analytics(subject_rows, grading_scale_data, remark_mode=assessment_config.get('remark_mode', 'grade_band'))
                    overall_grade, _ = self._grade_for_score(float(overall_average or 0), grading_scale_data)
 
                    pdf_buffer = generate_report_card_pdf( 
                        student=student, 
                        academic_term=academic_term, 
                        marks_rows=marks_rows, 
                        overall_average=float(overall_average or 0), 
                        overall_grade=overall_grade, 
                        aggregate_points=aggregate_points, 
                        class_position=class_position, 
                        attendance_percentage=float(attendance_percentage or 0), 
                        grading_scale_data=grading_scale_data 
                    ) 
                    
                    email_subject = f'Bitende Junior School - {student.first_name} {student.last_name} Report Card, Term {academic_term.term_number} {academic_year}'
                    email_body = render_to_string('school/emails/report_card_email.html', {
                        'student_name': f'{student.first_name} {student.last_name}',
                        'class_level': school_class.level,
                        'overall_average': overall_average,
                        'class_position': class_position,
                        'next_term_start_date': academic_term.end_date + timedelta(days=academic_term.holiday_break_days) # Simplified next term start date
                    })

                    # Attach PDF to email
                    from django.core.mail import EmailMessage
                    email_message = EmailMessage(email_subject, email_body, settings.DEFAULT_FROM_EMAIL, [parent_profile.email_address])
                    email_message.attach(f'report_card_{student.student_id}_Term{term_number}_{academic_year}.pdf', pdf_buffer.getvalue(), 'application/pdf')
                    email_message.send()

                    emails_sent_count += 1
                    SecurityAuditLog.objects.create(user=request.user, event_type='REPORT_CARD_EMAILED', ip_address=get_client_ip(request), details=f'Report card emailed to {parent_profile.email_address} for student {student.first_name} {student.last_name}.')
                else:
                    not_emailed_students.append(f'{student.first_name} {student.last_name} (No marks)')
            else:
                not_emailed_students.append(f'{student.first_name} {student.last_name} (No parent email)')
        
        return Response({
            'detail': f'Successfully sent {emails_sent_count} report cards.',
            'not_emailed': not_emailed_students
        }, status=status.HTTP_200_OK)

class GradingScaleViewSet(viewsets.ModelViewSet):
    queryset = GradingScale.objects.all()
    serializer_class = GradingScaleSerializer
    permission_classes = [permissions.IsAuthenticated, CanManageGrading]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=False, methods=['post'], url_path='set-default')
    def set_default_grading_scale(self, request):
        grading_scale_id = request.data.get('id')
        if not grading_scale_id:
            return Response({'detail': 'Grading scale ID is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with transaction.atomic():
                # Set all others to not default
                GradingScale.objects.update(is_default=False)
                # Set the selected one as default
                grading_scale = GradingScale.objects.get(id=grading_scale_id)
                grading_scale.is_default = True
                grading_scale.save()
                SecurityAuditLog.objects.create(user=request.user, event_type='DEFAULT_GRADING_SCALE_SET', ip_address=get_client_ip(request), details=f'Default grading scale set to {grading_scale.name} by {request.user.username}.')
            return Response({'detail': f'Grading scale {grading_scale.name} set as default.'}, status=status.HTTP_200_OK)
        except GradingScale.DoesNotExist:
            return Response({'detail': 'Grading scale not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            SecurityAuditLog.objects.create(user=request.user, event_type='DEFAULT_GRADING_SCALE_SET_FAILED', ip_address=get_client_ip(request), details=f'Failed to set default grading scale: {e}')
            return Response({'detail': f'Error setting default grading scale: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SecurityAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SecurityAuditLog.objects.all().order_by('-timestamp')
    serializer_class = SecurityAuditLogSerializer
    permission_classes = [IsSuperUser]

    def get_queryset(self):
        qs = super().get_queryset()
        event_type = (self.request.query_params.get('event_type') or '').strip()
        q = (self.request.query_params.get('q') or '').strip()
        user_id = (self.request.query_params.get('user_id') or '').strip()
        since_days = (self.request.query_params.get('since_days') or '').strip()
        if event_type:
            qs = qs.filter(event_type__icontains=event_type)
        if user_id.isdigit():
            qs = qs.filter(user_id=int(user_id))
        if since_days.isdigit():
            try:
                days = int(since_days)
                if days > 0:
                    qs = qs.filter(timestamp__gte=(timezone.now() - timedelta(days=days)))
            except Exception:
                pass
        if q:
            qs = qs.filter(
                Q(event_type__icontains=q)
                | Q(details__icontains=q)
                | Q(user__username__icontains=q)
            )

        # Optional limit for the SPA.
        lim = (self.request.query_params.get('limit') or '').strip()
        if lim.isdigit():
            try:
                n = int(lim)
                if 1 <= n <= 500:
                    qs = qs[:n]
            except Exception:
                pass
        return qs


class APICredentialViewSet(viewsets.ModelViewSet):
    queryset = APICredential.objects.all().order_by('-updated_at')
    serializer_class = APICredentialSerializer
    permission_classes = [IsSuperUser]

    def get_permissions(self):
        if getattr(self, 'action', None) in ['health', 'history']:
            return [IsFinanceUser()]
        return [permission() for permission in self.permission_classes]

    @action(detail=False, methods=['get'], url_path='health')
    def health(self, request):
        return Response(_build_credential_health_summary())

    @action(detail=False, methods=['get'], url_path='history')
    def history(self, request):
        svc = (request.query_params.get('service_name') or '').strip()
        credential_q = (request.query_params.get('credential') or '').strip()
        failures_only = _truthy(request.query_params.get('failures_only'))
        limit_q = (request.query_params.get('limit') or '').strip()
        limit = int(limit_q) if limit_q.isdigit() else 50
        limit = max(1, min(limit, 200))

        qs = APICredentialHealthLog.objects.select_related('credential', 'verified_by').all()
        if svc:
            qs = qs.filter(service_name=svc)
        if credential_q.isdigit():
            qs = qs.filter(credential_id=int(credential_q))
        if failures_only:
            qs = qs.filter(is_ok=False)
        return Response(APICredentialHealthLogSerializer(qs[:limit], many=True).data)

    @action(detail=True, methods=['post'], url_path='verify')
    def verify(self, request, pk=None):
        """
        Best-effort verification of credentials.
        Some providers require outbound network access; when unavailable, we still validate required fields.
        """
        cred = self.get_object()
        svc = cred.service_name

        def _record(is_ok: bool, detail: str, extra: dict | None):
            cred.last_verified_at = timezone.now()
            cred.last_verify_ok = bool(is_ok)
            cred.last_verify_detail = str(detail or '')
            cred.last_verify_extra = extra or {}
            cred.save(update_fields=['last_verified_at', 'last_verify_ok', 'last_verify_detail', 'last_verify_extra', 'updated_at'])
            APICredentialHealthLog.objects.create(
                credential=cred,
                service_name=cred.service_name,
                verified_by=request.user,
                is_ok=bool(is_ok),
                detail=str(detail or ''),
                extra=extra or {},
                verified_at=cred.last_verified_at,
            )

            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='API_CREDENTIAL_VERIFY_OK' if is_ok else 'API_CREDENTIAL_VERIFY_FAIL',
                ip_address=get_client_ip(request),
                details=f"{svc}: {detail}",
            )

        def ok(detail, extra=None):
            _record(True, detail, extra or {})
            return Response({'ok': True, 'service': svc, 'detail': detail, 'extra': extra or {}}, status=status.HTTP_200_OK)

        def bad(detail, extra=None, code=status.HTTP_400_BAD_REQUEST):
            _record(False, detail, extra or {})
            extra_payload = extra or {}
            friendly_detail = detail
            nested_error = None
            if isinstance(extra_payload, dict):
                nested_error = extra_payload.get('error') or extra_payload.get('response')
            if nested_error:
                friendly_detail = f'{detail} {nested_error}'
            return Response({'ok': False, 'service': svc, 'detail': friendly_detail, 'extra': extra_payload}, status=code)

        def parse_json_response(resp):
            try:
                data = resp.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                return data
            return {'text': (getattr(resp, 'text', '') or '')[:500]}

        def extract_access_token(data):
            if not isinstance(data, dict):
                return None
            token = data.get('access_token')
            if token:
                return token
            nested = data.get('data')
            if isinstance(nested, dict):
                return nested.get('access_token') or nested.get('token')
            return data.get('token')

        # Field presence checks first.
        if svc == 'google_oauth':
            if not cred.client_id or not cred.client_secret:
                return bad('Missing client_id or client_secret.')
            return ok('Google OAuth fields present. Live verification requires OAuth flow and is not performed here.')

        if svc == 'twilio_sms':
            if not cred.client_id or not cred.client_secret:
                return bad('Missing Account SID (client_id) or Auth Token (client_secret).')
            try:
                from twilio.rest import Client
                client = Client(cred.client_id, cred.client_secret)
                # Minimal live check: fetch account record.
                acc = client.api.accounts(cred.client_id).fetch()
                return ok('Twilio credentials verified.', {'status': getattr(acc, 'status', None), 'friendly_name': getattr(acc, 'friendly_name', None)})
            except Exception as e:
                return bad('Twilio live verification failed (network or invalid credentials).', {'error': str(e)}, code=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if svc == 'mtn_momo':
            x = cred.extra_data or {}
            api_user = (cred.client_id or '').strip()
            api_secret = (cred.client_secret or '').strip()
            subscription_key = (cred.api_key or '').strip()
            environment = (x.get('environment') or 'sandbox').strip().lower()
            product = (x.get('product') or 'collection').strip().lower() or 'collection'
            base_url = (x.get('base_url') or '').strip().rstrip('/')
            token_path = (x.get('token_path') or f'/{product}/token/').strip()

            missing = []
            if not api_user:
                missing.append('api_user')
            if not api_secret:
                missing.append('api_secret')
            if not subscription_key:
                missing.append('subscription_key')
            if missing:
                return bad('Missing MTN MoMo fields.', {'missing': missing})

            if not base_url:
                if environment in ['sandbox', 'test', 'uat']:
                    base_url = 'https://sandbox.momodeveloper.mtn.com'
                else:
                    return bad('Missing MTN base_url for this environment.', {'missing': ['base_url'], 'environment': environment})

            if not token_path.startswith('/'):
                token_path = '/' + token_path

            auth_value = base64.b64encode(f'{api_user}:{api_secret}'.encode('utf-8')).decode('ascii')
            headers = {
                'Authorization': f'Basic {auth_value}',
                'Ocp-Apim-Subscription-Key': subscription_key,
                'Accept': 'application/json',
            }
            if environment:
                headers['X-Target-Environment'] = environment

            try:
                r = requests.post(f'{base_url}{token_path}', headers=headers, timeout=8)
                payload = parse_json_response(r)
                if r.status_code == 200:
                    access_token = extract_access_token(payload)
                    return ok(
                        'MTN MoMo token request succeeded.',
                        {
                            'environment': environment,
                            'product': product,
                            'base_url': base_url,
                            'token_path': token_path,
                            'has_access_token': bool(access_token),
                            'expires_in': payload.get('expires_in'),
                        },
                    )
                return bad(
                    'MTN MoMo token request failed.',
                    {
                        'environment': environment,
                        'product': product,
                        'base_url': base_url,
                        'token_path': token_path,
                        'status_code': r.status_code,
                        'response': payload,
                    },
                    code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            except Exception as e:
                return bad(
                    'MTN MoMo live verification failed (network or invalid credentials).',
                    {
                        'environment': environment,
                        'product': product,
                        'base_url': base_url,
                        'token_path': token_path,
                        'error': str(e),
                    },
                    code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

        if svc == 'airtel_money':
            x = cred.extra_data or {}
            client_id = (cred.client_id or '').strip()
            client_secret = (cred.client_secret or '').strip()
            api_key = (cred.api_key or '').strip()
            environment = (x.get('environment') or '').strip().lower()
            base_url = (x.get('base_url') or '').strip().rstrip('/')
            token_url = (x.get('token_url') or '').strip()
            if not token_url and base_url:
                token_url = base_url + '/auth/oauth2/token'

            auth_style = (x.get('auth_style') or 'body').strip().lower()
            payload_format = (x.get('payload_format') or 'json').strip().lower()
            grant_type = (x.get('grant_type') or 'client_credentials').strip() or 'client_credentials'
            country = (x.get('country') or '').strip()
            currency = (x.get('currency') or '').strip()

            missing = []
            if not client_id:
                missing.append('client_id')
            if not client_secret:
                missing.append('client_secret')
            if not token_url:
                missing.append('token_url')
            if missing:
                return bad('Missing Airtel Money fields.', {'missing': missing})

            headers = {'Accept': 'application/json'}
            if country:
                headers['X-Country'] = country
            if currency:
                headers['X-Currency'] = currency

            if auth_style == 'basic':
                auth_value = base64.b64encode(f'{client_id}:{client_secret}'.encode('utf-8')).decode('ascii')
                headers['Authorization'] = f'Basic {auth_value}'
                body = {'grant_type': grant_type}
                if api_key:
                    body['api_key'] = api_key
            else:
                body = {
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'grant_type': grant_type,
                }
                if api_key:
                    body['api_key'] = api_key

            try:
                if payload_format == 'form':
                    r = requests.post(token_url, data=body, headers=headers, timeout=8)
                else:
                    headers['Content-Type'] = 'application/json'
                    r = requests.post(token_url, json=body, headers=headers, timeout=8)
                payload = parse_json_response(r)
                if 200 <= r.status_code < 300:
                    access_token = extract_access_token(payload)
                    return ok(
                        'Airtel Money token request succeeded.',
                        {
                            'environment': environment,
                            'token_url': token_url,
                            'auth_style': auth_style,
                            'payload_format': payload_format,
                            'has_access_token': bool(access_token),
                            'expires_in': payload.get('expires_in'),
                        },
                    )
                return bad(
                    'Airtel Money token request failed.',
                    {
                        'environment': environment,
                        'token_url': token_url,
                        'auth_style': auth_style,
                        'payload_format': payload_format,
                        'status_code': r.status_code,
                        'response': payload,
                    },
                    code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            except Exception as e:
                return bad(
                    'Airtel Money live verification failed (network or invalid credentials).',
                    {
                        'environment': environment,
                        'token_url': token_url,
                        'auth_style': auth_style,
                        'payload_format': payload_format,
                        'error': str(e),
                    },
                    code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

        if svc == 'email_smtp':
            # We store host/password in client_id/client_secret; the rest lives in extra_data.
            x = cred.extra_data or {}
            host = (cred.client_id or '').strip()
            password = (cred.client_secret or '').strip()
            port = (x.get('port') or '').strip() if isinstance(x.get('port'), str) else x.get('port')
            username = (x.get('username') or '').strip()
            missing = []
            if not host:
                missing.append('host')
            if not port:
                missing.append('port')
            if not username:
                missing.append('username')
            if not password:
                missing.append('password')
            if missing:
                return bad('Missing SMTP fields (host/password + extra fields).', {'missing': missing})
            use_tls = str(x.get('use_tls') or 'true').strip().lower() not in ('0', 'false', 'no')
            try:
                import smtplib

                with smtplib.SMTP(host, int(port), timeout=10) as server:
                    server.ehlo()
                    if use_tls:
                        server.starttls()
                        server.ehlo()
                    server.login(username, password)
                return ok('SMTP login succeeded.', {'host': host, 'port': int(port), 'username': username, 'use_tls': use_tls})
            except Exception as e:
                return bad('SMTP live verification failed (network or invalid credentials).', {'error': str(e), 'host': host, 'port': int(port), 'username': username, 'use_tls': use_tls}, code=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if svc == 'gmail_smtp':
            # Gmail SMTP preset: host/port are standard; require username + app password.
            x = cred.extra_data or {}
            username = (x.get('username') or '').strip()
            password = (cred.client_secret or '').strip()
            if not username or not password:
                return bad('Missing Gmail SMTP fields.', {'missing': [k for k in ['username', 'app_password'] if (k == 'username' and not username) or (k == 'app_password' and not password)]})
            try:
                import smtplib

                with smtplib.SMTP('smtp.gmail.com', 587, timeout=10) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(username, password)
                return ok('Gmail SMTP login succeeded.', {'host': 'smtp.gmail.com', 'port': 587, 'username': username})
            except Exception as e:
                return bad('Gmail SMTP live verification failed (network or invalid credentials).', {'error': str(e), 'host': 'smtp.gmail.com', 'port': 587, 'username': username}, code=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if svc == 'megasms':
            x = cred.extra_data or {}
            url = (x.get('url') or '').strip()
            sender = (x.get('sender') or '').strip()
            api_key = (cred.api_key or '').strip()
            missing = []
            if not url:
                missing.append('url')
            if not api_key:
                missing.append('api_key')
            if not sender:
                missing.append('sender')
            if missing:
                return bad('Missing MegaSMS fields.', {'missing': missing})
            return ok('MegaSMS fields present. Live verification depends on server internet access.')

        if svc == 'zapier_webhook':
            x = cred.extra_data or {}
            url = (x.get('url') or cred.client_id or '').strip()
            if not url:
                return bad('Missing webhook URL. Put it in Extra Fields -> url (or Client ID).')
            return ok('Webhook URL present.')

        if svc == 'openai':
            if not cred.api_key:
                return bad('Missing api_key for OpenAI.')
            base_url = (cred.extra_data or {}).get('base_url') if isinstance(cred.extra_data, dict) else None
            base_url = (base_url or 'https://api.openai.com').rstrip('/')
            try:
                r = requests.get(
                    base_url + '/v1/models',
                    headers={'Authorization': f'Bearer {cred.api_key}', 'Accept': 'application/json'},
                    timeout=6,
                )
                if r.status_code == 200:
                    return ok('OpenAI API reachable and key accepted.', {'base_url': base_url})
                return bad('OpenAI key rejected or API unreachable.', {'status_code': r.status_code, 'base_url': base_url}, code=status.HTTP_422_UNPROCESSABLE_ENTITY)
            except Exception as e:
                return bad('OpenAI live verification failed (network or invalid credentials).', {'error': str(e), 'base_url': base_url}, code=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if svc == 'gemini':
            if not cred.api_key:
                return bad('Missing api_key for Gemini.')
            try:
                # List models endpoint (API key query param).
                url = 'https://generativelanguage.googleapis.com/v1beta/models'
                r = requests.get(url, params={'key': cred.api_key}, timeout=6)
                if r.status_code == 200:
                    return ok('Gemini API reachable and key accepted.', {})
                return bad('Gemini key rejected or API unreachable.', {'status_code': r.status_code}, code=status.HTTP_422_UNPROCESSABLE_ENTITY)
            except Exception as e:
                return bad('Gemini live verification failed (network or invalid credentials).', {'error': str(e)}, code=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return ok('No verifier implemented for this service yet.')

    @action(detail=True, methods=['post'], url_path='send-test')
    def send_test(self, request, pk=None):
        """
        Best-effort "test send" for comm providers (SMTP/SMS/webhook).
        Payload depends on service:
          - gmail_smtp/email_smtp: { to_email }
          - megasms/twilio_sms: { to_number, message? }
          - zapier_webhook: { payload? }
        """
        cred = self.get_object()
        svc = cred.service_name

        if svc in ['gmail_smtp', 'email_smtp']:
            to_email = ((request.data or {}).get('to_email') or '').strip()
            if not to_email:
                return Response({'detail': 'to_email is required.'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                import smtplib
                from email.message import EmailMessage

                x = cred.extra_data or {}
                host = (cred.client_id or '').strip() if svc == 'email_smtp' else 'smtp.gmail.com'
                port = x.get('port') if svc == 'email_smtp' else 587
                try:
                    port = int(port)
                except Exception:
                    port = 587
                username = (x.get('username') or '').strip()
                password = (cred.client_secret or '').strip()
                use_tls = True
                if svc == 'email_smtp' and str(x.get('use_tls') or 'true').lower() in ['0', 'false', 'no']:
                    use_tls = False

                if not username or not password or not host:
                    return Response({'detail': 'SMTP fields incomplete. Verify credential fields.'}, status=status.HTTP_400_BAD_REQUEST)

                msg = EmailMessage()
                msg['Subject'] = f'Test email ({svc})'
                msg['From'] = username
                msg['To'] = to_email
                msg.set_content('This is a test email from the School Management System SMTP credential checker.')

                with smtplib.SMTP(host, port, timeout=10) as s:
                    s.ehlo()
                    if use_tls:
                        s.starttls()
                        s.ehlo()
                    s.login(username, password)
                    s.send_message(msg)
                SecurityAuditLog.objects.create(user=request.user, event_type='API_CREDENTIAL_TEST_SENT', ip_address=get_client_ip(request), details=f'{svc}: test email sent to {to_email}.')
                return Response({'ok': True, 'detail': f'Test email sent to {to_email}.'}, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({'ok': False, 'detail': f'Test email failed: {e}'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if svc in ['megasms', 'twilio_sms']:
            to_number = ((request.data or {}).get('to_number') or '').strip()
            message = ((request.data or {}).get('message') or '').strip() or 'Test SMS from School Management System.'
            if not to_number:
                return Response({'detail': 'to_number is required.'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                if svc == 'twilio_sms':
                    # Use the existing helper (which prefers MegaSMS when configured globally).
                    ok = send_sms(to_number, message)
                    if not ok:
                        raise Exception('send_sms returned False')
                    SecurityAuditLog.objects.create(user=request.user, event_type='API_CREDENTIAL_TEST_SENT', ip_address=get_client_ip(request), details=f'{svc}: test SMS sent to {to_number}.')
                    return Response({'ok': True, 'detail': f'Test SMS queued to {to_number}.'}, status=status.HTTP_200_OK)

                x = cred.extra_data or {}
                url = (x.get('url') or '').strip()
                sender = (x.get('sender') or '').strip()
                api_key = (cred.api_key or '').strip()
                if not url or not sender or not api_key:
                    return Response({'detail': 'MegaSMS fields incomplete. Verify credential fields.'}, status=status.HTTP_400_BAD_REQUEST)

                payload = {"api_key": api_key, "to": to_number, "message": message, "sender": sender}
                fmt = (x.get('payload_format') or 'form').strip().lower()
                if fmt == 'json':
                    r = requests.post(url, json=payload, timeout=10)
                else:
                    r = requests.post(url, data=payload, timeout=10)
                if 200 <= int(r.status_code) < 300:
                    SecurityAuditLog.objects.create(user=request.user, event_type='API_CREDENTIAL_TEST_SENT', ip_address=get_client_ip(request), details=f'{svc}: test SMS sent to {to_number}.')
                    return Response({'ok': True, 'detail': f'Test SMS sent to {to_number}.', 'status_code': r.status_code}, status=status.HTTP_200_OK)
                return Response({'ok': False, 'detail': f'MegaSMS responded with {r.status_code}.', 'response': (r.text or '')[:500]}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            except Exception as e:
                return Response({'ok': False, 'detail': f'Test SMS failed: {e}'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if svc == 'zapier_webhook':
            x = cred.extra_data or {}
            url = (x.get('url') or cred.client_id or '').strip()
            payload = (request.data or {}).get('payload') or {'event': 'test', 'ts': timezone.now().isoformat()}
            if not url:
                return Response({'detail': 'Webhook URL missing.'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                r = requests.post(url, json=payload, timeout=10)
                if 200 <= int(r.status_code) < 300:
                    SecurityAuditLog.objects.create(user=request.user, event_type='API_CREDENTIAL_TEST_SENT', ip_address=get_client_ip(request), details=f'{svc}: test webhook posted.')
                    return Response({'ok': True, 'detail': 'Test webhook sent.', 'status_code': r.status_code}, status=status.HTTP_200_OK)
                return Response({'ok': False, 'detail': f'Webhook responded with {r.status_code}.', 'response': (r.text or '')[:500]}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            except Exception as e:
                return Response({'ok': False, 'detail': f'Test webhook failed: {e}'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response({'detail': 'Test send not supported for this service.'}, status=status.HTTP_400_BAD_REQUEST)


class SubjectViewSet(viewsets.ModelViewSet):
    queryset = Subject.objects.all().order_by('name')
    serializer_class = SubjectSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffAdminOrTeacherReadOnly]


class ClassSubjectViewSet(viewsets.ModelViewSet):
    queryset = ClassSubject.objects.select_related('school_class', 'subject').all().order_by('school_class__level', 'subject__name')
    serializer_class = ClassSubjectSerializer
    permission_classes = [permissions.IsAuthenticated, IsStaffAdminOrTeacherReadOnly]

    def get_queryset(self):
        qs = super().get_queryset()
        class_id = (self.request.query_params.get('school_class') or '').strip()
        if class_id.isdigit():
            qs = qs.filter(school_class_id=int(class_id))
        return qs


def _resolve_document_merge_targets(document, request):
    data = request.data if request.method != 'GET' else request.query_params
    audience = str(data.get('audience') or 'guardians').strip().lower() or 'guardians'
    if audience not in {'guardians', 'students'}:
        raise ValidationError('audience must be guardians or students.')

    student_id = str(data.get('student') or '').strip()
    class_id = str(data.get('school_class') or document.school_class_id or '').strip()
    qs = Student.objects.select_related('current_class').all().order_by('current_class__level', 'section', 'student_id')

    if student_id.isdigit():
        targets = list(qs.filter(id=int(student_id))[:1])
    elif class_id.isdigit():
        targets = list(qs.filter(current_class_id=int(class_id))[:250])
    else:
        targets = []

    return targets, audience


def _role_matches_library_scope(role: str, scope: str) -> bool:
    scope = (scope or 'all').strip().lower()
    role = (role or '').strip().lower()
    if scope == 'all':
        return True
    if scope == 'admin':
        return role in ['superadmin', 'admin', 'headteacher', 'deputy', 'dos']
    return role == scope


def _header_block_for_preset(preset: str, school_name: str) -> str:
    p = (preset or 'standard').strip().lower()
    if p == 'finance':
        return f"<div><strong>{school_name} - Finance Office</strong></div><div>Official Finance Communication</div><hr>"
    if p == 'academic':
        return f"<div><strong>{school_name} - Academic Office</strong></div><div>Official Academic Communication</div><hr>"
    if p == 'minimal':
        return f"<div><strong>{school_name}</strong></div>"
    return f"<div><strong>{school_name}</strong></div><div>Official School Communication</div><hr>"


def _footer_block_for_preset(preset: str, school_name: str) -> str:
    p = (preset or 'standard').strip().lower()
    if p == 'finance':
        return f"<hr><div>Issued by Finance Office, {school_name}</div>"
    if p == 'academic':
        return f"<hr><div>Issued by Academic Office, {school_name}</div>"
    if p == 'minimal':
        return f"<div>{school_name}</div>"
    return f"<hr><div>{school_name} | For support contact the school office.</div>"


def _compose_document_body(document, mapping, rendered_body_template):
    school_name = mapping.get('school_name') or 'Bitende Junior School'
    body_html = sanitize_rich_text_html(rendered_body_template)
    header = _header_block_for_preset(getattr(document, 'header_preset', 'standard'), school_name)
    footer = _footer_block_for_preset(getattr(document, 'footer_preset', 'standard'), school_name)
    signature = ''
    if getattr(document, 'include_signature_block', False):
        signature = (
            "<div style=\"margin-top:24px\"><div>Signature: _________________________</div>"
            "<div>Name: _____________________________</div></div>"
        )
    stamp = ''
    if getattr(document, 'include_school_stamp', False):
        stamp = "<div style=\"margin-top:16px\">[SCHOOL STAMP]</div>"
    merged = f"{header}<div style=\"margin-top:10px\">{body_html}</div>{signature}{stamp}{footer}"
    return sanitize_rich_text_html(merged)


def _student_document_merge_context(student, request, audience='guardians'):
    guardian = _guardian_contacts_for_student(student)
    active_term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number').first()
    branding = get_system_setting('school_branding', {}) or {}
    class_level = getattr(getattr(student, 'current_class', None), 'level', '') or ''
    section = (getattr(student, 'section', None) or '').strip()
    class_label = f"{class_level}{section}" if class_level or section else ''
    recipient_name = guardian['parent_name'] if audience == 'guardians' else f"{student.first_name} {student.last_name}".strip()
    recipient_email = guardian['parent_email'] if audience == 'guardians' else ''
    recipient_phone = guardian['parent_phone'] if audience == 'guardians' else ''
    return {
        'school_name': branding.get('school_name', 'Bitende Junior School') if isinstance(branding, dict) else 'Bitende Junior School',
        'today': timezone.localdate().isoformat(),
        'current_date': timezone.localdate().isoformat(),
        'student_name': f"{student.first_name} {student.last_name}".strip(),
        'student_first_name': student.first_name or '',
        'student_last_name': student.last_name or '',
        'student_id': student.student_id or '',
        'class_level': class_level,
        'section': section,
        'class_label': class_label,
        'parent_name': guardian['parent_name'] or '',
        'parent_phone': guardian['parent_phone'] or '',
        'parent_email': guardian['parent_email'] or '',
        'recipient_name': recipient_name or '',
        'recipient_email': recipient_email or '',
        'recipient_phone': recipient_phone or '',
        'district': getattr(student, 'district', '') or '',
        'gender': getattr(student, 'gender', '') or '',
        'religion': getattr(student, 'religion', '') or '',
        'home_address': getattr(student, 'home_address', '') or '',
        'login_url': request.build_absolute_uri('/'),
        'term_number': getattr(active_term, 'term_number', '') or '',
        'academic_year': getattr(active_term, 'academic_year', '') or '',
    }


def _render_document_merge(document, student, request, audience='guardians'):
    branding = get_system_setting('school_branding', {}) or {}
    school_name = branding.get('school_name') if isinstance(branding, dict) else None
    mapping = _student_document_merge_context(student, request, audience=audience)
    if school_name:
        mapping['school_name'] = school_name
    rendered_title = _safe_format_template(document.title, mapping)
    rendered_body_template = _safe_format_template(document.body, mapping)
    rendered_body_html = _compose_document_body(document, mapping, rendered_body_template)
    rendered_body_text = rich_text_to_plain_text(rendered_body_html or rendered_body_template)
    return {
        'title': rendered_title,
        'body': rendered_body_html or rendered_body_text,
        'body_html': rendered_body_html,
        'body_text': rendered_body_text,
        'student_id': student.student_id,
        'student_name': mapping['student_name'],
        'recipient_name': mapping['recipient_name'],
        'recipient_email': mapping['recipient_email'],
        'recipient_phone': mapping['recipient_phone'],
        'recipient_contact': mapping['recipient_email'] or mapping['recipient_phone'] or '',
        'class_label': mapping['class_label'],
        'date_label': mapping['today'],
        'audience': audience,
    }


def _parse_schedule_datetime(raw_value):
    value = str(raw_value or '').strip()
    if not value:
        return timezone.now()
    dt = parse_datetime(value)
    if not dt:
        raise ValidationError('Invalid scheduled datetime format. Use ISO format.')
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _ack_url(request, token, event_name):
    base = request.build_absolute_uri('/').rstrip('/')
    return f"{base}/api/communication-deliveries/acknowledge/?token={token}&event={event_name}"


def _relative_media_path_from_url(file_url):
    value = str(file_url or '').strip()
    if not value:
        return None
    media_url = str(getattr(settings, 'MEDIA_URL', '/media/') or '/media/').strip()
    if '://' in value:
        return None
    if value.startswith(media_url):
        rel = value[len(media_url):]
    else:
        rel = value.lstrip('/')
    rel = rel.strip().replace('\\', '/').lstrip('/')
    if not rel or '..' in rel.split('/'):
        return None
    return rel


def _apply_uploaded_media_to_field(instance, field_name, file_url):
    rel = _relative_media_path_from_url(file_url)
    if file_url is not None and str(file_url).strip() == '':
        getattr(instance, field_name).delete(save=False)
        setattr(instance, field_name, None)
        instance.save(update_fields=[field_name])
        return None
    if not rel:
        return None
    if not default_storage.exists(rel):
        raise ValidationError('Uploaded file could not be found. Please upload it again.')
    field = getattr(instance, field_name)
    field.name = rel
    instance.save(update_fields=[field_name])
    return rel


def _validate_upload_filename(name):
    raw = str(name or '').strip()
    if not raw:
        raise ValidationError('Uploaded file must have a name.')
    if len(raw) > 180:
        raise ValidationError('Uploaded file name is too long.')
    if re.search(r'[\x00-\x1f<>:"|?*]', raw):
        raise ValidationError('Uploaded file name contains invalid characters.')
    return raw


def _raise_upload_validation_error(message):
    raise ValidationError(message)


def _validate_image_upload_bytes(file_name, payload):
    if not payload:
        _raise_upload_validation_error('Uploaded image is empty.')
    if payload[:2] == b'MZ':
        _raise_upload_validation_error('Executable files are not allowed.')
    fmt = ''
    try:
        with Image.open(io.BytesIO(payload)) as img:
            img.verify()
        with Image.open(io.BytesIO(payload)) as img:
            fmt = (img.format or '').upper()
    except (UnidentifiedImageError, OSError):
        _raise_upload_validation_error('The uploaded image could not be verified.')
    allowed_formats = {'JPEG', 'PNG', 'WEBP', 'GIF'}
    if fmt not in allowed_formats:
        _raise_upload_validation_error('Only JPG, PNG, WEBP, or GIF images are allowed.')
    return fmt.lower()


def _validate_document_upload_bytes(file_name, payload, ext):
    if not payload:
        _raise_upload_validation_error('Uploaded document is empty.')
    if payload[:2] == b'MZ':
        _raise_upload_validation_error('Executable files are not allowed.')

    ext = str(ext or '').lower()
    if ext == 'pdf':
        if not payload.startswith(b'%PDF'):
            _raise_upload_validation_error('The PDF file signature is invalid.')
        return 'pdf'
    if ext == 'docx':
        names = set()
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            _raise_upload_validation_error('The DOCX file is corrupted or invalid.')
        if 'word/document.xml' not in names:
            _raise_upload_validation_error('The DOCX file structure is invalid.')
        return 'docx'
    if ext == 'doc':
        if payload[:8] != b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            _raise_upload_validation_error('The DOC file signature is invalid.')
        return 'doc'
    _raise_upload_validation_error('Unsupported document type.')


def _storage_name_for_upload(prefix, file_name, safe_ext):
    folder = f"{prefix}/{timezone.now().strftime('%Y%m%d')}"
    return f"{folder}/{uuid.uuid4().hex}.{safe_ext}"


def _attempt_delivery(delivery, request, *, force=False):
    campaign = delivery.campaign
    now = timezone.now()
    if not force and delivery.status == 'retry_pending' and delivery.next_attempt_at and delivery.next_attempt_at > now:
        return False

    recipient = delivery.recipient_email if delivery.channel == 'email' else delivery.recipient_phone
    if not recipient:
        delivery.status = 'skipped'
        delivery.last_error = 'Missing recipient contact.'
        delivery.last_attempt_at = now
        delivery.save(update_fields=['status', 'last_error', 'last_attempt_at', 'updated_at'])
        return False

    delivery.attempt_count = int(delivery.attempt_count or 0) + 1
    delivery.last_attempt_at = now
    ok = False
    err = None
    try:
        if delivery.channel == 'email':
            open_url = _ack_url(request, delivery.ack_token, 'opened')
            confirm_url = _ack_url(request, delivery.ack_token, 'confirmed')
            reply_url = _ack_url(request, delivery.ack_token, 'replied')
            ok = bool(send_email(
                subject=delivery.message_subject or campaign.document.title,
                recipient_list=[recipient],
                template_name='school/emails/communication_email.html',
                context={
                    'title': delivery.message_subject or campaign.document.title,
                    'recipient_name': delivery.recipient_name or 'Parent/Guardian',
                    'student_name': f"{getattr(delivery.student, 'first_name', '')} {getattr(delivery.student, 'last_name', '')}".strip(),
                    'student_id': getattr(delivery.student, 'student_id', ''),
                    'class_label': getattr(getattr(delivery.student, 'current_class', None), 'level', ''),
                    'body_html': delivery.message_body,
                    'body': rich_text_to_plain_text(delivery.message_body),
                    'open_url': open_url,
                    'confirm_url': confirm_url,
                    'reply_url': reply_url,
                },
            ))
        else:
            confirm_url = _ack_url(request, delivery.ack_token, 'confirmed')
            text = rich_text_to_plain_text(delivery.message_body)
            ok = bool(send_sms(recipient, f"{delivery.message_subject or campaign.document.title} | {text} | Confirm: {confirm_url}"))
    except Exception as exc:
        ok = False
        err = str(exc)

    if ok:
        delivery.status = 'sent'
        delivery.sent_at = timezone.now()
        delivery.last_error = None
        delivery.next_attempt_at = None
    else:
        if delivery.attempt_count <= int(campaign.retry_limit or 0):
            delivery.status = 'retry_pending'
            delivery.next_attempt_at = timezone.now() + timedelta(minutes=int(campaign.retry_delay_minutes or 30))
            delivery.last_error = err or 'Send failed. Will retry.'
        else:
            delivery.status = 'failed'
            delivery.next_attempt_at = None
            delivery.last_error = err or 'Send failed.'
    delivery.save(update_fields=[
        'attempt_count', 'last_attempt_at', 'status', 'sent_at',
        'last_error', 'next_attempt_at', 'updated_at'
    ])
    return ok


def _seed_campaign_deliveries(campaign, document, targets, request, audience='guardians'):
    created = 0
    for student in targets:
        rendered = _render_document_merge(document, student, request, audience=audience)
        delivery = CommunicationDelivery.objects.create(
            campaign=campaign,
            student=student,
            recipient_name=rendered.get('recipient_name') or None,
            recipient_email=rendered.get('recipient_email') or None,
            recipient_phone=rendered.get('recipient_phone') or None,
            channel=campaign.channel,
            message_subject=rendered.get('title'),
            message_body=rendered.get('body_html') or rendered.get('body_text') or rendered.get('body'),
            status='pending',
        )
        recipient = delivery.recipient_email if campaign.channel == 'email' else delivery.recipient_phone
        if not recipient:
            delivery.status = 'skipped'
            delivery.last_error = 'No recipient contact found.'
            delivery.save(update_fields=['status', 'last_error', 'updated_at'])
        created += 1
    return created


def _refresh_campaign_summary(campaign):
    qs = campaign.deliveries.all()
    sent_like = qs.filter(status__in=['sent', 'opened', 'confirmed', 'replied']).count()
    failed = qs.filter(status='failed').count()
    skipped = qs.filter(status='skipped').count()
    pending = qs.filter(status__in=['pending', 'retry_pending']).count()
    campaign.sent_count = sent_like
    campaign.failed_count = failed
    campaign.skipped_count = skipped
    campaign.last_run_at = timezone.now()
    if pending > 0:
        campaign.status = 'scheduled'
        campaign.finished_at = None
    else:
        campaign.finished_at = timezone.now()
        campaign.status = 'partially_failed' if failed > 0 else 'completed'
    campaign.save(update_fields=[
        'sent_count', 'failed_count', 'skipped_count', 'status',
        'last_run_at', 'finished_at', 'updated_at'
    ])


def _run_campaign(campaign, request, actor=None):
    now = timezone.now()
    campaign.status = 'running'
    if not campaign.started_at:
        campaign.started_at = now
    campaign.last_run_at = now
    campaign.save(update_fields=['status', 'started_at', 'last_run_at', 'updated_at'])

    deliveries = campaign.deliveries.filter(status__in=['pending', 'retry_pending']).order_by('id')
    for delivery in deliveries:
        _attempt_delivery(delivery, request)

    _refresh_campaign_summary(campaign)
    if actor:
        SecurityAuditLog.objects.create(
            user=actor,
            event_type='CAMPAIGN_RUN',
            ip_address=get_client_ip(request),
            details=f'Campaign {campaign.id} executed. status={campaign.status}, sent={campaign.sent_count}, failed={campaign.failed_count}, skipped={campaign.skipped_count}.',
        )


class DocumentDraftViewSet(viewsets.ModelViewSet):
    queryset = DocumentDraft.objects.select_related('created_by', 'school_class', 'subject', 'printed_by').all().order_by('-created_at')
    serializer_class = DocumentDraftSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)
        user = self.request.user
        if role == 'teacher':
            qs = qs.filter(
                Q(created_by=user) |
                Q(workflow_status='published', library_scope__in=['all', 'teacher'])
            )
        elif role == 'bursar':
            qs = qs.filter(
                Q(created_by=user) |
                Q(workflow_status='published', library_scope__in=['all', 'bursar'])
            )
        elif role == 'reception':
            qs = qs.filter(
                Q(created_by=user) |
                Q(workflow_status='published', library_scope__in=['all', 'reception']) |
                Q(workflow_status='published', library_scope='admin')
            )
        elif role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(self.request, self):
            pass
        else:
            return qs.none()

        library_scope = (self.request.query_params.get('library_scope') or '').strip().lower()
        if library_scope:
            qs = qs.filter(library_scope=library_scope)
        workflow_status = (self.request.query_params.get('workflow_status') or '').strip().lower()
        if workflow_status:
            qs = qs.filter(workflow_status=workflow_status)
        template_key = (self.request.query_params.get('template_key') or '').strip()
        if template_key:
            qs = qs.filter(template_key=template_key)

        latest_only = str(self.request.query_params.get('latest') or '').strip().lower() in ('1', 'true', 'yes')
        if latest_only:
            ordered = qs.order_by('template_key', '-version_number', '-id')
            seen = set()
            keep_ids = []
            for doc in ordered:
                key = doc.template_key or f"id:{doc.id}"
                if key in seen:
                    continue
                seen.add(key)
                keep_ids.append(doc.id)
            qs = qs.filter(id__in=keep_ids)
        return qs

    def perform_create(self, serializer):
        role = get_role(self.request.user)
        if role not in ['teacher', 'reception', 'bursar'] and not (IsSuperUser().has_permission(self.request, self) or is_admin_role(role)):
            raise PermissionDenied('Only teachers/admin/reception can create drafts.')
        library_scope = serializer.validated_data.get('library_scope') or 'all'
        if not _role_matches_library_scope(role, library_scope) and not (IsSuperUser().has_permission(self.request, self) or is_admin_role(role)):
            raise PermissionDenied('Your role cannot create templates in this library scope.')
        serializer.save(
            created_by=self.request.user,
            template_key=uuid.uuid4().hex,
            version_number=1,
            workflow_status='draft',
        )

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        doc = self.get_object()
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(request, self)):
            return Response({'detail': 'Only administrators can approve templates.'}, status=status.HTTP_403_FORBIDDEN)
        if doc.workflow_status not in ['draft', 'approved']:
            return Response({'detail': 'Only draft templates can be approved.'}, status=status.HTTP_400_BAD_REQUEST)
        doc.workflow_status = 'approved'
        doc.workflow_notes = (request.data or {}).get('workflow_notes') or doc.workflow_notes
        doc.approved_at = timezone.now()
        doc.approved_by = request.user
        doc.save(update_fields=['workflow_status', 'workflow_notes', 'approved_at', 'approved_by', 'updated_at'])
        return Response(DocumentDraftSerializer(doc).data)

    @action(detail=True, methods=['post'], url_path='publish')
    def publish(self, request, pk=None):
        doc = self.get_object()
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(request, self)):
            return Response({'detail': 'Only administrators can publish templates.'}, status=status.HTTP_403_FORBIDDEN)
        force = _truthy((request.data or {}).get('force'))
        if doc.workflow_status != 'approved' and not force:
            return Response({'detail': 'Template must be approved before publishing.'}, status=status.HTTP_400_BAD_REQUEST)
        doc.workflow_status = 'published'
        if not doc.approved_at:
            doc.approved_at = timezone.now()
            doc.approved_by = request.user
        doc.published_at = timezone.now()
        doc.published_by = request.user
        doc.save(update_fields=['workflow_status', 'approved_at', 'approved_by', 'published_at', 'published_by', 'updated_at'])
        return Response(DocumentDraftSerializer(doc).data)

    @action(detail=True, methods=['post'], url_path='new-version')
    def new_version(self, request, pk=None):
        base = self.get_object()
        role = get_role(request.user)
        if role not in ['teacher', 'reception', 'bursar'] and not (role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(request, self)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        same_key = base.template_key or uuid.uuid4().hex
        last_ver = DocumentDraft.objects.filter(template_key=same_key).aggregate(maxv=Max('version_number')).get('maxv') or 1
        new_doc = DocumentDraft.objects.create(
            created_by=request.user,
            kind=base.kind,
            title=base.title,
            body=base.body,
            school_class=base.school_class,
            subject=base.subject,
            status='draft',
            template_key=same_key,
            version_number=int(last_ver) + 1,
            previous_version=base,
            workflow_status='draft',
            library_scope=base.library_scope,
            header_preset=base.header_preset,
            footer_preset=base.footer_preset,
            include_signature_block=base.include_signature_block,
            include_school_stamp=base.include_school_stamp,
        )
        return Response(DocumentDraftSerializer(new_doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='submit')
    def submit(self, request, pk=None):
        doc = self.get_object()
        role = get_role(request.user)
        if role != 'teacher' and not (IsSuperUser().has_permission(request, self) or is_admin_role(role)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if doc.status not in ['draft', 'rejected']:
            return Response({'detail': 'Only drafts can be submitted.'}, status=status.HTTP_400_BAD_REQUEST)
        doc.status = 'submitted'
        doc.submitted_at = timezone.now()
        doc.save(update_fields=['status', 'submitted_at', 'updated_at'])
        try:
            notify_roles(['reception'], category='system', title='New print draft submitted', message=doc.title, link_page='printdesk', link_object_id=doc.id)
        except Exception:
            pass
        return Response(DocumentDraftSerializer(doc).data)

    @action(detail=True, methods=['post'], url_path='mark-printed')
    def mark_printed(self, request, pk=None):
        doc = self.get_object()
        role = get_role(request.user)
        if role != 'reception' and not IsSuperUser().has_permission(request, self):
            return Response({'detail': 'Only reception/superadmin can mark printed.'}, status=status.HTTP_403_FORBIDDEN)
        doc.status = 'printed'
        doc.printed_at = timezone.now()
        doc.printed_by = request.user
        doc.save(update_fields=['status', 'printed_at', 'printed_by', 'updated_at'])
        try:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='PRINT_DOC_MARKED',
                ip_address=get_client_ip(request),
                details=f'DocumentDraft {doc.id} marked printed.',
            )
        except Exception:
            pass
        return Response(DocumentDraftSerializer(doc).data)

    @action(detail=True, methods=['post'], url_path='preview-merge')
    def preview_merge(self, request, pk=None):
        doc = self.get_object()
        try:
            targets, audience = _resolve_document_merge_targets(doc, request)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if not targets:
            return Response({'detail': 'Choose a student or class before previewing.'}, status=status.HTTP_400_BAD_REQUEST)
        preview = _render_document_merge(doc, targets[0], request, audience=audience)
        return Response({
            'count': len(targets),
            'audience': audience,
            'preview': preview,
        })

    @action(detail=True, methods=['post'], url_path='queue-merge')
    def queue_merge(self, request, pk=None):
        doc = self.get_object()
        role = get_role(request.user)
        if role not in ['teacher', 'reception'] and not (IsSuperUser().has_permission(request, self) or is_admin_role(role)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            targets, audience = _resolve_document_merge_targets(doc, request)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if not targets:
            return Response({'detail': 'Choose a student or class before queuing letters.'}, status=status.HTTP_400_BAD_REQUEST)

        documents = [_render_document_merge(doc, student, request, audience=audience) for student in targets]
        class_id = request.data.get('school_class') or doc.school_class_id
        school_class = SchoolClass.objects.filter(id=class_id).first() if str(class_id or '').isdigit() else doc.school_class
        item = PrintQueueItem.objects.create(
            kind='mail_merge_letter',
            status='queued',
            title=f"{doc.title} ({len(documents)} letter{'s' if len(documents) != 1 else ''})"[:200],
            note=f"Audience: {audience}",
            student=targets[0] if len(targets) == 1 else None,
            payload={
                'documents': documents,
                'document_draft_id': doc.id,
                'audience': audience,
                'school_class_id': school_class.id if school_class else None,
            },
            is_sensitive=False,
            expires_at=timezone.now() + timedelta(days=7),
            requested_by=request.user,
        )
        if role != 'reception':
            try:
                notify_roles(
                    ['reception'],
                    category='system',
                    title='Mail merge letters queued',
                    message=f'{doc.title} ({len(documents)} recipient(s))',
                    link_page='printqueue',
                    link_object_id=item.id,
                    school_class=school_class,
                )
            except Exception:
                pass
        return Response({'detail': 'Letters queued for printing.', 'print_queue_id': item.id, 'count': len(documents)})

    @action(detail=True, methods=['post'], url_path='send-merge')
    def send_merge(self, request, pk=None):
        doc = self.get_object()
        role = get_role(request.user)
        if role not in ['teacher', 'reception'] and not (IsSuperUser().has_permission(request, self) or is_admin_role(role)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        channel = str((request.data or {}).get('channel') or 'email').strip().lower()
        if channel not in {'email', 'sms'}:
            return Response({'detail': 'channel must be email or sms.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            targets, audience = _resolve_document_merge_targets(doc, request)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if not targets:
            return Response({'detail': 'Choose a student or class before sending.'}, status=status.HTTP_400_BAD_REQUEST)

        sent = 0
        skipped = 0
        failures = []
        for student in targets:
            rendered = _render_document_merge(doc, student, request, audience=audience)
            recipient = rendered['recipient_email'] if channel == 'email' else rendered['recipient_phone']
            if not recipient:
                skipped += 1
                continue
            try:
                if channel == 'email':
                    ok = send_email(
                        subject=rendered['title'],
                        recipient_list=[recipient],
                        template_name='school/emails/communication_email.html',
                        context={
                            'title': rendered['title'],
                            'recipient_name': rendered['recipient_name'],
                            'student_name': rendered['student_name'],
                            'student_id': rendered['student_id'],
                            'class_label': rendered['class_label'],
                            'body': rendered['body_text'],
                            'body_html': rendered['body_html'],
                        },
                    )
                else:
                    ok = bool(send_sms(recipient, f"{rendered['title']} | {rendered['body_text']}"))
                if ok:
                    sent += 1
                else:
                    failures.append(student.student_id)
            except Exception:
                failures.append(student.student_id)

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='MAIL_MERGE_SENT',
            ip_address=get_client_ip(request),
            details=f'DocumentDraft {doc.id} sent via {channel}: sent={sent}, skipped={skipped}, failed={len(failures)}.',
        )
        return Response({
            'detail': f'{channel.upper()} delivery completed.',
            'sent': sent,
            'skipped': skipped,
            'failed': failures,
            'audience': audience,
        })

    @action(detail=True, methods=['post'], url_path='schedule-campaign')
    def schedule_campaign(self, request, pk=None):
        doc = self.get_object()
        role = get_role(request.user)
        if role not in ['teacher', 'reception', 'bursar'] and not (role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(request, self)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        channel = str((request.data or {}).get('channel') or 'email').strip().lower()
        if channel not in {'email', 'sms'}:
            return Response({'detail': 'channel must be email or sms.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            scheduled_for = _parse_schedule_datetime((request.data or {}).get('scheduled_for'))
            targets, audience = _resolve_document_merge_targets(doc, request)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if not targets:
            return Response({'detail': 'Choose a student or class before scheduling.'}, status=status.HTTP_400_BAD_REQUEST)

        retry_limit = int((request.data or {}).get('retry_limit') or 2)
        retry_delay_minutes = int((request.data or {}).get('retry_delay_minutes') or 30)
        class_id = (request.data or {}).get('school_class') or doc.school_class_id
        student_id = (request.data or {}).get('student')

        campaign = CommunicationCampaign.objects.create(
            document=doc,
            channel=channel,
            audience=audience,
            school_class_id=int(class_id) if str(class_id or '').isdigit() else None,
            student_id=int(student_id) if str(student_id or '').isdigit() else None,
            scheduled_for=scheduled_for,
            retry_limit=max(0, min(retry_limit, 10)),
            retry_delay_minutes=max(1, min(retry_delay_minutes, 1440)),
            notes=(request.data or {}).get('notes') or '',
            created_by=request.user,
            status='scheduled',
        )
        seeded = _seed_campaign_deliveries(campaign, doc, targets, request, audience=audience)
        _refresh_campaign_summary(campaign)
        if campaign.scheduled_for <= timezone.now():
            _run_campaign(campaign, request, actor=request.user)
        return Response({
            'detail': 'Campaign scheduled.',
            'campaign': CommunicationCampaignSerializer(campaign).data,
            'seeded': seeded,
        }, status=status.HTTP_201_CREATED)


class CommunicationCampaignViewSet(viewsets.ModelViewSet):
    queryset = CommunicationCampaign.objects.select_related(
        'document', 'school_class', 'student', 'created_by'
    ).prefetch_related('deliveries').all().order_by('-scheduled_for', '-id')
    serializer_class = CommunicationCampaignSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)
        if role == 'teacher':
            return qs.filter(created_by=self.request.user)
        if role == 'bursar':
            return qs.filter(
                Q(created_by=self.request.user) |
                Q(document__library_scope__in=['all', 'bursar'])
            )
        if role == 'reception':
            return qs.filter(
                Q(created_by=self.request.user) |
                Q(document__library_scope__in=['all', 'reception', 'admin'])
            )
        if role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(self.request, self):
            return qs
        return qs.none()

    def perform_create(self, serializer):
        role = get_role(self.request.user)
        if role not in ['teacher', 'reception', 'bursar'] and not (role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(self.request, self)):
            raise PermissionDenied('Permission denied.')
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], url_path='run-now')
    def run_now(self, request, pk=None):
        campaign = self.get_object()
        role = get_role(request.user)
        if role not in ['teacher', 'reception', 'bursar'] and not (role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(request, self)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        _run_campaign(campaign, request, actor=request.user)
        return Response(CommunicationCampaignSerializer(campaign).data)

    @action(detail=False, methods=['post'], url_path='run-due')
    def run_due(self, request):
        role = get_role(request.user)
        if role not in ['reception', 'bursar'] and not (role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(request, self)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        now = timezone.now()
        due = self.get_queryset().filter(status='scheduled', scheduled_for__lte=now).order_by('scheduled_for')[:40]
        ran = 0
        for campaign in due:
            _run_campaign(campaign, request, actor=request.user)
            ran += 1
        return Response({'detail': f'Executed {ran} campaign(s).', 'ran': ran})

    @action(detail=True, methods=['get'], url_path='delivery-report')
    def delivery_report(self, request, pk=None):
        campaign = self.get_object()
        deliveries = campaign.deliveries.all().order_by('-updated_at')
        totals = {
            'total': deliveries.count(),
            'sent': deliveries.filter(status__in=['sent', 'opened', 'confirmed', 'replied']).count(),
            'failed': deliveries.filter(status='failed').count(),
            'retry_pending': deliveries.filter(status='retry_pending').count(),
            'skipped': deliveries.filter(status='skipped').count(),
            'opened': deliveries.filter(opened_at__isnull=False).count(),
            'confirmed': deliveries.filter(confirmed_at__isnull=False).count(),
            'replied': deliveries.filter(replied_at__isnull=False).count(),
        }
        return Response({
            'campaign': CommunicationCampaignSerializer(campaign).data,
            'totals': totals,
            'deliveries': CommunicationDeliverySerializer(deliveries[:300], many=True).data,
        })

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status in ['completed', 'partially_failed', 'cancelled']:
            return Response({'detail': f'Campaign already {campaign.status}.'}, status=status.HTTP_400_BAD_REQUEST)
        campaign.status = 'cancelled'
        campaign.finished_at = timezone.now()
        campaign.save(update_fields=['status', 'finished_at', 'updated_at'])
        pending = campaign.deliveries.filter(status__in=['pending', 'retry_pending'])
        pending.update(status='skipped', last_error='Campaign cancelled.')
        _refresh_campaign_summary(campaign)
        return Response(CommunicationCampaignSerializer(campaign).data)


class CommunicationDeliveryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CommunicationDelivery.objects.select_related('campaign', 'campaign__document', 'student', 'student__current_class').all().order_by('-id')
    serializer_class = CommunicationDeliverySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)
        if role == 'teacher':
            qs = qs.filter(campaign__created_by=self.request.user)
        elif role == 'bursar':
            qs = qs.filter(Q(campaign__created_by=self.request.user) | Q(campaign__document__library_scope__in=['all', 'bursar']))
        elif role == 'reception':
            qs = qs.filter(Q(campaign__created_by=self.request.user) | Q(campaign__document__library_scope__in=['all', 'reception', 'admin']))
        elif role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(self.request, self):
            pass
        else:
            return qs.none()

        channel = (self.request.query_params.get('channel') or '').strip().lower()
        status_v = (self.request.query_params.get('status') or '').strip().lower()
        campaign_id = (self.request.query_params.get('campaign') or '').strip()
        student_id = (self.request.query_params.get('student') or '').strip()
        class_id = (self.request.query_params.get('class_id') or '').strip()
        class_level = (self.request.query_params.get('class_level') or '').strip()
        q = (self.request.query_params.get('q') or '').strip()

        if channel:
            qs = qs.filter(channel__iexact=channel)
        if status_v:
            qs = qs.filter(status__iexact=status_v)
        if campaign_id.isdigit():
            qs = qs.filter(campaign_id=int(campaign_id))
        if student_id.isdigit():
            qs = qs.filter(student_id=int(student_id))
        if class_id.isdigit():
            qs = qs.filter(student__current_class_id=int(class_id))
        if class_level:
            qs = qs.filter(student__current_class__level__iexact=class_level)
        if q:
            qs = qs.filter(
                Q(recipient_name__icontains=q)
                | Q(recipient_email__icontains=q)
                | Q(recipient_phone__icontains=q)
                | Q(message_subject__icontains=q)
                | Q(student__student_id__icontains=q)
                | Q(student__first_name__icontains=q)
                | Q(student__last_name__icontains=q)
                | Q(campaign__document__title__icontains=q)
            )
        return qs

    def _can_manage_delivery(self, delivery):
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role) or IsSuperUser().has_permission(self.request, self):
            return True
        if role in ['bursar', 'reception']:
            return True
        if role == 'teacher':
            return getattr(delivery.campaign, 'created_by_id', None) == getattr(self.request.user, 'id', None)
        return False

    @action(detail=True, methods=['post'], url_path='retry')
    def retry(self, request, pk=None):
        delivery = self.get_object()
        if not self._can_manage_delivery(delivery):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        delivery.status = 'retry_pending'
        delivery.next_attempt_at = timezone.now()
        delivery.last_error = 'Retry requested manually.'
        delivery.save(update_fields=['status', 'next_attempt_at', 'last_error', 'updated_at'])
        _attempt_delivery(delivery, request, force=True)
        _refresh_campaign_summary(delivery.campaign)
        try:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='DELIVERY_RETRY',
                ip_address=get_client_ip(request),
                details=f'Communication delivery {delivery.id} retried manually.',
            )
        except Exception:
            pass
        return Response(CommunicationDeliverySerializer(delivery).data)

    @action(detail=True, methods=['post'], url_path='resend')
    def resend(self, request, pk=None):
        delivery = self.get_object()
        if not self._can_manage_delivery(delivery):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        duplicate = CommunicationDelivery.objects.create(
            campaign=delivery.campaign,
            student=delivery.student,
            recipient_name=delivery.recipient_name,
            recipient_email=delivery.recipient_email,
            recipient_phone=delivery.recipient_phone,
            channel=delivery.channel,
            message_subject=delivery.message_subject,
            message_body=delivery.message_body,
            status='pending',
        )
        _attempt_delivery(duplicate, request, force=True)
        _refresh_campaign_summary(delivery.campaign)
        try:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='DELIVERY_RESEND',
                ip_address=get_client_ip(request),
                details=f'Communication delivery {delivery.id} resent as {duplicate.id}.',
            )
        except Exception:
            pass
        return Response(CommunicationDeliverySerializer(duplicate).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get', 'post'], url_path='acknowledge', authentication_classes=[], permission_classes=[permissions.AllowAny])
    def acknowledge(self, request):
        token = (request.query_params.get('token') or request.data.get('token') or '').strip()
        event = (request.query_params.get('event') or request.data.get('event') or 'opened').strip().lower()
        if not token:
            return Response({'detail': 'token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        delivery = CommunicationDelivery.objects.filter(ack_token=token).first()
        if not delivery:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_404_NOT_FOUND)
        now = timezone.now()
        if event == 'opened':
            if not delivery.opened_at:
                delivery.opened_at = now
            if delivery.status == 'sent':
                delivery.status = 'opened'
        elif event == 'confirmed':
            if not delivery.confirmed_at:
                delivery.confirmed_at = now
            delivery.status = 'confirmed'
        elif event == 'replied':
            if not delivery.replied_at:
                delivery.replied_at = now
            delivery.status = 'replied'
        else:
            return Response({'detail': 'event must be opened, confirmed, or replied.'}, status=status.HTTP_400_BAD_REQUEST)
        delivery.save(update_fields=['opened_at', 'confirmed_at', 'replied_at', 'status', 'updated_at'])
        _refresh_campaign_summary(delivery.campaign)
        return Response({'detail': f'Acknowledgment recorded ({event}).'})


class ExamPaperViewSet(viewsets.ModelViewSet):
    queryset = ExamPaper.objects.select_related('school_class', 'subject', 'teacher', 'printed_by').all().order_by('-created_at')
    serializer_class = ExamPaperSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)
        if role == 'teacher':
            try:
                t = self.request.user.teacher_profile
                return qs.filter(teacher=t)
            except Exception:
                return qs.none()
        if role == 'reception' or IsSuperUser().has_permission(self.request, self) or is_admin_role(role):
            return qs
        return qs.none()

    def create(self, request, *args, **kwargs):
        role = get_role(request.user)
        if role != 'teacher' and not (IsSuperUser().has_permission(request, self) or is_admin_role(role)):
            return Response({'detail': 'Only teachers/admin can upload exams.'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data or {}
        title = (data.get('title') or '').strip()
        file_url = (data.get('file_url') or '').strip()
        description = (data.get('description') or '').strip() or None
        school_class = data.get('school_class') if str(data.get('school_class') or '').isdigit() else None
        section = (data.get('section') or '').strip().upper()
        subject = data.get('subject') if str(data.get('subject') or '').isdigit() else None

        if not title or not file_url:
            return Response({'detail': 'title and file_url are required.'}, status=status.HTTP_400_BAD_REQUEST)
        if section and len(section) != 1:
            return Response({'detail': 'section must be a single letter (or blank).'}, status=status.HTTP_400_BAD_REQUEST)

        teacher = None
        if role == 'teacher':
            try:
                teacher = request.user.teacher_profile
            except Exception:
                return Response({'detail': 'Teacher profile not linked.'}, status=status.HTTP_400_BAD_REQUEST)

        obj = ExamPaper.objects.create(
            title=title,
            description=description,
            school_class_id=int(school_class) if school_class else None,
            section=section or '',
            subject_id=int(subject) if subject else None,
            teacher=teacher,
            file_url=file_url,
            status='draft',
        )
        try:
            SecurityAuditLog.objects.create(user=request.user, event_type='EXAM_UPLOADED', ip_address=get_client_ip(request), details=f'ExamPaper {obj.id} uploaded.')
        except Exception:
            pass
        return Response(ExamPaperSerializer(obj).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='submit')
    def submit(self, request, pk=None):
        obj = self.get_object()
        role = get_role(request.user)
        if role != 'teacher' and not (IsSuperUser().has_permission(request, self) or is_admin_role(role)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if obj.status != 'draft':
            return Response({'detail': 'Only draft exams can be submitted.'}, status=status.HTTP_400_BAD_REQUEST)
        obj.status = 'submitted'
        obj.submitted_at = timezone.now()
        obj.save(update_fields=['status', 'submitted_at', 'updated_at'])
        try:
            notify_roles(['reception'], category='academic', title='New exam uploaded for printing', message=obj.title, link_page='printdesk', link_object_id=obj.id)
        except Exception:
            pass
        return Response(ExamPaperSerializer(obj).data)

    @action(detail=True, methods=['post'], url_path='mark-printed')
    def mark_printed(self, request, pk=None):
        obj = self.get_object()
        role = get_role(request.user)
        if role != 'reception' and not IsSuperUser().has_permission(request, self):
            return Response({'detail': 'Only reception/superadmin can mark printed.'}, status=status.HTTP_403_FORBIDDEN)
        obj.status = 'printed'
        obj.printed_at = timezone.now()
        obj.printed_by = request.user
        obj.save(update_fields=['status', 'printed_at', 'printed_by', 'updated_at'])
        try:
            SecurityAuditLog.objects.create(
                user=request.user,
                event_type='PRINT_EXAM_MARKED',
                ip_address=get_client_ip(request),
                details=f'ExamPaper {obj.id} marked printed.',
            )
        except Exception:
            pass
        return Response(ExamPaperSerializer(obj).data)


class UploadViewSet(viewsets.ViewSet): 
    permission_classes = [permissions.IsAuthenticated] 

    @action(detail=False, methods=['post'], url_path='image')
    def image(self, request):
        f = request.FILES.get('file')
        if not f:
            return Response({'detail': 'file is required.'}, status=status.HTTP_400_BAD_REQUEST)
        content_type = (getattr(f, 'content_type', '') or '').lower()
        if not content_type.startswith('image/'):
            return Response({'detail': 'Only image uploads are allowed.'}, status=status.HTTP_400_BAD_REQUEST)
        if f.size and f.size > 2 * 1024 * 1024:
            return Response({'detail': 'Max file size is 2MB.'}, status=status.HTTP_400_BAD_REQUEST)

        role = get_role(request.user)
        if not (IsSuperUser().has_permission(request, self) or is_admin_role(role) or role in ['reception', 'teacher']):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            raw_name = _validate_upload_filename(f.name)
            payload = f.read()
            detected_ext = _validate_image_upload_bytes(raw_name, payload)
            safe_ext = 'jpg' if detected_ext == 'jpeg' else detected_ext
            name = _storage_name_for_upload('uploads', raw_name, safe_ext)
            saved = default_storage.save(name, ContentFile(payload))
        except ValidationError as e:
            try:
                SecurityAuditLog.objects.create(
                    user=request.user,
                    event_type='UPLOAD_REJECTED',
                    ip_address=get_client_ip(request),
                    details=f'Image upload rejected for {getattr(f, "name", "unknown")}: {e}',
                )
            except Exception:
                pass
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'url': default_storage.url(saved)}) 

    @action(detail=False, methods=['post'], url_path='file')
    def file(self, request):
        """
        Upload a document (PDF/DOC/DOCX) for teacher exams and admin documents.
        """
        f = request.FILES.get('file')
        if not f:
            return Response({'detail': 'file is required.'}, status=status.HTTP_400_BAD_REQUEST)

        ct = (getattr(f, 'content_type', '') or '').lower()
        allowed = {
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }
        if ct not in allowed:
            return Response({'detail': 'Only PDF/DOC/DOCX uploads are allowed.'}, status=status.HTTP_400_BAD_REQUEST)
        if f.size and f.size > 10 * 1024 * 1024:
            return Response({'detail': 'Max file size is 10MB.'}, status=status.HTTP_400_BAD_REQUEST)

        role = get_role(request.user)
        if not (IsSuperUser().has_permission(request, self) or is_admin_role(role) or role in ['reception', 'teacher']):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            raw_name = _validate_upload_filename(f.name)
            ext = (raw_name.rsplit('.', 1)[-1] if '.' in raw_name else 'pdf').lower()
            safe_ext = ext if re.match(r'^[a-z0-9]{1,6}$', ext) else 'pdf'
            payload = f.read()
            _validate_document_upload_bytes(raw_name, payload, safe_ext)
            name = _storage_name_for_upload('uploads/docs', raw_name, safe_ext)
            saved = default_storage.save(name, ContentFile(payload))
        except ValidationError as e:
            try:
                SecurityAuditLog.objects.create(
                    user=request.user,
                    event_type='UPLOAD_REJECTED',
                    ip_address=get_client_ip(request),
                    details=f'Document upload rejected for {getattr(f, "name", "unknown")}: {e}',
                )
            except Exception:
                pass
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'url': default_storage.url(saved)}) 


class PrintQueueViewSet(viewsets.ModelViewSet):
    """
    Unified print queue for Reception: admission letters, credentials, report cards.
    """

    queryset = PrintQueueItem.objects.all().order_by('-created_at')
    serializer_class = PrintQueueItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _can_view(self, role: str) -> bool:
        return role in ['superadmin', 'reception'] or is_admin_role(role)

    def get_queryset(self):
        role = get_role(self.request.user)
        if not self._can_view(role):
            return PrintQueueItem.objects.none()
        qs = super().get_queryset()

        status_v = (self.request.query_params.get('status') or '').strip().lower()
        kind = (self.request.query_params.get('kind') or '').strip().lower()
        if status_v:
            qs = qs.filter(status=status_v)
        if kind:
            qs = qs.filter(kind=kind)
        return qs

    def create(self, request, *args, **kwargs):
        role = get_role(request.user)
        if not self._can_view(role):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        kind = (request.data or {}).get('kind')
        title = (request.data or {}).get('title') or ''
        note = (request.data or {}).get('note') or None
        student_id = (request.data or {}).get('student_id')
        teacher_id = (request.data or {}).get('teacher_id')
        payload = (request.data or {}).get('payload') or {}

        if kind not in dict(getattr(PrintQueueItem, '_meta').get_field('kind').choices):
            return Response({'detail': 'Invalid kind.'}, status=status.HTTP_400_BAD_REQUEST)

        student = Student.objects.filter(id=student_id).first() if str(student_id).isdigit() else None
        teacher = Teacher.objects.filter(id=teacher_id).first() if str(teacher_id).isdigit() else None

        safe_title = (title or '').strip()
        if not safe_title:
            if kind == 'report_card' and student:
                safe_title = f"Report card: {student.first_name} {student.last_name}".strip()
            elif student:
                safe_title = f"{kind.replace('_',' ').title()}: {student.first_name} {student.last_name}".strip()
            elif teacher:
                safe_title = f"{kind.replace('_',' ').title()}: {teacher.first_name} {teacher.last_name}".strip()
            else:
                safe_title = kind.replace('_', ' ').title()

        is_sensitive = bool((request.data or {}).get('is_sensitive', False))
        expires_hours = int((request.data or {}).get('expires_hours') or (24 if is_sensitive else 168))
        expires_at = timezone.now() + timedelta(hours=max(1, min(expires_hours, 24 * 14)))

        obj = PrintQueueItem.objects.create(
            kind=kind,
            status='queued',
            title=safe_title,
            note=(str(note).strip() if note else None),
            student=student,
            teacher=teacher,
            payload=payload if isinstance(payload, dict) else {},
            is_sensitive=is_sensitive,
            expires_at=expires_at,
            requested_by=request.user,
        )
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PRINTQ_ENQUEUED',
            ip_address=get_client_ip(request),
            details=f'Enqueued print item id={obj.id} kind={kind} sensitive={is_sensitive}.',
        )
        return Response(self.get_serializer(obj).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        role = get_role(request.user)
        if not self._can_view(role):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        obj = self.get_object()
        if obj.status in ['printed', 'cancelled', 'expired']:
            return Response({'detail': f'Already {obj.status}.'}, status=status.HTTP_400_BAD_REQUEST)
        obj.status = 'cancelled'
        obj.save(update_fields=['status', 'updated_at'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PRINTQ_CANCELLED',
            ip_address=get_client_ip(request),
            details=f'Cancelled print item id={obj.id}.',
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        role = get_role(request.user)
        if not self._can_view(role):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        obj = self.get_object()

        if obj.status == 'expired' or obj.is_expired():
            obj.status = 'expired'
            if obj.is_sensitive and not obj.wiped_at:
                obj.payload = {}
                obj.wiped_at = timezone.now()
            obj.save(update_fields=['status', 'payload', 'wiped_at', 'updated_at'])
            return Response({'detail': 'This print item has expired.'}, status=status.HTTP_410_GONE)

        payload = obj.payload or {}
        login_url = payload.get('login_url') or request.build_absolute_uri('/')

        if obj.kind == 'mail_merge_letter':
            documents = payload.get('documents') or []
            pdf_buffer = generate_mail_merge_letter_pdf(documents, bundle_title=obj.title or 'Letters')
            fn = f"mail_merge_{obj.id}.pdf"
            return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

        if obj.kind == 'staff_credentials':
            pdf_buffer = generate_staff_credential_pdf(
                payload.get('staff_name') or obj.title,
                payload.get('role') or 'staff',
                payload.get('username') or '',
                payload.get('password') or '',
                login_url,
            )
            fn = f"staff_credentials_{(payload.get('username') or 'staff')}.pdf"
            return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

        if obj.kind == 'teacher_credentials':
            if not obj.teacher:
                return Response({'detail': 'Teacher missing for this item.'}, status=status.HTTP_400_BAD_REQUEST)
            pdf_buffer = generate_teacher_credential_pdf(
                obj.teacher,
                payload.get('username'),
                payload.get('password'),
                login_url,
            )
            fn = f"teacher_credentials_{obj.teacher.employee_id or obj.teacher.id}.pdf"
            return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

        if obj.kind in ['admission_letter', 'student_credentials', 'parent_credentials', 'report_card']:
            if not obj.student:
                return Response({'detail': 'Student missing for this item.'}, status=status.HTTP_400_BAD_REQUEST)

            if obj.kind == 'report_card':
                term_number = payload.get('term_number')
                academic_year = payload.get('academic_year')
                if not (str(term_number).isdigit() and str(academic_year).isdigit()):
                    return Response({'detail': 'term_number and academic_year are required for report cards.'}, status=status.HTTP_400_BAD_REQUEST)
                term_number = int(term_number)
                academic_year = int(academic_year)
                academic_term = AcademicTerm.objects.filter(term_number=term_number, academic_year=academic_year).first()
                if not academic_term:
                    return Response({'detail': 'Academic term not found.'}, status=status.HTTP_404_NOT_FOUND)

                marks = Mark.objects.filter(student=obj.student, term=term_number, year=academic_year)
                if not marks.exists():
                    return Response({'detail': 'No marks found for this student in the specified term.'}, status=status.HTTP_404_NOT_FOUND)

                overall_average = marks.aggregate(Avg('score'))['score__avg'] or 0
                all_class_marks = Mark.objects.filter(
                    student__current_class=obj.student.current_class,
                    student__section=obj.student.section,
                    term=term_number,
                    year=academic_year,
                )
                students_with_averages = all_class_marks.values('student').annotate(avg_score=Avg('score'))
                sorted_students = sorted(list(students_with_averages), key=lambda x: x['avg_score'], reverse=True)
                class_position = 0
                for i, s in enumerate(sorted_students):
                    if s['student'] == obj.student.id:
                        class_position = i + 1
                        break

                total_school_days = 100
                days_present = Attendance.objects.filter(
                    student=obj.student,
                    date__range=(academic_term.start_date, academic_term.end_date),
                    status='Present',
                ).count()
                attendance_percentage = (days_present / total_school_days) * 100 if total_school_days > 0 else 0

                grading_scale = GradingScale.objects.filter(school_class=obj.student.current_class, is_default=False).first()
                if not grading_scale:
                    grading_scale = GradingScale.objects.filter(is_default=True).first()
                grading_scale_data = grading_scale.scale_data if grading_scale else []

                # Compute marks_rows for points/aggregates.
                marks_rows = []
                total_points = 0
                points_known = False
                for m in marks:
                    score = float(getattr(m, 'score', 0) or 0)
                    grade = "N/A"
                    pts = None
                    for gs in (grading_scale_data or []):
                        try:
                            mn = float(gs.get('min_score'))
                            mx = float(gs.get('max_score'))
                        except Exception:
                            continue
                        if mn <= score <= mx:
                            grade = str(gs.get('grade') or 'N/A')
                            v = gs.get('points', None)
                            try:
                                pts = int(v) if v is not None and str(v).strip() != '' else None
                            except Exception:
                                pts = None
                            break
                    if pts is not None:
                        points_known = True
                        total_points += int(pts)
                    marks_rows.append({
                        'subject': getattr(m, 'subject', '') or '',
                        'score': score,
                        'max_score': 100,
                        'percentage': score,
                        'grade': grade,
                        'points': pts,
                        'remarks': getattr(m, 'remarks', None) or '',
                    })

                overall_grade = "N/A"
                for gs in (grading_scale_data or []):
                    try:
                        mn = float(gs.get('min_score'))
                        mx = float(gs.get('max_score'))
                    except Exception:
                        continue
                    if mn <= float(overall_average or 0) <= mx:
                        overall_grade = str(gs.get('grade') or 'N/A')
                        break

                aggregate_points = int(total_points) if points_known else None

                pdf_buffer = generate_report_card_pdf(
                    student=obj.student,
                    academic_term=academic_term,
                    marks_rows=marks_rows,
                    overall_average=float(overall_average or 0),
                    overall_grade=overall_grade,
                    aggregate_points=aggregate_points,
                    class_position=class_position,
                    attendance_percentage=float(attendance_percentage or 0),
                    grading_scale_data=grading_scale_data,
                )
                fn = f"report_card_{obj.student.student_id}_Term{term_number}_{academic_year}.pdf"
                return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

            if obj.kind == 'admission_letter':
                tmpl = None
                try:
                    v = SystemSetting.objects.filter(key='admission_letter_template').values_list('value', flat=True).first()
                    if isinstance(v, dict):
                        tmpl = v.get('text') or None
                    elif isinstance(v, str):
                        tmpl = v or None
                except Exception:
                    tmpl = None
                pdf_buffer = generate_admission_letter_pdf(
                    obj.student,
                    login_url,
                    parent_username=payload.get('parent_username'),
                    parent_password=payload.get('parent_password'),
                    student_username=payload.get('student_username'),
                    student_password=payload.get('student_password'),
                    template_text=tmpl,
                )
                fn = f"admission_letter_{obj.student.student_id}.pdf"
                return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

            # Credentials
            if obj.kind == 'parent_credentials':
                pdf_buffer = generate_parent_credential_pdf(
                    parent_name=obj.student.parent_name or 'Parent/Guardian',
                    student_name=f"{obj.student.first_name} {obj.student.last_name}",
                    student_id=obj.student.student_id,
                    login_url=login_url,
                    phone_number=payload.get('parent_username') or obj.student.parent_phone,
                    password=payload.get('parent_password'),
                )
                fn = f"parent_credentials_{obj.student.student_id}.pdf"
                return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

            # default to student credentials
            pdf_buffer = generate_student_credential_pdf(
                student_name=f"{obj.student.first_name} {obj.student.last_name}",
                student_username=payload.get('student_username') or obj.student.student_id,
                student_password=payload.get('student_password'),
                login_url=login_url,
            )
            fn = f"student_credentials_{obj.student.student_id}.pdf"
            return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

        return Response({'detail': 'Unsupported print kind.'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='mark-printed')
    def mark_printed(self, request, pk=None):
        role = get_role(request.user)
        if role not in ['superadmin', 'reception'] and not is_admin_role(role):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        obj = self.get_object()
        if obj.status == 'printed':
            return Response({'detail': 'Already printed.'}, status=status.HTTP_400_BAD_REQUEST)
        obj.status = 'printed'
        obj.printed_by = request.user
        obj.printed_at = timezone.now()
        if obj.is_sensitive:
            obj.payload = {}
            obj.wiped_at = timezone.now()
        obj.save(update_fields=['status', 'printed_by', 'printed_at', 'payload', 'wiped_at', 'updated_at'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PRINTQ_PRINTED',
            ip_address=get_client_ip(request),
            details=f'Marked print item id={obj.id} printed (sensitive={obj.is_sensitive}).',
        )
        return Response(self.get_serializer(obj).data)


class AIToolsViewSet(viewsets.ViewSet):
    """
    Teacher-only AI helper endpoints.
    Strictly limited to generating draft text for tests/exams/notes.
    """

    permission_classes = [permissions.IsAuthenticated]

    def _enabled(self) -> bool:
        v = get_system_setting('ai_tools_enabled', {'enabled': True})
        if isinstance(v, dict):
            return bool(v.get('enabled', True))
        return bool(v) if v is not None else True

    def _choose_cred(self):
        # Prefer OpenAI when available; fallback to Gemini.
        for svc in ['openai', 'gemini']:
            c = APICredential.objects.filter(service_name=svc, is_active=True, last_verify_ok=True).order_by('-updated_at').first()
            if c:
                return c
        return None

    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        if get_role(request.user) != 'teacher':
            return Response({'detail': 'Only teachers can use AI Tools.'}, status=status.HTTP_403_FORBIDDEN)
        if not self._enabled():
            return Response({'detail': 'AI Tools are disabled by Super Admin.'}, status=status.HTTP_403_FORBIDDEN)

        cred = self._choose_cred()
        if not cred:
            return Response({'detail': 'No verified AI credentials configured.'}, status=status.HTTP_400_BAD_REQUEST)

        kind = (request.data or {}).get('kind') or 'test'
        title = (request.data or {}).get('title') or ''
        instructions = (request.data or {}).get('instructions') or ''
        class_id = (request.data or {}).get('school_class')
        subject_id = (request.data or {}).get('subject')

        if not instructions.strip():
            return Response({'detail': 'instructions is required.'}, status=status.HTTP_400_BAD_REQUEST)

        school_class = SchoolClass.objects.filter(id=class_id).first() if str(class_id).isdigit() else None
        subject = Subject.objects.filter(id=subject_id).first() if str(subject_id).isdigit() else None

        safe_kind = kind if kind in ['test', 'exam', 'notes'] else 'test'
        safe_title = (title or '').strip() or f"{safe_kind.title()} Draft"

        # Guardrails: generate drafts only. No system actions, no student data processing.
        sys_prompt = (
            "You are a teacher assistant for a primary school in Uganda. "
            "Generate classroom materials only (tests, exams, notes). "
            "Do not include private data. Do not provide hacking/security advice. "
            "Output plain text only (no markdown)."
        )
        user_prompt = f"Kind: {safe_kind}\n"
        if school_class:
            user_prompt += f"Class: {school_class.level}\n"
        if subject:
            user_prompt += f"Subject: {subject.name}\n"
        user_prompt += f"Instructions: {instructions.strip()}\n"

        content = None
        extra = cred.extra_data if isinstance(cred.extra_data, dict) else {}

        try:
            if cred.service_name == 'openai':
                base_url = (extra.get('base_url') or 'https://api.openai.com').rstrip('/')
                model = extra.get('model') or 'gpt-4.1-mini'
                r = requests.post(
                    base_url + '/v1/chat/completions',
                    headers={'Authorization': f'Bearer {cred.api_key}', 'Content-Type': 'application/json'},
                    json={
                        'model': model,
                        'messages': [
                            {'role': 'system', 'content': sys_prompt},
                            {'role': 'user', 'content': user_prompt},
                        ],
                        'temperature': 0.4,
                    },
                    timeout=18,
                )
                if r.status_code != 200:
                    return Response({'detail': 'AI request failed.', 'status_code': r.status_code, 'body': r.text[:300]}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
                data = r.json()
                content = (((data.get('choices') or [{}])[0].get('message') or {}).get('content') or '').strip()
            elif cred.service_name == 'gemini':
                model = extra.get('model') or 'gemini-1.5-flash'
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                r = requests.post(
                    url,
                    params={'key': cred.api_key},
                    headers={'Content-Type': 'application/json'},
                    json={
                        'contents': [{'parts': [{'text': sys_prompt + "\n\n" + user_prompt}]}],
                        'generationConfig': {'temperature': 0.4},
                    },
                    timeout=18,
                )
                if r.status_code != 200:
                    return Response({'detail': 'AI request failed.', 'status_code': r.status_code, 'body': r.text[:300]}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
                data = r.json()
                content = ((((data.get('candidates') or [{}])[0].get('content') or {}).get('parts') or [{}])[0].get('text') or '').strip()
            else:
                return Response({'detail': 'Unsupported AI service.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': 'AI request error.', 'error': str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if not content:
            return Response({'detail': 'AI returned empty content.'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        doc = DocumentDraft.objects.create(
            created_by=request.user,
            kind=safe_kind,
            title=safe_title[:160],
            body=content,
            school_class=school_class,
            subject=subject,
            status='draft',
        )

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='AI_DRAFT_GENERATED',
            ip_address=get_client_ip(request),
            details=f'AI draft generated id={doc.id} svc={cred.service_name} kind={safe_kind}.',
        )

        return Response(DocumentDraftSerializer(doc).data, status=status.HTTP_201_CREATED)


class SecurityAdminViewSet(viewsets.ViewSet):
    """
    Super Admin security dashboard endpoints.
    """
    permission_classes = [IsSuperUser]

    @action(detail=False, methods=['get'], url_path='overview')
    def overview(self, request):
        since = timezone.now() - timedelta(days=1)
        logs = SecurityAuditLog.objects.filter(timestamp__gte=since)
        by_type = {}
        for row in logs.values('event_type').annotate(c=Count('id')).order_by('-c')[:30]:
            by_type[row['event_type']] = row['c']

        active_sessions = UserSession.objects.filter(is_active=True).count()
        failed = SecurityAuditLog.objects.filter(timestamp__gte=since, event_type__in=['LOGIN_FAILURE', 'LOGIN_RATE_LIMITED']).count()

        return Response({
            'since': since.isoformat(),
            'active_sessions': active_sessions,
            'failed_logins_24h': failed,
            'events_24h': by_type,
        })

    @action(detail=False, methods=['get'], url_path='active-sessions')
    def active_sessions(self, request):
        qs = UserSession.objects.select_related('user').filter(is_active=True).order_by('-login_time')[:200]
        rows = []
        for s in qs:
            rows.append({
                'id': s.id,
                'session_key': s.session_key,
                'user_id': s.user_id,
                'username': getattr(s.user, 'username', None),
                'login_time': s.login_time,
                'ip_address': s.ip_address,
                'user_agent': s.user_agent,
            })
        return Response(rows)

    @action(detail=False, methods=['post'], url_path='terminate-session')
    def terminate_session(self, request):
        session_key = (request.data.get('session_key') or '').strip()
        if not session_key:
            return Response({'detail': 'session_key is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Mark our tracking row inactive.
        UserSession.objects.filter(session_key=session_key, is_active=True).update(is_active=False, logout_time=timezone.now())
        # Remove Django session so it becomes invalid immediately.
        Session.objects.filter(session_key=session_key).delete()

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='SESSION_TERMINATED',
            ip_address=get_client_ip(request),
            details=f'Terminated session_key={session_key}.',
        )
        return Response({'detail': 'Session terminated.'})

    @action(detail=False, methods=['post'], url_path='terminate-user-sessions')
    def terminate_user_sessions(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'detail': 'user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        keys = list(UserSession.objects.filter(user_id=user_id, is_active=True).values_list('session_key', flat=True))
        UserSession.objects.filter(user_id=user_id, is_active=True).update(is_active=False, logout_time=timezone.now())
        Session.objects.filter(session_key__in=keys).delete()
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='USER_SESSIONS_TERMINATED',
            ip_address=get_client_ip(request),
            details=f'Terminated {len(keys)} sessions for user_id={user_id}.',
        )
        return Response({'detail': f'Terminated {len(keys)} sessions.'})

    @action(detail=False, methods=['post'], url_path='disable-user')
    def disable_user(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'detail': 'user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        u = User.objects.filter(id=user_id).first()
        if not u:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        if u == request.user:
            return Response({'detail': 'You cannot disable your own account.'}, status=status.HTTP_400_BAD_REQUEST)
        u.is_active = False
        u.save(update_fields=['is_active'])
        # Also kill sessions.
        keys = list(UserSession.objects.filter(user=u, is_active=True).values_list('session_key', flat=True))
        UserSession.objects.filter(user=u, is_active=True).update(is_active=False, logout_time=timezone.now())
        Session.objects.filter(session_key__in=keys).delete()
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='USER_DISABLED',
            ip_address=get_client_ip(request),
            details=f'Disabled user {u.username} and terminated {len(keys)} sessions.',
        )
        return Response({'detail': f'User {u.username} disabled.'})


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.select_related('student', 'student__current_class', 'received_by', 'approved_by', 'submitted_by', 'deposit_batch').all().order_by('-received_at')
    serializer_class = PaymentSerializer
    permission_classes = [IsFinanceUser]
    PROOF_PAYMENT_METHODS = {'bank'}

    def _can_manage_sensitive_payments(self, user) -> bool:
        role = get_role(user)
        return bool(user and user.is_authenticated and (user.is_superuser or role in ('superadmin', 'bursar')))

    def _can_approve_bank_slips(self, user) -> bool:
        # Approvals are restricted to Bursar or Super Admin.
        return self._can_manage_sensitive_payments(user)

    def _is_submitted_payment_proof(self, payment) -> bool:
        return bool(
            payment
            and (payment.submitted_by_id or payment.receipt_image_url)
            and (payment.method or '').lower() in self.PROOF_PAYMENT_METHODS
        )

    def _payment_proof_label(self, method) -> str:
        return f"{_payment_method_label(method)} proof"

    def get_queryset(self):
        qs = super().get_queryset()
        q = (self.request.query_params.get('q') or '').strip()
        student_pk = (self.request.query_params.get('student') or '').strip()
        status_v = (self.request.query_params.get('status') or '').strip()
        method_v = (self.request.query_params.get('method') or '').strip()
        class_id = (self.request.query_params.get('class_id') or '').strip()
        date_from = (self.request.query_params.get('date_from') or '').strip()
        date_to = (self.request.query_params.get('date_to') or '').strip()
        year_v = (self.request.query_params.get('academic_year') or '').strip()
        term_v = (self.request.query_params.get('term_number') or '').strip()
        batch_id = (self.request.query_params.get('deposit_batch') or '').strip()
        unbatched = (self.request.query_params.get('unbatched') or '').strip().lower()

        if student_pk.isdigit():
            qs = qs.filter(student_id=int(student_pk))
        if status_v:
            qs = qs.filter(status=status_v)
        if method_v:
            qs = qs.filter(method=method_v)
        if class_id.isdigit():
            qs = qs.filter(student__current_class_id=int(class_id))
        if year_v.isdigit():
            qs = qs.filter(academic_year=int(year_v))
        if term_v.isdigit():
            qs = qs.filter(term_number=int(term_v))
        if batch_id.isdigit():
            qs = qs.filter(deposit_batch_id=int(batch_id))
        if unbatched in ('1', 'true', 'yes'):
            qs = qs.filter(deposit_batch__isnull=True)
        if date_from:
            try:
                qs = qs.filter(received_at__date__gte=date.fromisoformat(date_from))
            except Exception:
                pass
        if date_to:
            try:
                qs = qs.filter(received_at__date__lte=date.fromisoformat(date_to))
            except Exception:
                pass
        if q:
            qs = qs.filter(
                Q(student__student_id__icontains=q)
                | Q(student__first_name__icontains=q)
                | Q(student__last_name__icontains=q)
                | Q(student__parent_name__icontains=q)
                | Q(student__parent_phone__icontains=q)
                | Q(reference__icontains=q)
                | Q(receipt_number__icontains=q)
            )
        return qs

    @action(detail=False, methods=['post'], url_path='bulk-review')
    def bulk_review(self, request):
        """
        Finance: bulk approve/reject submitted bank-payment proofs.
        Payload:
          { "ids": [1,2,3], "action": "approve"|"reject", "reason": "...", "review_notes": "..." }
        """
        data = request.data or {}
        ids = data.get('ids') or []
        action_v = (data.get('action') or '').strip().lower()
        reason = (data.get('reason') or '').strip()
        review_notes = (data.get('review_notes') or '').strip()

        if not (isinstance(ids, list) and ids):
            return Response({'detail': 'ids[] is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if action_v not in ('approve', 'reject'):
            return Response({'detail': 'action must be approve or reject.'}, status=status.HTTP_400_BAD_REQUEST)

        if not self._can_approve_bank_slips(request.user):
            return Response({'detail': 'Only Bursar or Super Admin can approve/reject submitted bank-payment proofs.'}, status=status.HTTP_403_FORBIDDEN)

        # Coerce ids to ints
        clean_ids = []
        for x in ids:
            try:
                clean_ids.append(int(x))
            except Exception:
                pass
        clean_ids = list(dict.fromkeys(clean_ids))[:400]
        if not clean_ids:
            return Response({'detail': 'No valid ids provided.'}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        d = timezone.localdate()
        updated = []
        skipped = 0

        with transaction.atomic():
            for pid in clean_ids:
                p = Payment.objects.select_related('student').filter(id=pid).first()
                if not p:
                    skipped += 1
                    continue

                # Only submitted proof payments are handled here.
                if not self._is_submitted_payment_proof(p):
                    skipped += 1
                    continue

                if action_v == 'approve':
                    if p.status not in ['pending', 'rejected']:
                        skipped += 1
                        continue
                    p.status = 'approved'
                    p.approved_by = request.user
                    p.approved_at = now
                    if review_notes:
                        p.review_notes = review_notes
                    if not p.receipt_number:
                        p.receipt_number = f"RCPT-{d.strftime('%Y%m%d')}-{p.id:06d}"
                    p.save(update_fields=['status', 'approved_by', 'approved_at', 'review_notes', 'receipt_number', 'updated_at'])
                    self._recompute_invoice(p.student_id, p.academic_year, p.term_number)
                    _refresh_finance_commitments(p.student, p.academic_year, p.term_number)
                    updated.append(p)
                    continue

                # reject
                if p.status not in ['pending']:
                    skipped += 1
                    continue
                p.status = 'rejected'
                if reason:
                    p.notes = (p.notes or '') + (('\n' if p.notes else '') + f"Rejected: {reason}")
                if review_notes:
                    p.review_notes = review_notes
                p.save(update_fields=['status', 'notes', 'review_notes', 'updated_at'])
                updated.append(p)

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PAYMENT_BULK_REVIEW',
            ip_address=get_client_ip(request),
            details=f'Bulk {action_v} payments count={len(updated)} skipped={skipped}.',
        )
        return Response({
            'action': action_v,
            'updated': len(updated),
            'skipped': skipped,
            'ids': [p.id for p in updated][:200],
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='export-csv')
    def export_csv(self, request):
        """
        Export filtered payments list as CSV (same filters as list endpoint).
        """
        import csv
        from django.utils.text import slugify

        qs = self.get_queryset().order_by('-received_at')[:5000]
        resp = HttpResponse(content_type='text/csv; charset=utf-8')
        d = timezone.localdate()
        fn = f"payments_{d.isoformat()}.csv"
        resp['Content-Disposition'] = f'attachment; filename="{slugify(fn) or fn}"'

        w = csv.writer(resp)
        w.writerow(['id', 'date', 'student_id', 'student_name', 'amount', 'method', 'status', 'term', 'reference', 'submitted_by', 'approved_by', 'receipt_number'])
        for p in qs:
            dt = p.received_at.isoformat(sep=' ', timespec='seconds') if p.received_at else ''
            term_lbl = f"T{p.term_number}/{p.academic_year}" if p.term_number and p.academic_year else ''
            w.writerow([
                p.id,
                dt,
                getattr(p.student, 'student_id', ''),
                f"{getattr(p.student, 'first_name', '')} {getattr(p.student, 'last_name', '')}".strip(),
                str(p.amount),
                p.method,
                p.status,
                term_lbl,
                p.reference or '',
                getattr(getattr(p, 'submitted_by', None), 'username', '') or '',
                getattr(getattr(p, 'approved_by', None), 'username', '') or '',
                p.receipt_number or '',
            ])
        return resp

    @action(detail=False, methods=['get'], url_path='mine', permission_classes=[permissions.IsAuthenticated])
    def mine(self, request):
        """
        Parent/student read-only payments history for their own account.
        """
        role = get_role(request.user)
        if role not in ['parent', 'student']:
            return Response({'detail': 'Only parent/student users can access this.'}, status=status.HTTP_403_FORBIDDEN)

        if role == 'student':
            stu, _, _ = get_student_scope(request.user)
            if not stu:
                return Response([])
            qs = Payment.objects.select_related('student', 'received_by').filter(student=stu).order_by('-received_at')[:120]
            return Response(PaymentSerializer(qs, many=True).data)

        phone = getattr(getattr(request.user, 'profile', None), 'phone_number', None)
        linked = list(StudentGuardianLink.objects.filter(parent_user=request.user, is_active=True).values_list('student_id', flat=True))
        kids = []
        if phone:
            kids += list(Student.objects.filter(Q(parent_phone=phone) | Q(parent_phone2=phone)).values_list('id', flat=True))
        kids += linked
        kids = list(set([int(k) for k in kids if str(k).isdigit()]))
        if not kids:
            return Response([])
        qs = Payment.objects.select_related('student', 'received_by').filter(student_id__in=list(kids)).order_by('-received_at')[:180]
        return Response(PaymentSerializer(qs, many=True).data)

    def perform_create(self, serializer):
        # Default: staff-created payments are immediately approved/received.
        payment = serializer.save(received_by=self.request.user)
        if payment.status in (None, '', 'pending'):
            payment.status = 'received'
        if payment.status in ('received', 'approved') and not payment.approved_at:
            payment.approved_by = self.request.user
            payment.approved_at = timezone.now()
        if payment.status in ('received', 'approved') and not payment.receipt_number:
            d = timezone.localdate()
            payment.receipt_number = f"RCPT-{d.strftime('%Y%m%d')}-{payment.id:06d}"
        payment.save(update_fields=['status', 'approved_by', 'approved_at', 'receipt_number', 'updated_at'])
        self._recompute_invoice(payment.student_id, payment.academic_year, payment.term_number)
        _refresh_finance_commitments(payment.student, payment.academic_year, payment.term_number)

        # In-app notifications (best-effort).
        try:
            # Finance staff get alerted about new payments.
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title='New payment received',
                message=f"{payment.student.student_id} {payment.student.first_name} {payment.student.last_name} paid UGX {payment.amount} via {payment.method}.",
                link_page='finance',
                link_object_id=payment.id,
                student=payment.student,
                school_class=getattr(payment.student, 'current_class', None),
                meta={'payment_id': payment.id, 'method': payment.method, 'amount': str(payment.amount)},
            )

            # Parent + student portals get alerted (if accounts exist).
            phones = [payment.student.parent_phone, payment.student.parent_phone2]
            phones = [p for p in phones if p]
            if phones:
                for pu in User.objects.filter(profile__phone_number__in=phones).distinct():
                    notify_user(
                        pu,
                        category='finance',
                        title='Payment received',
                        message=f"We received UGX {payment.amount} for {payment.student.first_name} {payment.student.last_name}.",
                        link_page='finance',
                        link_object_id=payment.id,
                        student=payment.student,
                        school_class=getattr(payment.student, 'current_class', None),
                        meta={'payment_id': payment.id, 'amount': str(payment.amount)},
                    )
            su = User.objects.filter(username=payment.student.student_id).first()
            if su:
                notify_user(
                    su,
                    category='finance',
                    title='Payment received',
                    message=f"Payment of UGX {payment.amount} was recorded for your account.",
                    link_page='finance',
                    link_object_id=payment.id,
                    student=payment.student,
                    school_class=getattr(payment.student, 'current_class', None),
                    meta={'payment_id': payment.id, 'amount': str(payment.amount)},
                )
        except Exception:
            pass

    def perform_update(self, serializer):
        # If year/term/student changes, recompute both old and new invoices.
        before = self.get_object()
        is_submitted_payment_proof = self._is_submitted_payment_proof(before)
        if is_submitted_payment_proof and not self._can_manage_sensitive_payments(self.request.user):
            raise PermissionDenied('Only Bursar or Super Admin can edit submitted payment-proof records.')
        old_student_id = before.student_id
        old_year = before.academic_year
        old_term = before.term_number
        payment = serializer.save()
        self._recompute_invoice(old_student_id, old_year, old_term)
        self._recompute_invoice(payment.student_id, payment.academic_year, payment.term_number)
        old_student = Student.objects.filter(id=old_student_id).first() if old_student_id else None
        if old_student and old_year and old_term:
            _refresh_finance_commitments(old_student, old_year, old_term)
        _refresh_finance_commitments(payment.student, payment.academic_year, payment.term_number)

    def _recompute_invoice(self, student_id, academic_year, term_number):
        if not student_id or not academic_year or not term_number:
            return
        inv = Invoice.objects.filter(student_id=student_id, academic_year=academic_year, term_number=term_number).first()
        if not inv:
            # Try to infer due from fee structure.
            stu = Student.objects.filter(id=student_id).select_related('current_class').first()
            due = Decimal('0')
            if stu and stu.current_class_id:
                fs = FeeStructure.objects.filter(school_class_id=stu.current_class_id, year=academic_year, term=term_number).first()
                if fs:
                    due = Decimal(str(fs.amount))
                else:
                    # Fallback: use annual fee / 3 when fee structure row is missing.
                    try:
                        due = (Decimal(str(stu.current_class.annual_fee)) / Decimal('3')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    except Exception:
                        due = Decimal('0')
            inv = Invoice.objects.create(student_id=student_id, academic_year=academic_year, term_number=term_number, amount_due=due)

        paid = Payment.objects.filter(
            student_id=student_id,
            academic_year=academic_year,
            term_number=term_number,
            status__in=['received', 'approved'],
        ).aggregate(s=Sum('amount'))['s'] or 0
        inv.amount_paid = paid
        if inv.amount_due <= 0:
            inv.status = 'paid' if paid > 0 else 'unpaid'
        elif paid <= 0:
            inv.status = 'unpaid'
        elif paid < inv.amount_due:
            inv.status = 'partial'
        else:
            inv.status = 'paid'
        inv.save()

    @action(detail=True, methods=['post'], url_path='reverse')
    def reverse(self, request, pk=None):
        if not self._can_manage_sensitive_payments(request.user):
            return Response({'detail': 'Only Bursar or Super Admin can reverse payments.'}, status=status.HTTP_403_FORBIDDEN)
        payment = self.get_object()
        payment.status = 'reversed'
        payment.save(update_fields=['status'])
        self._recompute_invoice(payment.student_id, payment.academic_year, payment.term_number)
        _refresh_finance_commitments(payment.student, payment.academic_year, payment.term_number)
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PAYMENT_REVERSED',
            ip_address=get_client_ip(request),
            details=f'Payment {payment.id} reversed for student {payment.student.student_id}.',
        )
        try:
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title='Payment reversed',
                message=f"Payment {payment.id} was reversed for {payment.student.student_id}.",
                link_page='finance',
                link_object_id=payment.id,
                student=payment.student,
                school_class=getattr(payment.student, 'current_class', None),
                meta={'payment_id': payment.id, 'status': 'reversed'},
            )
        except Exception:
            pass
        return Response(PaymentSerializer(payment).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """
        Finance: approve a pending submitted bank payment after reviewing receipt.
        """
        p = self.get_object()
        proof_label = self._payment_proof_label(p.method)
        if not self._can_approve_bank_slips(request.user):
            return Response({'detail': 'Only Bursar or Super Admin can approve submitted bank-payment proofs.'}, status=status.HTTP_403_FORBIDDEN)
        if (p.method or '').lower() not in self.PROOF_PAYMENT_METHODS:
            return Response({'detail': 'Only submitted bank payment proofs can be approved here.'}, status=status.HTTP_400_BAD_REQUEST)
        if not p.receipt_image_url:
            return Response({'detail': f'Missing {proof_label} image.'}, status=status.HTTP_400_BAD_REQUEST)
        if p.status not in ['pending', 'rejected']:
            return Response({'detail': 'Only pending/rejected payments can be approved.'}, status=status.HTTP_400_BAD_REQUEST)
        review_notes = ((request.data or {}).get('review_notes') or '').strip()
        p.status = 'approved'
        p.approved_by = request.user
        p.approved_at = timezone.now()
        if review_notes:
            p.review_notes = review_notes
        if not p.receipt_number:
            d = timezone.localdate()
            p.receipt_number = f"RCPT-{d.strftime('%Y%m%d')}-{p.id:06d}"
        p.save(update_fields=['status', 'approved_by', 'approved_at', 'receipt_number', 'review_notes', 'updated_at'])
        self._recompute_invoice(p.student_id, p.academic_year, p.term_number)
        _refresh_finance_commitments(p.student, p.academic_year, p.term_number)
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PAYMENT_APPROVED',
            ip_address=get_client_ip(request),
            details=f'Payment {p.id} approved for student {p.student.student_id}.',
        )
        try:
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title=f'{proof_label.title()} approved',
                message=f"{p.student.student_id} payment of UGX {p.amount} via {_payment_method_label(p.method)} was approved.",
                link_page='finance',
                link_object_id=p.id,
                student=p.student,
                school_class=getattr(p.student, 'current_class', None),
                meta={'payment_id': p.id, 'status': 'approved', 'method': p.method},
            )
        except Exception:
            pass
        return Response(PaymentSerializer(p).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='receipt', permission_classes=[permissions.IsAuthenticated])
    def receipt(self, request, pk=None):
        """
        Download/preview a PDF receipt.

        Finance users can access any receipt.
        Parent/student users can only access receipts for their own linked students.
        """
        p = self.get_object()
        role = get_role(request.user)
        if role in ['parent', 'student']:
            allowed = False
            if role == 'student':
                stu, _, _ = get_student_scope(request.user)
                allowed = bool(stu and p.student_id == stu.id)
            else:
                phone = getattr(getattr(request.user, 'profile', None), 'phone_number', None)
                linked = list(StudentGuardianLink.objects.filter(parent_user=request.user, is_active=True).values_list('student_id', flat=True))
                allowed = (p.student_id in linked) or (phone and phone in [p.student.parent_phone, p.student.parent_phone2])
            if not allowed:
                return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        # Ensure receipt number exists for printable receipts.
        if p.status in ('received', 'approved') and not p.receipt_number:
            d = timezone.localdate()
            p.receipt_number = f"RCPT-{d.strftime('%Y%m%d')}-{p.id:06d}"
            p.save(update_fields=['receipt_number', 'updated_at'])

        pdf_buffer = generate_payment_receipt_pdf(p)
        fn = f"receipt_{p.receipt_number or p.id}.pdf"
        return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        p = self.get_object()
        proof_label = self._payment_proof_label(p.method)
        if not self._can_approve_bank_slips(request.user):
            return Response({'detail': 'Only Bursar or Super Admin can reject submitted bank-payment proofs.'}, status=status.HTTP_403_FORBIDDEN)
        if (p.method or '').lower() not in self.PROOF_PAYMENT_METHODS:
            return Response({'detail': 'Only submitted bank payment proofs can be rejected here.'}, status=status.HTTP_400_BAD_REQUEST)
        if not p.receipt_image_url:
            return Response({'detail': f'Missing {proof_label} image.'}, status=status.HTTP_400_BAD_REQUEST)
        if p.status not in ['pending']:
            return Response({'detail': 'Only pending payments can be rejected.'}, status=status.HTTP_400_BAD_REQUEST)
        data = request.data or {}
        reason = (data.get('reason') or '').strip()
        review_notes = (data.get('review_notes') or '').strip()
        p.status = 'rejected'
        if reason:
            p.notes = (p.notes or '') + (('\n' if p.notes else '') + f"Rejected: {reason}")
        if review_notes:
            p.review_notes = review_notes
        p.save(update_fields=['status', 'notes', 'review_notes', 'updated_at'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PAYMENT_REJECTED',
            ip_address=get_client_ip(request),
            details=f'Payment {p.id} rejected for student {p.student.student_id}.',
        )
        try:
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title=f'{proof_label.title()} rejected',
                message=f"{p.student.student_id} payment of UGX {p.amount} via {_payment_method_label(p.method)} was rejected.",
                link_page='finance',
                link_object_id=p.id,
                student=p.student,
                school_class=getattr(p.student, 'current_class', None),
                meta={'payment_id': p.id, 'status': 'rejected', 'method': p.method},
            )
        except Exception:
            pass
        return Response(PaymentSerializer(p).data, status=status.HTTP_200_OK)


class PaymentSubmissionViewSet(viewsets.ViewSet):
    """
    Parent/Student payment intake:
    - bank slips stay manual and bursar-approved
    - mobile money requests are initiated against configured gateways
      and can later auto-post through callbacks or manual sync
    """
    permission_classes = [permissions.IsAuthenticated]
    PROOF_PAYMENT_METHODS = {'bank'}
    MOBILE_PAYMENT_METHODS = {'mtn_momo', 'airtel_money'}

    def _is_parent_of(self, user, student: Student) -> bool:
        try:
            role = get_role(user)
        except Exception:
            role = None
        if role != 'parent':
            return False
        try:
            if StudentGuardianLink.objects.filter(parent_user=user, student=student, is_active=True).exists():
                return True
        except Exception:
            pass
        ph = None
        try:
            ph = user.profile.phone_number
        except Exception:
            ph = None
        if not ph:
            return False
        return ph in [student.parent_phone, student.parent_phone2]

    def _submit_payment_proof(self, request, method: str):
        method = (method or '').strip().lower()
        role = get_role(request.user)
        if role not in ['parent', 'student']:
            return Response({'detail': 'Only parent/student can submit a bank payment slip.'}, status=status.HTTP_403_FORBIDDEN)
        if method not in self.PROOF_PAYMENT_METHODS:
            return Response({'detail': 'Unsupported bank payment method.'}, status=status.HTTP_400_BAD_REQUEST)

        student_id = (request.data or {}).get('student')
        amount = (request.data or {}).get('amount')
        academic_year = (request.data or {}).get('academic_year')
        term_number = (request.data or {}).get('term_number')
        receipt_image_url = (request.data or {}).get('receipt_image_url')
        reference = (request.data or {}).get('reference')
        purpose = ((request.data or {}).get('purpose') or '').strip()

        if not student_id or not amount or not receipt_image_url:
            return Response({'detail': 'student, amount, and receipt_image_url are required.'}, status=status.HTTP_400_BAD_REQUEST)

        stu = Student.objects.filter(id=student_id).first()
        if not stu:
            return Response({'detail': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)

        if role == 'parent' and not self._is_parent_of(request.user, stu):
            return Response({'detail': 'This student is not linked to your parent account.'}, status=status.HTTP_403_FORBIDDEN)
        if role == 'student':
            own_student, _, _ = get_student_scope(request.user)
            if not own_student or own_student.id != stu.id:
                return Response({'detail': 'You can only submit a bank payment slip for your own account.'}, status=status.HTTP_403_FORBIDDEN)
        if not purpose:
            purpose = f"School fees for {stu.first_name} {stu.last_name} ({stu.student_id})"
            if str(term_number).isdigit() and str(academic_year).isdigit():
                purpose = f"{purpose} - Term {int(term_number)} {int(academic_year)}"

        p = Payment.objects.create(
            student=stu,
            amount=amount,
            method=method,
            reference=(reference or '').strip() or None,
            academic_year=int(academic_year) if str(academic_year).isdigit() else None,
            term_number=int(term_number) if str(term_number).isdigit() else None,
            status='pending',
            receipt_image_url=str(receipt_image_url).strip(),
            notes=purpose,
            received_by=None,
            submitted_by=request.user,
        )

        try:
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title='Payment pending approval',
                message=f"{stu.student_id} submitted {_payment_method_label(method)} proof for UGX {p.amount}.",
                link_page='finance',
                link_object_id=p.id,
                student=stu,
                school_class=getattr(stu, 'current_class', None),
                meta={'payment_id': p.id, 'status': 'pending', 'method': method},
            )
        except Exception:
            pass

        return Response(PaymentSerializer(p).data, status=status.HTTP_201_CREATED)

    def _mobile_callback_url(self, request, method: str, cred):
        extra = getattr(cred, 'extra_data', None) or {}
        configured = (extra.get('callback_url') or '').strip()
        if configured:
            return configured
        suffix = 'mtn' if method == 'mtn_momo' else 'airtel'
        return request.build_absolute_uri(f'/api/payment-submissions/mobile-callback/{suffix}/')

    def _mobile_credential(self, method: str):
        return get_active_api_credential(method) or APICredential.objects.filter(service_name=method, is_active=True).first()

    def _mtn_access_token(self, cred):
        x = cred.extra_data or {}
        api_user = (cred.client_id or '').strip()
        api_secret = (cred.client_secret or '').strip()
        subscription_key = (cred.api_key or '').strip()
        environment = (x.get('environment') or 'sandbox').strip().lower()
        product = (x.get('product') or 'collection').strip().lower() or 'collection'
        base_url = (x.get('base_url') or '').strip().rstrip('/') or 'https://sandbox.momodeveloper.mtn.com'
        token_path = (x.get('token_path') or f'/{product}/token/').strip()
        if not token_path.startswith('/'):
            token_path = '/' + token_path
        auth_value = base64.b64encode(f'{api_user}:{api_secret}'.encode('utf-8')).decode('ascii')
        headers = {
            'Authorization': f'Basic {auth_value}',
            'Ocp-Apim-Subscription-Key': subscription_key,
            'Accept': 'application/json',
        }
        if environment:
            headers['X-Target-Environment'] = environment
        r = requests.post(f'{base_url}{token_path}', headers=headers, timeout=12)
        payload = {}
        try:
            payload = r.json() if r.content else {}
        except Exception:
            payload = {}
        token = payload.get('access_token') or ((payload.get('data') or {}).get('access_token') if isinstance(payload.get('data'), dict) else None)
        if r.status_code != 200 or not token:
            raise ValidationError(f"MTN token request failed: {payload or r.text}")
        return token, {'environment': environment, 'base_url': base_url, 'product': product, 'subscription_key': subscription_key}

    def _airtel_access_token(self, cred):
        x = cred.extra_data or {}
        client_id = (cred.client_id or '').strip()
        client_secret = (cred.client_secret or '').strip()
        api_key = (cred.api_key or '').strip()
        base_url = (x.get('base_url') or '').strip().rstrip('/')
        token_url = (x.get('token_url') or '').strip() or (base_url + '/auth/oauth2/token' if base_url else '')
        auth_style = (x.get('auth_style') or 'body').strip().lower()
        payload_format = (x.get('payload_format') or 'json').strip().lower()
        grant_type = (x.get('grant_type') or 'client_credentials').strip() or 'client_credentials'
        country = (x.get('country') or 'UG').strip()
        currency = (x.get('currency') or 'UGX').strip()
        headers = {'Accept': 'application/json'}
        body = {'grant_type': grant_type}
        if auth_style == 'basic':
            auth_value = base64.b64encode(f'{client_id}:{client_secret}'.encode('utf-8')).decode('ascii')
            headers['Authorization'] = f'Basic {auth_value}'
            if api_key:
                body['api_key'] = api_key
        else:
            body.update({'client_id': client_id, 'client_secret': client_secret})
            if api_key:
                body['api_key'] = api_key
        if country:
            headers['X-Country'] = country
        if currency:
            headers['X-Currency'] = currency
        if payload_format == 'form':
            r = requests.post(token_url, data=body, headers=headers, timeout=12)
        else:
            headers['Content-Type'] = 'application/json'
            r = requests.post(token_url, json=body, headers=headers, timeout=12)
        payload = {}
        try:
            payload = r.json() if r.content else {}
        except Exception:
            payload = {}
        token = payload.get('access_token') or ((payload.get('data') or {}).get('access_token') if isinstance(payload.get('data'), dict) else None)
        if not (200 <= r.status_code < 300) or not token:
            raise ValidationError(f"Airtel token request failed: {payload or r.text}")
        return token, {'base_url': base_url, 'country': country, 'currency': currency, 'api_key': api_key}

    def _mark_mobile_payment_received(self, payment, payload=None, provider_status='successful'):
        payment.status = 'received'
        payment.provider_status = provider_status
        payment.provider_payload = payload or {}
        payment.approved_at = payment.approved_at or timezone.now()
        if not payment.receipt_number:
            payment.receipt_number = _next_receipt_number(payment)
        payment.save(update_fields=['status', 'provider_status', 'provider_payload', 'approved_at', 'receipt_number', 'updated_at'])
        PaymentViewSet()._recompute_invoice(payment.student_id, payment.academic_year, payment.term_number)
        _refresh_finance_commitments(payment.student, payment.academic_year, payment.term_number)
        try:
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title='Mobile payment received',
                message=f"{payment.student.student_id} {payment.student.first_name} {payment.student.last_name} paid UGX {payment.amount} via {_payment_method_label(payment.method)}.",
                link_page='finance',
                link_object_id=payment.id,
                student=payment.student,
                school_class=getattr(payment.student, 'current_class', None),
                meta={'payment_id': payment.id, 'method': payment.method, 'amount': str(payment.amount), 'provider_status': provider_status},
            )
        except Exception:
            pass
        return payment

    def _mark_mobile_payment_failed(self, payment, payload=None, provider_status='failed'):
        payment.status = 'rejected'
        payment.provider_status = provider_status
        payment.provider_payload = payload or {}
        payment.save(update_fields=['status', 'provider_status', 'provider_payload', 'updated_at'])
        return payment

    def _resolve_mobile_payment(self, gateway_reference=None, provider_reference=None):
        if gateway_reference:
            payment = Payment.objects.filter(gateway_reference=gateway_reference).first()
            if payment:
                return payment
        if provider_reference:
            payment = Payment.objects.filter(reference=provider_reference).first()
            if payment:
                return payment
        return None

    def _mobile_payment_audit_meta(self, request, payment, phone):
        student = payment.student
        role = get_role(request.user)
        payer_name = f"{getattr(request.user, 'first_name', '')} {getattr(request.user, 'last_name', '')}".strip()
        purpose = f"School fees for {student.first_name} {student.last_name} ({student.student_id})"
        if payment.term_number and payment.academic_year:
            purpose = f"{purpose} - Term {payment.term_number} {payment.academic_year}"
        return {
            'payer_role': role,
            'payer_user_id': request.user.id,
            'payer_username': request.user.username,
            'payer_name': payer_name,
            'phone_number': phone,
            'selected_student_id': student.id,
            'selected_student_system_id': student.student_id,
            'selected_student_name': f"{student.first_name} {student.last_name}".strip(),
            'academic_year': payment.academic_year,
            'term_number': payment.term_number,
            'purpose': purpose,
        }

    def _initiate_mtn_payment(self, request, payment, phone, cred):
        token, meta = self._mtn_access_token(cred)
        x = cred.extra_data or {}
        request_path = (x.get('request_to_pay_path') or '/collection/v1_0/requesttopay').strip()
        if not request_path.startswith('/'):
            request_path = '/' + request_path
        status_path_template = (x.get('status_path_template') or '/collection/v1_0/requesttopay/{reference_id}').strip()
        callback_url = self._mobile_callback_url(request, 'mtn_momo', cred)
        headers = {
            'Authorization': f'Bearer {token}',
            'Ocp-Apim-Subscription-Key': meta['subscription_key'],
            'X-Reference-Id': payment.gateway_reference,
            'X-Target-Environment': meta['environment'],
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        body = {
            'amount': str(payment.amount),
            'currency': (x.get('currency') or 'UGX').strip() or 'UGX',
            'externalId': payment.reference or payment.gateway_reference,
            'payer': {'partyIdType': 'MSISDN', 'partyId': phone},
            'payerMessage': f'Bitende fees {payment.student.student_id}',
            'payeeNote': f'Term {payment.term_number or "-"} {payment.academic_year or "-"}',
        }
        r = requests.post(f"{meta['base_url']}{request_path}", json=body, headers=headers, timeout=15)
        payload = {}
        meta_payload = self._mobile_payment_audit_meta(request, payment, phone)
        try:
            payload = r.json() if r.content else {}
        except Exception:
            payload = {}
        payment.provider_payload = {
            'initiation': payload,
            'callback_url': callback_url,
            'status_path_template': status_path_template,
            'phone_number': phone,
            'audit': meta_payload,
        }
        payment.provider_status = 'pending'
        if not payment.notes:
            payment.notes = meta_payload['purpose']
        payment.save(update_fields=['provider_payload', 'provider_status', 'notes', 'updated_at'])
        if r.status_code not in (200, 201, 202):
            self._mark_mobile_payment_failed(payment, payload, f'http_{r.status_code}')
            raise ValidationError(f"MTN request-to-pay failed: {payload or r.text}")
        return {'detail': 'MTN mobile-money payment request sent.', 'payment': PaymentSerializer(payment).data, 'provider_response': payload}

    def _initiate_airtel_payment(self, request, payment, phone, cred):
        token, meta = self._airtel_access_token(cred)
        x = cred.extra_data or {}
        request_url = (x.get('request_url') or '').strip()
        if not request_url:
            base_url = meta.get('base_url') or (x.get('base_url') or '').strip().rstrip('/')
            request_path = (x.get('request_path') or '/merchant/v1/payments/').strip()
            if not request_path.startswith('/'):
                request_path = '/' + request_path
            request_url = f'{base_url}{request_path}'
        callback_url = self._mobile_callback_url(request, 'airtel_money', cred)
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        if meta.get('country'):
            headers['X-Country'] = meta['country']
        if meta.get('currency'):
            headers['X-Currency'] = meta['currency']
        if meta.get('api_key'):
            headers['x-api-key'] = meta['api_key']
        body = {
            'reference': payment.gateway_reference,
            'subscriber': {
                'country': meta.get('country') or 'UG',
                'currency': meta.get('currency') or 'UGX',
                'msisdn': phone,
            },
            'transaction': {
                'amount': str(payment.amount),
                'country': meta.get('country') or 'UG',
                'currency': meta.get('currency') or 'UGX',
                'id': payment.gateway_reference,
            },
            'callback_url': callback_url,
        }
        r = requests.post(request_url, json=body, headers=headers, timeout=15)
        payload = {}
        meta_payload = self._mobile_payment_audit_meta(request, payment, phone)
        try:
            payload = r.json() if r.content else {}
        except Exception:
            payload = {}
        payment.provider_payload = {
            'initiation': payload,
            'callback_url': callback_url,
            'request_url': request_url,
            'phone_number': phone,
            'audit': meta_payload,
        }
        payment.provider_status = 'pending'
        if not payment.notes:
            payment.notes = meta_payload['purpose']
        payment.save(update_fields=['provider_payload', 'provider_status', 'notes', 'updated_at'])
        if r.status_code not in (200, 201, 202):
            self._mark_mobile_payment_failed(payment, payload, f'http_{r.status_code}')
            raise ValidationError(f"Airtel payment request failed: {payload or r.text}")
        return {'detail': 'Airtel mobile-money payment request sent.', 'payment': PaymentSerializer(payment).data, 'provider_response': payload}

    def _sync_mobile_payment_status(self, payment):
        method = (payment.method or '').strip().lower()
        if method == 'mtn_momo':
            cred = self._mobile_credential(method)
            token, meta = self._mtn_access_token(cred)
            stored = payment.provider_payload or {}
            status_path_template = ((stored.get('status_path_template') if isinstance(stored, dict) else None) or '/collection/v1_0/requesttopay/{reference_id}').strip()
            status_path = status_path_template.replace('{reference_id}', payment.gateway_reference or '')
            headers = {
                'Authorization': f'Bearer {token}',
                'Ocp-Apim-Subscription-Key': meta['subscription_key'],
                'X-Target-Environment': meta['environment'],
                'Accept': 'application/json',
            }
            r = requests.get(f"{meta['base_url']}{status_path}", headers=headers, timeout=12)
            payload = {}
            try:
                payload = r.json() if r.content else {}
            except Exception:
                payload = {}
            status_value = payload.get('status') or payload.get('financialTransactionStatus') or payload.get('reason')
            if _mobile_provider_success(status_value):
                self._mark_mobile_payment_received(payment, payload, str(status_value or 'successful'))
            elif _mobile_provider_failure(status_value):
                self._mark_mobile_payment_failed(payment, payload, str(status_value or 'failed'))
            else:
                payment.provider_status = str(status_value or 'pending')
                payment.provider_payload = payload
                payment.save(update_fields=['provider_status', 'provider_payload', 'updated_at'])
            return payment

        if method == 'airtel_money':
            cred = self._mobile_credential(method)
            token, meta = self._airtel_access_token(cred)
            x = cred.extra_data or {}
            status_url = (x.get('status_url_template') or '').strip()
            if status_url:
                status_url = status_url.replace('{reference_id}', payment.gateway_reference or '')
            else:
                base_url = meta.get('base_url') or (x.get('base_url') or '').strip().rstrip('/')
                status_url = f"{base_url}/standard/v1/payments/{payment.gateway_reference or ''}"
            headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
            if meta.get('country'):
                headers['X-Country'] = meta['country']
            if meta.get('currency'):
                headers['X-Currency'] = meta['currency']
            if meta.get('api_key'):
                headers['x-api-key'] = meta['api_key']
            r = requests.get(status_url, headers=headers, timeout=12)
            payload = {}
            try:
                payload = r.json() if r.content else {}
            except Exception:
                payload = {}
            data_node = payload.get('data') if isinstance(payload.get('data'), dict) else {}
            txn = data_node.get('transaction') if isinstance(data_node.get('transaction'), dict) else {}
            status_value = payload.get('status') or txn.get('status') or data_node.get('status')
            if _mobile_provider_success(status_value):
                self._mark_mobile_payment_received(payment, payload, str(status_value or 'successful'))
            elif _mobile_provider_failure(status_value):
                self._mark_mobile_payment_failed(payment, payload, str(status_value or 'failed'))
            else:
                payment.provider_status = str(status_value or 'pending')
                payment.provider_payload = payload
                payment.save(update_fields=['provider_status', 'provider_payload', 'updated_at'])
            return payment

        return payment

    @action(detail=False, methods=['post'], url_path='proof')
    def proof(self, request):
        return self._submit_payment_proof(request, (request.data or {}).get('method'))

    @action(detail=False, methods=['post'], url_path='bank-slip')
    def bank_slip(self, request):
        return self._submit_payment_proof(request, 'bank')

    @action(detail=False, methods=['post'], url_path='mobile-initiate')
    def mobile_initiate(self, request):
        role = get_role(request.user)
        if role not in ['parent', 'student']:
            return Response({'detail': 'Only parent/student users can start a mobile payment.'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data or {}
        method = (data.get('method') or '').strip().lower()
        if method not in self.MOBILE_PAYMENT_METHODS:
            return Response({'detail': 'Unsupported mobile payment method.'}, status=status.HTTP_400_BAD_REQUEST)
        student_id = data.get('student')
        amount = data.get('amount')
        academic_year = data.get('academic_year')
        term_number = data.get('term_number')
        phone = _normalize_msisdn(data.get('phone_number'))
        if not student_id or not amount or not phone:
            return Response({'detail': 'student, amount, and phone_number are required.'}, status=status.HTTP_400_BAD_REQUEST)
        stu = Student.objects.filter(id=student_id).first()
        if not stu:
            return Response({'detail': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)
        if role == 'parent' and not self._is_parent_of(request.user, stu):
            return Response({'detail': 'This student is not linked to your parent account.'}, status=status.HTTP_403_FORBIDDEN)
        if role == 'student':
            own_student, _, _ = get_student_scope(request.user)
            if not own_student or own_student.id != stu.id:
                return Response({'detail': 'You can only start a mobile payment for your own account.'}, status=status.HTTP_403_FORBIDDEN)
        cred = self._mobile_credential(method)
        if not cred:
            return Response({'detail': f'No active {_payment_method_label(method)} credential is configured yet. Ask the super admin to finish API Credentials setup.'}, status=status.HTTP_400_BAD_REQUEST)
        gateway_reference = f"{method.upper()}-{uuid.uuid4().hex[:24]}"
        payment = Payment.objects.create(
            student=stu,
            amount=amount,
            method=method,
            reference=(data.get('reference') or '').strip() or gateway_reference,
            gateway_reference=gateway_reference,
            provider_name=method,
            provider_status='initiated',
            provider_payload={},
            academic_year=int(academic_year) if str(academic_year).isdigit() else None,
            term_number=int(term_number) if str(term_number).isdigit() else None,
            notes=(data.get('purpose') or '').strip() or None,
            status='pending',
            received_by=None,
            submitted_by=request.user,
        )
        try:
            if method == 'mtn_momo':
                result = self._initiate_mtn_payment(request, payment, phone, cred)
            else:
                result = self._initiate_airtel_payment(request, payment, phone, cred)
        except ValidationError as e:
            return Response({'detail': str(e), 'payment': PaymentSerializer(payment).data}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except Exception as e:
            self._mark_mobile_payment_failed(payment, {'error': str(e)}, 'error')
            return Response({'detail': f'Mobile payment request failed: {e}', 'payment': PaymentSerializer(payment).data}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(result, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=['post'], url_path='mobile-sync')
    def mobile_sync(self, request):
        payment_id = (request.data or {}).get('payment')
        payment = Payment.objects.filter(id=payment_id, method__in=list(self.MOBILE_PAYMENT_METHODS)).select_related('student').first()
        if not payment:
            return Response({'detail': 'Mobile payment not found.'}, status=status.HTTP_404_NOT_FOUND)
        role = get_role(request.user)
        if role == 'parent' and not self._is_parent_of(request.user, payment.student):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if role == 'student':
            own_student, _, _ = get_student_scope(request.user)
            if not own_student or own_student.id != payment.student_id:
                return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        if role not in ['parent', 'student', 'bursar', 'superadmin'] and not is_admin_role(role):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            payment = self._sync_mobile_payment_status(payment)
        except Exception as e:
            return Response({'detail': f'Could not sync payment right now: {e}'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(PaymentSerializer(payment).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='mobile-callback/mtn', permission_classes=[permissions.AllowAny])
    def mobile_callback_mtn(self, request):
        payload = request.data or {}
        gateway_reference = request.headers.get('X-Reference-Id') or payload.get('referenceId') or payload.get('reference_id') or payload.get('externalId')
        payment = self._resolve_mobile_payment(gateway_reference=gateway_reference, provider_reference=payload.get('externalId'))
        if not payment:
            return Response({'detail': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)
        status_value = payload.get('status') or payload.get('financialTransactionStatus') or payload.get('reason')
        if _mobile_provider_success(status_value):
            self._mark_mobile_payment_received(payment, payload, str(status_value or 'successful'))
        elif _mobile_provider_failure(status_value):
            self._mark_mobile_payment_failed(payment, payload, str(status_value or 'failed'))
        else:
            payment.provider_status = str(status_value or 'pending')
            payment.provider_payload = payload
            payment.save(update_fields=['provider_status', 'provider_payload', 'updated_at'])
        return Response({'ok': True}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='mobile-callback/airtel', permission_classes=[permissions.AllowAny])
    def mobile_callback_airtel(self, request):
        payload = request.data or {}
        txn = payload.get('transaction') if isinstance(payload.get('transaction'), dict) else {}
        data_node = payload.get('data') if isinstance(payload.get('data'), dict) else {}
        txn = txn or (data_node.get('transaction') if isinstance(data_node.get('transaction'), dict) else {})
        gateway_reference = payload.get('reference') or payload.get('txn_id') or txn.get('id') or payload.get('transaction_id')
        payment = self._resolve_mobile_payment(gateway_reference=gateway_reference, provider_reference=payload.get('airtel_money_id'))
        if not payment:
            return Response({'detail': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)
        status_value = payload.get('status') or txn.get('status') or data_node.get('status')
        if _mobile_provider_success(status_value):
            self._mark_mobile_payment_received(payment, payload, str(status_value or 'successful'))
        elif _mobile_provider_failure(status_value):
            self._mark_mobile_payment_failed(payment, payload, str(status_value or 'failed'))
        else:
            payment.provider_status = str(status_value or 'pending')
            payment.provider_payload = payload
            payment.save(update_fields=['provider_status', 'provider_payload', 'updated_at'])
        return Response({'ok': True}, status=status.HTTP_200_OK)


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.select_related('student').all().order_by('-academic_year', '-term_number', 'student__student_id')
    serializer_class = InvoiceSerializer
    permission_classes = [IsFinanceUser]

    def _can_manage_results_hold(self, user) -> bool:
        role = get_role(user)
        return bool(user and user.is_authenticated and (user.is_superuser or role in ['superadmin', 'bursar', 'headteacher', 'admin']))

    def get_permissions(self):
        if self.action == 'mine':
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        status_v = (self.request.query_params.get('status') or '').strip()
        year = (self.request.query_params.get('year') or '').strip()
        term = (self.request.query_params.get('term') or '').strip()
        q = (self.request.query_params.get('q') or '').strip()
        if status_v:
            qs = qs.filter(status=status_v)
        if year.isdigit():
            qs = qs.filter(academic_year=int(year))
        if term.isdigit():
            qs = qs.filter(term_number=int(term))
        if q:
            qs = qs.filter(
                Q(student__student_id__icontains=q)
                | Q(student__first_name__icontains=q)
                | Q(student__last_name__icontains=q)
            )
        return qs

    @action(detail=False, methods=['get'], url_path='mine', permission_classes=[permissions.IsAuthenticated])
    def mine(self, request):
        """
        Parent/student fee breakdown for the active term:
        base fee (invoice/fee structure) + additional class charges + paid + balance.
        """
        role = get_role(request.user)
        if role not in ['parent', 'student']:
            return Response({'detail': 'Only parent/student users can access this.'}, status=status.HTTP_403_FORBIDDEN)

        active_term = AcademicTerm.objects.filter(is_archived=False).order_by('-academic_year', '-term_number').first()
        if not active_term:
            return Response({'term': None, 'students': []})
        year = int(active_term.academic_year)
        term = int(active_term.term_number)

        def compute_for_student(stu):
            if not stu or not stu.current_class_id:
                return {
                    'student': StudentSerializer(stu).data if stu else None,
                    'academic_year': year,
                    'term_number': term,
                    'base_due': 0,
                    'extras_total': 0,
                    'total_due': 0,
                    'paid': 0,
                    'balance': 0,
                    'opening_balance': 0,
                    'arrears_brought_forward': 0,
                    'credit_brought_forward': 0,
                    'closing_balance': 0,
                    'charge_items': [],
                }

            opening = _opening_balance_before_term(stu, year, term)
            base_due = _base_due_for_term(stu, year, term)
            paid_in_term = _payments_for_term(stu, year, term)

            sec = (stu.section or '').strip().upper()
            cq = ClassCharge.objects.filter(
                school_class_id=stu.current_class_id,
                is_active=True,
                is_published=True,
            ).filter(Q(section__isnull=True) | Q(section='') | Q(section=sec)).filter(
                Q(academic_year__isnull=True) | Q(academic_year=year)
            ).filter(
                Q(term_number__isnull=True) | Q(term_number=term)
            ).order_by('due_date', 'title')
            items = ClassChargeSerializer(cq, many=True).data
            extras_total = sum([Decimal(str(c.get('amount') or 0)) for c in items], Decimal('0.00'))
            adj_now = _adjustments_for_term(stu, year, term)
            term_due = (base_due + extras_total + Decimal(str(adj_now))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            credit_bf = opening if opening > 0 else Decimal('0.00')
            arrears_bf = (-opening) if opening < 0 else Decimal('0.00')
            total_to_settle = (term_due + arrears_bf).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            available = (credit_bf + Decimal(str(paid_in_term or 0))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            paid_applied = min(available, total_to_settle)
            balance = (total_to_settle - paid_applied).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            closing = (available - total_to_settle).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            return {
                'student': StudentSerializer(stu).data,
                'academic_year': year,
                'term_number': term,
                'base_due': str(base_due),
                'extras_total': str(extras_total),
                'adjustments_total': str(Decimal(str(adj_now)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'total_due': str(total_to_settle),
                'paid': str(paid_applied),
                'balance': str(balance if balance > 0 else Decimal('0.00')),
                'opening_balance': str(opening),
                'arrears_brought_forward': str(arrears_bf),
                'credit_brought_forward': str(credit_bf),
                'closing_balance': str(closing),
                'charge_items': items,
            }

        if role == 'student':
            stu, _, _ = get_student_scope(request.user)
            if not stu:
                return Response({'term': AcademicTermSerializer(active_term).data, 'students': []})
            return Response({'term': AcademicTermSerializer(active_term).data, 'students': [compute_for_student(stu)]})

        phone = getattr(getattr(request.user, 'profile', None), 'phone_number', None)
        linked_ids = list(StudentGuardianLink.objects.filter(parent_user=request.user, is_active=True).values_list('student_id', flat=True))
        if not phone and not linked_ids:
            return Response({'term': AcademicTermSerializer(active_term).data, 'students': []})
        q = Q(id__in=linked_ids)
        if phone:
            q = q | Q(parent_phone=phone) | Q(parent_phone2=phone)
        kids = Student.objects.select_related('current_class').filter(q).order_by('current_class__level', 'section', 'student_id')
        return Response({'term': AcademicTermSerializer(active_term).data, 'students': [compute_for_student(s) for s in kids]})

    @action(detail=False, methods=['get'], url_path='statement', permission_classes=[permissions.IsAuthenticated])
    def statement(self, request):
        """
        Download a per-student fee statement PDF for an academic year.

        Query params:
          - student: Student.id (required)
          - year: academic year (required)

        Finance users can request any student.
        Parent/student users can only request linked students.
        """
        student_q = (request.query_params.get('student') or '').strip()
        year_q = (request.query_params.get('year') or '').strip()
        if not (student_q.isdigit() and year_q.isdigit()):
            return Response({'detail': 'student and year are required.'}, status=status.HTTP_400_BAD_REQUEST)
        student_id = int(student_q)
        year = int(year_q)

        stu = Student.objects.select_related('current_class').filter(id=student_id).first()
        if not stu:
            return Response({'detail': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)

        role = get_role(request.user)
        is_fin = IsFinanceUser().has_permission(request, self) or (role in ['superadmin', 'bursar'] or is_admin_role(role))
        if not is_fin:
            if role == 'student':
                ss, _, _ = get_student_scope(request.user)
                if not ss or ss.id != stu.id:
                    return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
            elif role == 'parent':
                phone = getattr(getattr(request.user, 'profile', None), 'phone_number', None)
                linked = list(StudentGuardianLink.objects.filter(parent_user=request.user, is_active=True).values_list('student_id', flat=True))
                ok = (stu.id in linked) or (phone and phone in [stu.parent_phone, stu.parent_phone2])
                if not ok:
                    return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
            else:
                return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        opening = _opening_balance_before_term(stu, year, 1)
        terms = []
        for tm in [1, 2, 3]:
            term_due = (_base_due_for_term(stu, year, tm) + _class_extras_for_term(stu, year, tm) + _adjustments_for_term(stu, year, tm)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            paid_now = _payments_for_term(stu, year, tm)

            credit_bf = opening if opening > 0 else Decimal('0.00')
            arrears_bf = (-opening) if opening < 0 else Decimal('0.00')
            total_to_settle = (term_due + arrears_bf).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            available = (credit_bf + paid_now).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            paid_applied = min(available, total_to_settle)
            balance_due = (total_to_settle - paid_applied).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            closing = (available - total_to_settle).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            terms.append({
                'term_number': tm,
                'opening_balance': str(opening),
                'term_due': str(term_due),
                'adjustments_total': str(_adjustments_for_term(stu, year, tm)),
                'paid_in_term': str(paid_now),
                'paid_applied': str(paid_applied),
                'balance_due': str(balance_due),
                'closing_balance': str(closing),
            })
            opening = closing

        pdf_buffer = generate_fee_statement_pdf(stu, year, terms)
        fn = f"statement_{stu.student_id}_{year}.pdf"
        return FileResponse(pdf_buffer, as_attachment=False, filename=fn, content_type='application/pdf')

    def perform_update(self, serializer):
        inv = serializer.save()
        # After changing amount_due, re-evaluate status.
        if inv.amount_due <= 0:
            inv.status = 'paid' if inv.amount_paid > 0 else 'unpaid'
        elif inv.amount_paid <= 0:
            inv.status = 'unpaid'
        elif inv.amount_paid < inv.amount_due:
            inv.status = 'partial'
        else:
            inv.status = 'paid'
        inv.save()
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='INVOICE_UPDATED',
            ip_address=get_client_ip(self.request),
            details=f'Invoice updated for {inv.student.student_id} T{inv.term_number}/{inv.academic_year}.',
        )

    @action(detail=False, methods=['get'], url_path='ledger')
    def ledger(self, request):
        """
        Staff finance dashboard helper.
        Computes a per-student ledger for the given year/term:
        - opening balance (credit +, arrears -) from prior terms within the same academic year
        - term due (base fee + class charges)
        - paid applied (opening credit + payments this term, capped by total due incl arrears)
        - balance due and closing balance (credit/arrears) for carry-forward
        """
        role = get_role(request.user)
        if not (role in ['superadmin', 'bursar'] or is_admin_role(role)):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        year_q = (request.query_params.get('year') or '').strip()
        term_q = (request.query_params.get('term') or '').strip()
        if not (year_q.isdigit() and term_q.isdigit()):
            return Response({'detail': 'year and term are required.'}, status=status.HTTP_400_BAD_REQUEST)
        year = int(year_q)
        term = int(term_q)
        if term not in [1, 2, 3]:
            return Response({'detail': 'term must be 1..3.'}, status=status.HTTP_400_BAD_REQUEST)

        out = []
        students = Student.objects.select_related('current_class').all()
        for stu in students:
            inv_now = Invoice.objects.filter(student=stu, academic_year=year, term_number=term).first()
            opening = _opening_balance_before_term(stu, year, term)
            adj_now = _adjustments_for_term(stu, year, term)
            term_due = (_base_due_for_term(stu, year, term) + _class_extras_for_term(stu, year, term) + adj_now).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            paid_now = _payments_for_term(stu, year, term)

            credit_bf = opening if opening > 0 else Decimal('0.00')
            arrears_bf = (-opening) if opening < 0 else Decimal('0.00')
            total_to_settle = (term_due + arrears_bf).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            available = (credit_bf + paid_now).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            paid_applied = min(available, total_to_settle)
            balance_due = (total_to_settle - paid_applied).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            closing = (available - total_to_settle).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            if balance_due <= Decimal('0.00'):
                status_s = 'paid'
            elif paid_applied > Decimal('0.00'):
                status_s = 'partial'
            else:
                status_s = 'unpaid'

            out.append({
                'student_id': stu.id,
                'student_system_id': stu.student_id,
                'student_name': f"{stu.first_name} {stu.last_name}".strip(),
                'class_level': getattr(stu.current_class, 'level', None),
                'section': (stu.section or '').strip(),
                'year': year,
                'term': term,
                'invoice_id': inv_now.id if inv_now else None,
                'results_blocked': bool(getattr(inv_now, 'results_blocked', False)) if inv_now else False,
                'results_block_reason': getattr(inv_now, 'results_block_reason', None) if inv_now else None,
                'opening_balance': str(opening),
                'credit_brought_forward': str(credit_bf),
                'arrears_brought_forward': str(arrears_bf),
                'term_due': str(term_due),
                'adjustments_total': str(adj_now),
                'paid_in_term': str(paid_now),
                'paid_applied': str(paid_applied),
                'balance_due': str(balance_due),
                'closing_balance': str(closing),
                'status': status_s,
            })

        return Response({'year': year, 'term': term, 'students': out})

    @action(detail=True, methods=['post'], url_path='block-results')
    def block_results(self, request, pk=None):
        inv = self.get_object()
        if not self._can_manage_results_hold(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        reason = ((request.data or {}).get('reason') or '').strip()
        inv.results_blocked = True
        inv.results_block_reason = reason or 'Fees not cleared'
        inv.results_blocked_by = request.user
        inv.results_blocked_at = timezone.now()
        inv.save(update_fields=['results_blocked', 'results_block_reason', 'results_blocked_by', 'results_blocked_at', 'updated_at'])
        ResultsHoldLog.objects.create(
            invoice=inv,
            action='held',
            reason=inv.results_block_reason,
            source='manual',
            acted_by=request.user,
            acted_at=inv.results_blocked_at or timezone.now(),
        )
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='RESULTS_BLOCKED',
            ip_address=get_client_ip(request),
            details=f'Blocked results for {inv.student.student_id} T{inv.term_number}/{inv.academic_year}.',
        )
        return Response(InvoiceSerializer(inv).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='unblock-results')
    def unblock_results(self, request, pk=None):
        inv = self.get_object()
        if not self._can_manage_results_hold(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        inv.results_blocked = False
        inv.results_block_reason = None
        inv.results_blocked_by = None
        inv.results_blocked_at = None
        inv.save(update_fields=['results_blocked', 'results_block_reason', 'results_blocked_by', 'results_blocked_at', 'updated_at'])
        ResultsHoldLog.objects.create(
            invoice=inv,
            action='released',
            reason='Manual release',
            source='manual',
            acted_by=request.user,
            acted_at=timezone.now(),
        )
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='RESULTS_UNBLOCKED',
            ip_address=get_client_ip(request),
            details=f'Unblocked results for {inv.student.student_id} T{inv.term_number}/{inv.academic_year}.',
        )
        return Response(InvoiceSerializer(inv).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='hold-results')
    def hold_results_bulk(self, request):
        """
        Bulk-hold results for defaulters in a term (optionally scoped to a class).
        Payload: { year, term, class_id?, reason? }
        """
        if not self._can_manage_results_hold(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        year = (request.data or {}).get('year')
        term = (request.data or {}).get('term')
        class_id = (request.data or {}).get('class_id')
        reason = ((request.data or {}).get('reason') or '').strip() or 'Outstanding fees'
        if not (str(year).isdigit() and str(term).isdigit()):
            return Response({'detail': 'year and term are required.'}, status=status.HTTP_400_BAD_REQUEST)
        year = int(year)
        term = int(term)
        qs = Invoice.objects.filter(academic_year=year, term_number=term, status__in=['unpaid', 'partial'])
        if str(class_id).isdigit():
            qs = qs.filter(student__current_class_id=int(class_id))
        now_ts = timezone.now()
        invoices = list(qs.select_related('student')[:5000])
        n = qs.update(
            results_blocked=True,
            results_block_reason=reason,
            results_blocked_by=request.user,
            results_blocked_at=now_ts,
        )
        ResultsHoldLog.objects.bulk_create([
            ResultsHoldLog(
                invoice=inv,
                action='held',
                reason=reason,
                source='bulk',
                acted_by=request.user,
                acted_at=now_ts,
            )
            for inv in invoices
        ])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='RESULTS_BULK_HELD',
            ip_address=get_client_ip(request),
            details=f'Bulk-held results count={n} T{term}/{year} class_id={class_id or ""}.',
        )
        return Response({'held': n}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='release-results')
    def release_results_bulk(self, request):
        """
        Bulk-release held results in a term (optionally scoped to a class).
        Payload: { year, term, class_id? }
        """
        if not self._can_manage_results_hold(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        year = (request.data or {}).get('year')
        term = (request.data or {}).get('term')
        class_id = (request.data or {}).get('class_id')
        if not (str(year).isdigit() and str(term).isdigit()):
            return Response({'detail': 'year and term are required.'}, status=status.HTTP_400_BAD_REQUEST)
        year = int(year)
        term = int(term)
        qs = Invoice.objects.filter(academic_year=year, term_number=term, results_blocked=True)
        if str(class_id).isdigit():
            qs = qs.filter(student__current_class_id=int(class_id))
        invoices = list(qs[:5000])
        n = qs.update(
            results_blocked=False,
            results_block_reason=None,
            results_blocked_by=None,
            results_blocked_at=None,
        )
        ResultsHoldLog.objects.bulk_create([
            ResultsHoldLog(
                invoice=inv,
                action='released',
                reason='Bulk release',
                source='bulk',
                acted_by=request.user,
                acted_at=timezone.now(),
            )
            for inv in invoices
        ])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='RESULTS_BULK_RELEASED',
            ip_address=get_client_ip(request),
            details=f'Bulk-released results count={n} T{term}/{year} class_id={class_id or ""}.',
        )
        return Response({'released': n}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='defaulters')
    def defaulters(self, request):
        """
        Convenience endpoint: invoices that are unpaid/partial for a given term/year.
        """
        year = (request.query_params.get('year') or '').strip()
        term = (request.query_params.get('term') or '').strip()
        qs = self.get_queryset().filter(status__in=['unpaid', 'partial'])
        if year.isdigit():
            qs = qs.filter(academic_year=int(year))
        if term.isdigit():
            qs = qs.filter(term_number=int(term))
        qs = qs.order_by('status', '-amount_due', 'student__student_id')[:300]
        return Response(InvoiceSerializer(qs, many=True).data)


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all().order_by('-start_date', '-created_at')
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role) or role == 'reception':
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_role(self.request.user)
        include_past = _truthy(self.request.query_params.get('include_past'))
        today = timezone.localdate()

        # Default: hide past events for everyone (staff can opt-in with include_past=1).
        if not include_past:
            qs = qs.filter(
                Q(end_date__gte=today) | (Q(end_date__isnull=True) & Q(start_date__gte=today))
            )

        is_staff = (role == 'superadmin' or is_admin_role(role) or role in ['reception', 'bursar'])
        if is_staff:
            return qs
        return qs.filter(is_published=True)

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        role = get_role(request.user)
        data = EventSerializer(qs, many=True).data
        # SQLite JSONField filtering can be limited; do audience filtering in Python.
        if role and not (role == 'superadmin' or is_admin_role(role) or role in ['reception', 'bursar']):
            def ok(ev):
                aud = ev.get('audience_roles') or []
                return (len(aud) == 0) or (role in aud)
            data = [ev for ev in data if ok(ev)]
        return Response(data)

    def perform_create(self, serializer):
        start_date = serializer.validated_data.get('start_date')
        end_date = serializer.validated_data.get('end_date') or start_date
        _require_term_window(start_date=start_date, end_date=end_date, allow_holiday_break=True, label='start_date')
        obj = serializer.save(created_by=self.request.user)
        # Notify audience roles (or all users if no roles selected).
        try:
            aud = obj.audience_roles or []
            roles = aud if aud else (['superadmin', 'reception', 'bursar'] + ADMIN_ROLE_LIST + ['teacher', 'parent', 'student'])
            notify_roles(
                roles,
                category='events',
                title='New event posted',
                message=f"{obj.title} ({obj.start_date}{' to ' + str(obj.end_date) if obj.end_date else ''})",
                link_page='events',
                link_object_id=obj.id,
            )
        except Exception:
            pass

    def perform_update(self, serializer):
        start_date = serializer.validated_data.get('start_date', serializer.instance.start_date)
        end_date = serializer.validated_data.get('end_date', serializer.instance.end_date) or start_date
        _require_term_window(start_date=start_date, end_date=end_date, allow_holiday_break=True, label='start_date')
        obj = serializer.save()
        try:
            aud = obj.audience_roles or []
            roles = aud if aud else (['superadmin', 'reception', 'bursar'] + ADMIN_ROLE_LIST + ['teacher', 'parent', 'student'])
            notify_roles(
                roles,
                category='events',
                title='Event updated',
                message=f"{obj.title}",
                link_page='events',
                link_object_id=obj.id,
            )
        except Exception:
            pass

    @action(detail=False, methods=['post'], url_path='from-template')
    def from_template(self, request):
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role == 'reception'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        template_id = (request.data.get('template_id') or request.data.get('document_template') or '')
        if not str(template_id).isdigit():
            return Response({'detail': 'template_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        template = DocumentDraft.objects.filter(id=int(template_id)).first()
        if not template:
            return Response({'detail': 'Template not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not _role_matches_library_scope(role, template.library_scope):
            return Response({'detail': 'Template library scope does not allow this role.'}, status=status.HTTP_403_FORBIDDEN)

        start_date = (request.data.get('start_date') or '').strip()
        if not start_date:
            return Response({'detail': 'start_date is required.'}, status=status.HTTP_400_BAD_REQUEST)
        end_date = (request.data.get('end_date') or '').strip() or None

        mapping = {
            'today': timezone.localdate().isoformat(),
            'start_date': start_date,
            'end_date': end_date or '',
            'school_name': (get_system_setting('school_branding', {}) or {}).get('school_name', 'Bitende Junior School'),
        }
        title = (request.data.get('title') or '').strip() or _safe_format_template(template.title, mapping)
        description = (request.data.get('description') or '').strip() or rich_text_to_plain_text(
            _compose_document_body(template, mapping, _safe_format_template(template.body, mapping))
        )
        obj = Event.objects.create(
            title=title,
            description=description,
            start_date=start_date,
            end_date=end_date,
            image_url=(request.data.get('image_url') or '').strip() or None,
            audience_roles=request.data.get('audience_roles') or [],
            is_published=bool(request.data.get('is_published', True)),
            created_by=request.user,
        )
        return Response(EventSerializer(obj).data, status=status.HTTP_201_CREATED)


class SystemSettingViewSet(viewsets.ModelViewSet):
    queryset = SystemSetting.objects.all().order_by('key')
    serializer_class = SystemSettingSerializer
    permission_classes = [IsSuperUser]

    @action(detail=False, methods=['post'], url_path='bulk')
    def bulk(self, request):
        """
        Upsert multiple settings in one request.
        Payload: { "items": [ {"key":"...", "value": ...}, ... ] }
        """
        items = request.data.get('items') or []
        if not isinstance(items, list):
            return Response({'detail': 'items must be a list.'}, status=status.HTTP_400_BAD_REQUEST)
        out = []
        for it in items:
            k = (it.get('key') or '').strip()
            if not k:
                continue
            v = it.get('value')
            obj, _ = SystemSetting.objects.update_or_create(key=k, defaults={'value': v})
            cache.delete(f"sysset:{k}")
            out.append(SystemSettingSerializer(obj).data)
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='SYSTEM_SETTINGS_UPDATED',
            ip_address=get_client_ip(request),
            details=f'Updated {len(out)} system settings.',
        )
        return Response(out, status=status.HTTP_200_OK)


class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all().order_by('-created_at')
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset().filter(user=self.request.user).select_related('student', 'school_class')
        cat = (self.request.query_params.get('category') or '').strip()
        unread = (self.request.query_params.get('unread') or '').strip().lower()
        student_q = (self.request.query_params.get('student') or '').strip()
        class_q = (self.request.query_params.get('class_id') or '').strip()
        q = (self.request.query_params.get('q') or '').strip()
        if cat:
            qs = qs.filter(category=cat)
        if unread in ('1', 'true', 'yes'):
            qs = qs.filter(is_read=False)
        if student_q.isdigit():
            qs = qs.filter(student_id=int(student_q))
        if class_q.isdigit():
            qs = qs.filter(school_class_id=int(class_q))
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(message__icontains=q)
                | Q(student__student_id__icontains=q)
                | Q(student__first_name__icontains=q)
                | Q(student__last_name__icontains=q)
                | Q(school_class__level__icontains=q)
            )
        return qs

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        qs = self.get_queryset()
        by_category = {
            row['category']: row['total']
            for row in qs.values('category').annotate(total=Count('id'))
        }
        unread_count = qs.filter(is_read=False).count()
        class_rows = []
        for row in (
            qs.filter(school_class__isnull=False)
            .values('school_class_id', 'school_class__level')
            .annotate(total=Count('id'))
            .order_by('school_class__level')[:12]
        ):
            class_rows.append({
                'class_id': row['school_class_id'],
                'class_level': row['school_class__level'],
                'total': row['total'],
            })
        return Response({
            'total': qs.count(),
            'unread_count': unread_count,
            'by_category': by_category,
            'by_class': class_rows,
        })

    def perform_create(self, serializer):
        # Do not allow clients to create notifications (prevents abuse).
        raise PermissionDenied("Notifications are system-generated.")

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        n = self.get_object()
        if not n.is_read:
            n.is_read = True
            n.read_at = timezone.now()
            n.save(update_fields=['is_read', 'read_at'])
        return Response(NotificationSerializer(n).data)

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        now = timezone.now()
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True, read_at=now)
        return Response({'detail': 'All notifications marked read.'})


class AnnouncementViewSet(viewsets.ModelViewSet):
    queryset = Announcement.objects.all().order_by('-is_pinned', '-created_at')
    serializer_class = AnnouncementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        role = get_role(self.request.user)
        if role == 'superadmin' or is_admin_role(role) or role == 'reception':
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        role = get_role(request.user)
        data = AnnouncementSerializer(qs, many=True).data

        is_staff = (role == 'superadmin' or is_admin_role(role) or role in ['reception', 'bursar'])
        include_archived = is_staff and _truthy(request.query_params.get('include_archived'))
        include_expired = is_staff and _truthy(request.query_params.get('include_expired'))
        now = timezone.now()

        def audience_ok(a):
            aud = a.get('audience_roles') or []
            return (len(aud) == 0) or (role in aud)

        def active_ok(a):
            if (not include_archived) and a.get('is_archived'):
                return False
            exp = a.get('expires_at')
            if (not include_expired) and exp:
                try:
                    # DRF default ISO format.
                    if datetime.fromisoformat(str(exp).replace('Z', '+00:00')) <= now:
                        return False
                except Exception:
                    # If parsing fails, don't hide it unexpectedly.
                    pass
            return True

        if not is_staff:
            data = [a for a in data if a.get('is_published') and audience_ok(a) and active_ok(a)]
        else:
            # staff sees drafts, but still respects archive/expiry unless they include them.
            data = [a for a in data if audience_ok(a) and active_ok(a)]

        return Response(data)

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='ANNOUNCEMENT_CREATED',
            ip_address=get_client_ip(self.request),
            details=f'Announcement created: {obj.title}',
        )
        try:
            aud = obj.audience_roles or []
            roles = aud if aud else (['superadmin', 'reception', 'bursar'] + ADMIN_ROLE_LIST + ['teacher', 'parent', 'student'])
            notify_roles(
                roles,
                category='system',
                title='New announcement',
                message=obj.title,
                link_page='announcements',
                link_object_id=obj.id,
            )
        except Exception:
            pass

    def perform_update(self, serializer):
        obj = serializer.save()
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='ANNOUNCEMENT_UPDATED',
            ip_address=get_client_ip(self.request),
            details=f'Announcement updated: {obj.title}',
        )
        try:
            aud = obj.audience_roles or []
            roles = aud if aud else (['superadmin', 'reception', 'bursar'] + ADMIN_ROLE_LIST + ['teacher', 'parent', 'student'])
            notify_roles(
                roles,
                category='system',
                title='Announcement updated',
                message=obj.title,
                link_page='announcements',
                link_object_id=obj.id,
            )
        except Exception:
            pass

    @action(detail=False, methods=['post'], url_path='from-template')
    def from_template(self, request):
        role = get_role(request.user)
        if not (role == 'superadmin' or is_admin_role(role) or role == 'reception'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        template_id = (request.data.get('template_id') or request.data.get('document_template') or '')
        if not str(template_id).isdigit():
            return Response({'detail': 'template_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        template = DocumentDraft.objects.filter(id=int(template_id)).first()
        if not template:
            return Response({'detail': 'Template not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not _role_matches_library_scope(role, template.library_scope):
            return Response({'detail': 'Template library scope does not allow this role.'}, status=status.HTTP_403_FORBIDDEN)

        mapping = {
            'today': timezone.localdate().isoformat(),
            'school_name': (get_system_setting('school_branding', {}) or {}).get('school_name', 'Bitende Junior School'),
        }
        title = (request.data.get('title') or '').strip() or _safe_format_template(template.title, mapping)
        body = (request.data.get('body') or '').strip() or _compose_document_body(template, mapping, _safe_format_template(template.body, mapping))
        body = sanitize_rich_text_html(body)
        if not body:
            return Response({'detail': 'Announcement body is required.'}, status=status.HTTP_400_BAD_REQUEST)
        obj = Announcement.objects.create(
            title=title,
            body=body,
            image_url=(request.data.get('image_url') or '').strip() or None,
            audience_roles=request.data.get('audience_roles') or [],
            is_published=bool(request.data.get('is_published', True)),
            is_pinned=bool(request.data.get('is_pinned', False)),
            expires_at=request.data.get('expires_at') or None,
            created_by=request.user,
        )
        return Response(AnnouncementSerializer(obj).data, status=status.HTTP_201_CREATED)


class InvoiceAdjustmentViewSet(viewsets.ModelViewSet):
    queryset = InvoiceAdjustment.objects.select_related('student', 'created_by').all().order_by('-academic_year', '-term_number', '-created_at')
    serializer_class = InvoiceAdjustmentSerializer
    permission_classes = [IsFinanceUser]

    def get_queryset(self):
        qs = super().get_queryset()
        year = (self.request.query_params.get('year') or '').strip()
        term = (self.request.query_params.get('term') or '').strip()
        student_id = (self.request.query_params.get('student') or '').strip()
        kind = (self.request.query_params.get('kind') or '').strip()
        active = (self.request.query_params.get('active') or '').strip()

        if year.isdigit():
            qs = qs.filter(academic_year=int(year))
        if term.isdigit():
            qs = qs.filter(term_number=int(term))
        if student_id.isdigit():
            qs = qs.filter(student_id=int(student_id))
        if kind:
            qs = qs.filter(kind=kind)
        if active in ['0', '1']:
            qs = qs.filter(is_active=(active == '1'))
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='INVOICE_ADJUSTMENT_CREATED',
            ip_address=get_client_ip(self.request),
            details=f'Adjustment created for student_id={obj.student_id} T{obj.term_number}/{obj.academic_year} kind={obj.kind} amount={obj.amount}.',
        )

    def perform_update(self, serializer):
        obj = serializer.save()
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='INVOICE_ADJUSTMENT_UPDATED',
            ip_address=get_client_ip(self.request),
            details=f'Adjustment updated id={obj.id} student_id={obj.student_id} T{obj.term_number}/{obj.academic_year}.',
        )

    def perform_destroy(self, instance):
        sid = instance.student_id
        y = instance.academic_year
        t = instance.term_number
        iid = instance.id
        instance.delete()
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='INVOICE_ADJUSTMENT_DELETED',
            ip_address=get_client_ip(self.request),
            details=f'Adjustment deleted id={iid} student_id={sid} T{t}/{y}.',
        )


class StudentGuardianLinkViewSet(viewsets.ModelViewSet):
    queryset = StudentGuardianLink.objects.select_related('parent_user', 'student', 'created_by').all().order_by('-created_at')
    serializer_class = StudentGuardianLinkSerializer
    permission_classes = [IsStaffAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        parent = (self.request.query_params.get('parent_user') or '').strip()
        student = (self.request.query_params.get('student') or '').strip()
        active = (self.request.query_params.get('active') or '').strip()
        if parent.isdigit():
            qs = qs.filter(parent_user_id=int(parent))
        if student.isdigit():
            qs = qs.filter(student_id=int(student))
        if active in ['0', '1']:
            qs = qs.filter(is_active=(active == '1'))
        return qs

    def perform_create(self, serializer):
        parent_user = serializer.validated_data.get('parent_user')
        if not parent_user:
            raise ValidationError('parent_user is required.')
        role = get_role(parent_user)
        if role != 'parent':
            raise ValidationError('parent_user must have role=parent.')

        obj = serializer.save(created_by=self.request.user)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='GUARDIAN_LINK_CREATED',
            ip_address=get_client_ip(self.request),
            details=f'Linked parent_user_id={obj.parent_user_id} to student_id={obj.student_id} rel={obj.relationship}.',
        )

    def perform_update(self, serializer):
        obj = serializer.save()
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='GUARDIAN_LINK_UPDATED',
            ip_address=get_client_ip(self.request),
            details=f'Guardian link updated id={obj.id} active={obj.is_active}.',
        )


class DepositBatchViewSet(viewsets.ModelViewSet):
    queryset = DepositBatch.objects.all().order_by('-deposit_date', '-created_at')
    serializer_class = DepositBatchSerializer
    permission_classes = [IsFinanceUser]

    def get_queryset(self):
        qs = super().get_queryset()
        q = (self.request.query_params.get('q') or '').strip()
        posted = (self.request.query_params.get('posted') or '').strip().lower()
        date_from = (self.request.query_params.get('date_from') or '').strip()
        date_to = (self.request.query_params.get('date_to') or '').strip()
        if posted in ('1', 'true', 'yes'):
            qs = qs.filter(is_posted=True)
        if posted in ('0', 'false', 'no'):
            qs = qs.filter(is_posted=False)
        if date_from:
            try:
                qs = qs.filter(deposit_date__gte=date.fromisoformat(date_from))
            except Exception:
                pass
        if date_to:
            try:
                qs = qs.filter(deposit_date__lte=date.fromisoformat(date_to))
            except Exception:
                pass
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(bank_name__icontains=q) | Q(reference__icontains=q))
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='DEPOSIT_BATCH_CREATED',
            ip_address=get_client_ip(self.request),
            details=f'Created deposit batch id={obj.id}.',
        )

    @action(detail=True, methods=['get'], url_path='payments')
    def payments(self, request, pk=None):
        """
        List payments assigned to this deposit batch.
        """
        batch = self.get_object()
        qs = (
            Payment.objects.filter(deposit_batch=batch)
            .select_related('student', 'approved_by', 'submitted_by', 'received_by')
            .order_by('received_at', 'id')
        )[:2000]
        return Response(PaymentSerializer(qs, many=True).data)

    @action(detail=True, methods=['get'], url_path='report')
    def report(self, request, pk=None):
        """
        PDF report for reconciliation/printing.
        """
        batch = self.get_object()
        qs = (
            Payment.objects.filter(deposit_batch=batch)
            .select_related('student', 'approved_by', 'submitted_by', 'received_by')
            .order_by('received_at', 'id')
        )
        school_name = getattr(settings, "SCHOOL_NAME", None) or "Bitende Junior School"
        pdf = generate_deposit_batch_report_pdf(batch, qs, school_name=school_name)
        fname = f"deposit_batch_{batch.id}_{(batch.deposit_date.isoformat() if batch.deposit_date else 'report')}.pdf"
        return FileResponse(pdf, as_attachment=True, filename=fname, content_type='application/pdf')

    @action(detail=True, methods=['post'], url_path='add-payments')
    def add_payments(self, request, pk=None):
        batch = self.get_object()
        if batch.is_posted:
            return Response({'detail': 'Cannot modify a posted batch.'}, status=status.HTTP_400_BAD_REQUEST)
        ids = (request.data or {}).get('ids') or []
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'ids[] is required.'}, status=status.HTTP_400_BAD_REQUEST)
        clean = []
        for x in ids:
            try:
                clean.append(int(x))
            except Exception:
                pass
        clean = list(dict.fromkeys(clean))[:500]
        if not clean:
            return Response({'detail': 'No valid ids.'}, status=status.HTTP_400_BAD_REQUEST)
        qs = Payment.objects.filter(id__in=clean, method='bank', status__in=['approved', 'received'], deposit_batch__isnull=True)
        n = qs.update(deposit_batch=batch)
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='DEPOSIT_BATCH_ADD_PAYMENTS',
            ip_address=get_client_ip(request),
            details=f'Batch id={batch.id} added payments={n}.',
        )
        return Response({'added': n})

    @action(detail=True, methods=['post'], url_path='remove-payments')
    def remove_payments(self, request, pk=None):
        batch = self.get_object()
        if batch.is_posted:
            return Response({'detail': 'Cannot modify a posted batch.'}, status=status.HTTP_400_BAD_REQUEST)
        ids = (request.data or {}).get('ids') or []
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'ids[] is required.'}, status=status.HTTP_400_BAD_REQUEST)
        clean = []
        for x in ids:
            try:
                clean.append(int(x))
            except Exception:
                pass
        clean = list(dict.fromkeys(clean))[:500]
        n = Payment.objects.filter(id__in=clean, deposit_batch=batch).update(deposit_batch=None)
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='DEPOSIT_BATCH_REMOVE_PAYMENTS',
            ip_address=get_client_ip(request),
            details=f'Batch id={batch.id} removed payments={n}.',
        )
        return Response({'removed': n})

    @action(detail=True, methods=['post'], url_path='mark-posted')
    def mark_posted(self, request, pk=None):
        batch = self.get_object()
        batch.is_posted = True
        batch.posted_at = timezone.now()
        batch.posted_by = request.user
        batch.save(update_fields=['is_posted', 'posted_at', 'posted_by', 'updated_at'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='DEPOSIT_BATCH_POSTED',
            ip_address=get_client_ip(request),
            details=f'Posted deposit batch id={batch.id}.',
        )
        return Response(DepositBatchSerializer(batch).data)


class CashbookCloseViewSet(viewsets.ModelViewSet):
    queryset = CashbookClose.objects.select_related('cashier', 'closed_by').all().order_by('-close_date', '-created_at')
    serializer_class = CashbookCloseSerializer
    permission_classes = [IsFinanceUser]

    def get_queryset(self):
        qs = super().get_queryset()
        close_date_q = (self.request.query_params.get('close_date') or '').strip()
        cashier_q = (self.request.query_params.get('cashier') or '').strip()
        status_q = (self.request.query_params.get('status') or '').strip()
        q = (self.request.query_params.get('q') or '').strip()
        if close_date_q:
            try:
                qs = qs.filter(close_date=date.fromisoformat(close_date_q))
            except Exception:
                pass
        if cashier_q.isdigit():
            qs = qs.filter(cashier_id=int(cashier_q))
        if status_q:
            qs = qs.filter(status=status_q)
        if q:
            qs = qs.filter(Q(notes__icontains=q) | Q(cashier__username__icontains=q) | Q(closed_by__username__icontains=q))
        return qs

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        close_date_q = (request.query_params.get('close_date') or '').strip()
        cashier_q = (request.query_params.get('cashier') or '').strip()
        opening_cash = request.query_params.get('opening_cash') or '0'
        counted_cash_on_hand = request.query_params.get('counted_cash_on_hand') or '0'
        try:
            close_date_v = date.fromisoformat(close_date_q) if close_date_q else timezone.localdate()
        except Exception:
            return Response({'detail': 'Invalid close_date.'}, status=status.HTTP_400_BAD_REQUEST)
        cashier = User.objects.filter(id=int(cashier_q)).first() if cashier_q.isdigit() else None
        return Response(_build_cashbook_snapshot(
            close_date_v,
            cashier=cashier,
            opening_cash=opening_cash,
            counted_cash_on_hand=counted_cash_on_hand,
        ))

    @action(detail=False, methods=['get'], url_path='handover')
    def handover(self, request):
        close_date_q = (request.query_params.get('close_date') or '').strip()
        cashier_q = (request.query_params.get('cashier') or '').strip()
        try:
            close_date_v = date.fromisoformat(close_date_q) if close_date_q else timezone.localdate()
        except Exception:
            return Response({'detail': 'Invalid close_date.'}, status=status.HTTP_400_BAD_REQUEST)
        cashier = User.objects.filter(id=int(cashier_q)).first() if cashier_q.isdigit() else None
        summary = _build_cashbook_handover(close_date_v, cashier=cashier)
        due, cutoff_raw = _handover_alert_is_due()
        summary['alerts'] = _handover_alert_context(summary)
        summary['handover_alert_due'] = bool(due and summary['alerts'])
        summary['handover_alert_time'] = cutoff_raw
        created = _ensure_cashbook_handover_notification(request.user, summary)
        summary['handover_alert_notified'] = bool(created)
        return Response(summary)

    def perform_create(self, serializer):
        close_date_v = serializer.validated_data.get('close_date') or timezone.localdate()
        cashier = serializer.validated_data.get('cashier')
        opening_cash = serializer.validated_data.get('opening_cash') or Decimal('0.00')
        counted_cash_on_hand = serializer.validated_data.get('counted_cash_on_hand') or Decimal('0.00')
        snapshot = _build_cashbook_snapshot(
            close_date_v,
            cashier=cashier,
            opening_cash=opening_cash,
            counted_cash_on_hand=counted_cash_on_hand,
        )
        obj = serializer.save(
            status='closed',
            cash_received_total=_to_decimal(snapshot.get('cash_received_total')),
            non_cash_received_total=_to_decimal(snapshot.get('non_cash_received_total')),
            approved_expense_total=_to_decimal(snapshot.get('approved_expense_total')),
            expected_cash_on_hand=_to_decimal(snapshot.get('expected_cash_on_hand')),
            variance_amount=_to_decimal(snapshot.get('variance_amount')),
            deposit_batch_total=_to_decimal(snapshot.get('deposit_batch_total')),
            payment_count=int(snapshot.get('payment_count') or 0),
            expense_count=int(snapshot.get('expense_count') or 0),
            snapshot=snapshot,
            closed_by=self.request.user,
            closed_at=timezone.now(),
        )
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='CASHBOOK_CLOSED',
            ip_address=get_client_ip(self.request),
            details=f'Closed cashbook id={obj.id} date={obj.close_date} cashier_id={obj.cashier_id or ""}.',
        )

    @action(detail=True, methods=['get'], url_path='report')
    def report(self, request, pk=None):
        obj = self.get_object()
        school_name = getattr(settings, "SCHOOL_NAME", None) or "Bitende Junior School"
        pdf = generate_cashbook_close_pdf(obj, school_name=school_name)
        fname = f"cashbook_{obj.id}_{obj.close_date.isoformat()}.pdf"
        return FileResponse(pdf, as_attachment=True, filename=fname, content_type='application/pdf')

    @action(detail=False, methods=['get'], url_path='handover-report')
    def handover_report(self, request):
        close_date_q = (request.query_params.get('close_date') or '').strip()
        cashier_q = (request.query_params.get('cashier') or '').strip()
        try:
            close_date_v = date.fromisoformat(close_date_q) if close_date_q else timezone.localdate()
        except Exception:
            return Response({'detail': 'Invalid close_date.'}, status=status.HTTP_400_BAD_REQUEST)
        cashier = User.objects.filter(id=int(cashier_q)).first() if cashier_q.isdigit() else None
        summary = _build_cashbook_handover(close_date_v, cashier=cashier)
        school_name = getattr(settings, "SCHOOL_NAME", None) or "Bitende Junior School"
        pdf = generate_cashier_handover_pdf(summary, school_name=school_name)
        scope = getattr(cashier, 'username', None) or 'school'
        fname = f"cashier_handover_{scope}_{close_date_v.isoformat()}.pdf"
        return FileResponse(pdf, as_attachment=True, filename=fname, content_type='application/pdf')


class InstallmentPlanViewSet(viewsets.ModelViewSet):
    queryset = InstallmentPlan.objects.select_related('student', 'invoice', 'created_by', 'approved_by').prefetch_related('items').all().order_by('-created_at')
    serializer_class = InstallmentPlanSerializer
    permission_classes = [IsFinanceUser]

    def get_queryset(self):
        qs = super().get_queryset()
        student_q = (self.request.query_params.get('student') or '').strip()
        year_q = (self.request.query_params.get('year') or '').strip()
        term_q = (self.request.query_params.get('term') or '').strip()
        status_q = (self.request.query_params.get('status') or '').strip()
        q = (self.request.query_params.get('q') or '').strip()
        if student_q.isdigit():
            qs = qs.filter(student_id=int(student_q))
        if year_q.isdigit():
            qs = qs.filter(academic_year=int(year_q))
        if term_q.isdigit():
            qs = qs.filter(term_number=int(term_q))
        if status_q:
            qs = qs.filter(status=status_q)
        if q:
            qs = qs.filter(
                Q(student__student_id__icontains=q)
                | Q(student__first_name__icontains=q)
                | Q(student__last_name__icontains=q)
                | Q(title__icontains=q)
                | Q(notes__icontains=q)
            )
        return qs

    def perform_create(self, serializer):
        student = serializer.validated_data.get('student')
        year_v = serializer.validated_data.get('academic_year')
        term_v = serializer.validated_data.get('term_number')
        invoice = Invoice.objects.filter(student=student, academic_year=year_v, term_number=term_v).first()
        role = get_role(self.request.user)
        obj = serializer.save(
            created_by=self.request.user,
            approved_by=self.request.user if (self.request.user.is_superuser or role in ['superadmin', 'bursar']) else None,
            invoice=invoice,
        )
        _refresh_finance_commitments(student, year_v, term_v)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='INSTALLMENT_PLAN_CREATED',
            ip_address=get_client_ip(self.request),
            details=f'Installment plan id={obj.id} student_id={obj.student_id} T{obj.term_number}/{obj.academic_year}.',
        )

    def perform_update(self, serializer):
        obj = serializer.save(
            invoice=Invoice.objects.filter(
                student=serializer.instance.student,
                academic_year=serializer.instance.academic_year,
                term_number=serializer.instance.term_number,
            ).first()
        )
        _refresh_finance_commitments(obj.student, obj.academic_year, obj.term_number)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='INSTALLMENT_PLAN_UPDATED',
            ip_address=get_client_ip(self.request),
            details=f'Installment plan id={obj.id} updated.',
        )

    @action(detail=True, methods=['post'], url_path='send-reminder')
    def send_reminder(self, request, pk=None):
        plan = self.get_object()
        _refresh_finance_commitments(plan.student, plan.academic_year, plan.term_number)
        next_item = plan.items.exclude(status__in=['paid', 'cancelled']).order_by('due_date', 'id').first()
        if not next_item:
            return Response({'detail': 'No pending installment remains on this plan.'}, status=status.HTTP_400_BAD_REQUEST)
        contacts = _get_parent_contacts(plan.student)
        channel = ((request.data or {}).get('channel') or 'sms').strip().lower()
        if channel not in ['sms', 'email', 'both']:
            channel = 'sms'
        msg = (
            f"Bitende Junior School: installment reminder for {plan.student.first_name} {plan.student.last_name} "
            f"({plan.student.student_id}). {next_item.label or 'Installment'} of UGX {next_item.amount} is due on "
            f"{next_item.due_date}. Plan: {plan.title}."
        )
        email_count = 0
        sms_count = 0
        if channel in ['sms', 'both']:
            for phone in contacts['phones']:
                send_sms(phone, msg)
                _record_fee_reminder_log(
                    student=plan.student,
                    created_by=request.user,
                    channel='sms',
                    status_v='sent',
                    recipient=phone,
                    message=msg,
                    invoice=plan.invoice,
                    plan=plan,
                    installment=next_item,
                    provider='system_sms',
                )
                sms_count += 1
        if channel in ['email', 'both'] and contacts['emails']:
            ok = send_email(
                'Installment Reminder',
                contacts['emails'],
                'school/emails/fee_reminder_email.html',
                {
                    'student': plan.student,
                    'title': plan.title,
                    'amount': next_item.amount,
                    'due_date': next_item.due_date,
                    'term_number': plan.term_number,
                    'academic_year': plan.academic_year,
                    'message_text': msg,
                },
            )
            for email in contacts['emails']:
                _record_fee_reminder_log(
                    student=plan.student,
                    created_by=request.user,
                    channel='email',
                    status_v='sent' if ok else 'failed',
                    recipient=email,
                    message=msg,
                    invoice=plan.invoice,
                    plan=plan,
                    installment=next_item,
                    provider='smtp',
                )
                if ok:
                    email_count += 1
        if not sms_count and not email_count:
            return Response({'detail': 'No parent contacts found for this student.'}, status=status.HTTP_400_BAD_REQUEST)
        next_item.reminder_count = int(next_item.reminder_count or 0) + 1
        next_item.last_reminder_at = timezone.now()
        next_item.save(update_fields=['reminder_count', 'last_reminder_at', 'updated_at'])
        return Response({'detail': 'Reminder sent.', 'sms_count': sms_count, 'email_count': email_count})


class FeePromiseViewSet(viewsets.ModelViewSet):
    queryset = FeePromise.objects.select_related('student', 'installment', 'installment__plan', 'created_by').all().order_by('-created_at')
    serializer_class = FeePromiseSerializer
    permission_classes = [IsFinanceUser]

    def get_queryset(self):
        qs = super().get_queryset()
        student_q = (self.request.query_params.get('student') or '').strip()
        year_q = (self.request.query_params.get('year') or '').strip()
        term_q = (self.request.query_params.get('term') or '').strip()
        status_q = (self.request.query_params.get('status') or '').strip()
        overdue_q = (self.request.query_params.get('overdue') or '').strip().lower()
        if student_q.isdigit():
            qs = qs.filter(student_id=int(student_q))
        if year_q.isdigit():
            qs = qs.filter(academic_year=int(year_q))
        if term_q.isdigit():
            qs = qs.filter(term_number=int(term_q))
        if status_q:
            qs = qs.filter(status=status_q)
        if overdue_q in ['1', 'true', 'yes']:
            qs = qs.filter(status='open', promised_for__lt=timezone.localdate())
        return qs

    def perform_create(self, serializer):
        installment = serializer.validated_data.get('installment')
        extra = {}
        if installment and not serializer.validated_data.get('student'):
            extra['student'] = installment.plan.student
            extra['academic_year'] = installment.plan.academic_year
            extra['term_number'] = installment.plan.term_number
        obj = serializer.save(created_by=self.request.user, **extra)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='FEE_PROMISE_CREATED',
            ip_address=get_client_ip(self.request),
            details=f'Fee promise id={obj.id} student_id={obj.student_id} amount={obj.amount}.',
        )
        try:
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title='Fee promise recorded',
                message=f"{obj.student.student_id} promised UGX {obj.amount} by {obj.promised_for}.",
                link_page='fee_promises',
                link_object_id=obj.id,
                student=obj.student,
                school_class=getattr(obj.student, 'current_class', None),
                meta={'promise_id': obj.id, 'amount': str(obj.amount), 'promised_for': obj.promised_for.isoformat() if obj.promised_for else None},
            )
        except Exception:
            pass

    def perform_update(self, serializer):
        obj = serializer.save()
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='FEE_PROMISE_UPDATED',
            ip_address=get_client_ip(self.request),
            details=f'Fee promise id={obj.id} updated.',
        )
        try:
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title='Fee promise updated',
                message=f"{obj.student.student_id} promise is now {obj.status}.",
                link_page='fee_promises',
                link_object_id=obj.id,
                student=obj.student,
                school_class=getattr(obj.student, 'current_class', None),
                meta={'promise_id': obj.id, 'status': obj.status},
            )
        except Exception:
            pass

    @action(detail=True, methods=['post'], url_path='send-reminder')
    def send_reminder(self, request, pk=None):
        promise = self.get_object()
        contacts = _get_parent_contacts(promise.student)
        msg = (
            f"Bitende Junior School: reminder for fee promise on {promise.student.first_name} {promise.student.last_name} "
            f"({promise.student.student_id}). Promised amount UGX {promise.amount} was due by {promise.promised_for}."
        )
        sms_count = 0
        email_count = 0
        for phone in contacts['phones']:
            send_sms(phone, msg)
            _record_fee_reminder_log(
                student=promise.student,
                created_by=request.user,
                channel='sms',
                status_v='sent',
                recipient=phone,
                message=msg,
                promise=promise,
                provider='system_sms',
            )
            sms_count += 1
        if contacts['emails']:
            ok = send_email(
                'Fee Promise Reminder',
                contacts['emails'],
                'school/emails/fee_reminder_email.html',
                {
                    'student': promise.student,
                    'title': 'Fee promise reminder',
                    'amount': promise.amount,
                    'due_date': promise.promised_for,
                    'term_number': promise.term_number,
                    'academic_year': promise.academic_year,
                    'message_text': msg,
                },
            )
            for email in contacts['emails']:
                _record_fee_reminder_log(
                    student=promise.student,
                    created_by=request.user,
                    channel='email',
                    status_v='sent' if ok else 'failed',
                    recipient=email,
                    message=msg,
                    promise=promise,
                    provider='smtp',
                )
                if ok:
                    email_count += 1
        if not sms_count and not email_count:
            return Response({'detail': 'No parent contacts found for this student.'}, status=status.HTTP_400_BAD_REQUEST)
        promise.reminder_count = int(promise.reminder_count or 0) + 1
        promise.last_reminder_at = timezone.now()
        promise.save(update_fields=['reminder_count', 'last_reminder_at', 'updated_at'])
        return Response({'detail': 'Reminder sent.', 'sms_count': sms_count, 'email_count': email_count})

    @action(detail=True, methods=['post'], url_path='mark-kept')
    def mark_kept(self, request, pk=None):
        promise = self.get_object()
        promise.status = 'kept'
        promise.fulfilled_at = timezone.now()
        promise.save(update_fields=['status', 'fulfilled_at', 'updated_at'])
        try:
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title='Fee promise kept',
                message=f"{promise.student.student_id} fulfilled a fee promise of UGX {promise.amount}.",
                link_page='fee_promises',
                link_object_id=promise.id,
                student=promise.student,
                school_class=getattr(promise.student, 'current_class', None),
                meta={'promise_id': promise.id, 'status': 'kept'},
            )
        except Exception:
            pass
        return Response(FeePromiseSerializer(promise).data)

    @action(detail=True, methods=['post'], url_path='mark-missed')
    def mark_missed(self, request, pk=None):
        promise = self.get_object()
        promise.status = 'missed'
        promise.fulfilled_at = None
        promise.save(update_fields=['status', 'fulfilled_at', 'updated_at'])
        try:
            notify_roles(
                ['bursar', 'superadmin'] + ADMIN_ROLE_LIST,
                category='finance',
                title='Fee promise missed',
                message=f"{promise.student.student_id} missed a promise due on {promise.promised_for}.",
                link_page='fee_promises',
                link_object_id=promise.id,
                student=promise.student,
                school_class=getattr(promise.student, 'current_class', None),
                meta={'promise_id': promise.id, 'status': 'missed', 'promised_for': promise.promised_for.isoformat() if promise.promised_for else None},
            )
        except Exception:
            pass
        return Response(FeePromiseSerializer(promise).data)


class FeeReminderLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FeeReminderLog.objects.select_related('student', 'invoice', 'plan', 'installment', 'promise', 'created_by').all().order_by('-created_at')
    serializer_class = FeeReminderLogSerializer
    permission_classes = [IsFinanceUser]

    def get_queryset(self):
        qs = super().get_queryset()
        student_q = (self.request.query_params.get('student') or '').strip()
        year_q = (self.request.query_params.get('year') or '').strip()
        term_q = (self.request.query_params.get('term') or '').strip()
        channel_q = (self.request.query_params.get('channel') or '').strip()
        status_q = (self.request.query_params.get('status') or '').strip()
        if student_q.isdigit():
            qs = qs.filter(student_id=int(student_q))
        if year_q.isdigit():
            qs = qs.filter(academic_year=int(year_q))
        if term_q.isdigit():
            qs = qs.filter(term_number=int(term_q))
        if channel_q:
            qs = qs.filter(channel=channel_q)
        if status_q:
            qs = qs.filter(status=status_q)
        return qs


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all().order_by('name')
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsFinanceUser]

    def destroy(self, request, *args, **kwargs):
        if not IsSuperUser().has_permission(request, self):
            return Response({'detail': 'Only super admin can delete categories.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.select_related('category', 'created_by', 'approved_by').all().order_by('-expense_date', '-created_at')
    serializer_class = ExpenseSerializer
    permission_classes = [IsFinanceUser]

    def get_queryset(self):
        qs = super().get_queryset()
        status_v = (self.request.query_params.get('status') or '').strip()
        cat = (self.request.query_params.get('category') or '').strip()
        month = (self.request.query_params.get('month') or '').strip()
        year = (self.request.query_params.get('year') or '').strip()
        q = (self.request.query_params.get('q') or '').strip()
        if status_v:
            qs = qs.filter(status=status_v)
        if cat.isdigit():
            qs = qs.filter(category_id=int(cat))
        if month.isdigit() and year.isdigit():
            qs = qs.filter(expense_date__year=int(year), expense_date__month=int(month))
        if q:
            qs = qs.filter(Q(vendor__icontains=q) | Q(description__icontains=q))
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        SecurityAuditLog.objects.create(
            user=self.request.user,
            event_type='EXPENSE_CREATED',
            ip_address=get_client_ip(self.request),
            details=f'Created expense id={obj.id} amount={obj.amount}.',
        )

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        e = self.get_object()
        if e.status != 'pending':
            return Response({'detail': 'Only pending expenses can be approved.'}, status=status.HTTP_400_BAD_REQUEST)
        e.status = 'approved'
        e.approved_by = request.user
        e.approved_at = timezone.now()
        notes = ((request.data or {}).get('review_notes') or '').strip()
        if notes:
            e.review_notes = notes
        e.save(update_fields=['status', 'approved_by', 'approved_at', 'review_notes', 'updated_at'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='EXPENSE_APPROVED',
            ip_address=get_client_ip(request),
            details=f'Approved expense id={e.id}.',
        )
        return Response(ExpenseSerializer(e).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        e = self.get_object()
        if e.status != 'pending':
            return Response({'detail': 'Only pending expenses can be rejected.'}, status=status.HTTP_400_BAD_REQUEST)
        e.status = 'rejected'
        notes = ((request.data or {}).get('review_notes') or '').strip()
        if notes:
            e.review_notes = notes
        e.save(update_fields=['status', 'review_notes', 'updated_at'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='EXPENSE_REJECTED',
            ip_address=get_client_ip(request),
            details=f'Rejected expense id={e.id}.',
        )
        return Response(ExpenseSerializer(e).data)


# ==================== NEW VIEWSETS ====================

class ExamTypeViewSet(viewsets.ModelViewSet):
    queryset = ExamType.objects.all()
    serializer_class = ExamTypeSerializer
    permission_classes = [permissions.IsAuthenticated, CanManageTerms]
    filterset_fields = ['is_active', 'exam_type']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']


class AcademicCalendarEventViewSet(viewsets.ModelViewSet):
    queryset = AcademicCalendarEvent.objects.all()
    serializer_class = AcademicCalendarEventSerializer
    permission_classes = [permissions.IsAuthenticated, CanManageTerms]
    filterset_fields = ['academic_term', 'event_type', 'exam_type']
    search_fields = ['title', 'description']
    ordering_fields = ['event_date', 'created_at']
    ordering = ['event_date']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class TermInstallmentPlanViewSet(viewsets.ModelViewSet):
    queryset = TermInstallmentPlan.objects.all()
    serializer_class = TermInstallmentPlanSerializer
    permission_classes = [permissions.IsAuthenticated, IsFinanceUser]
    filterset_fields = ['academic_term', 'number_of_installments']
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class StudentDebtRecordViewSet(viewsets.ModelViewSet):
    queryset = StudentDebtRecord.objects.all()
    serializer_class = StudentDebtRecordSerializer
    permission_classes = [permissions.IsAuthenticated, IsFinanceUser]
    filterset_fields = ['student', 'academic_term', 'is_settled']
    search_fields = ['student__first_name', 'student__last_name']
    ordering_fields = ['created_at', 'outstanding_amount']
    ordering = ['-created_at']

    @action(detail=True, methods=['post'], url_path='settle')
    def settle_debt(self, request, pk=None):
        debt = self.get_object()
        if debt.is_settled:
            return Response({'detail': 'This debt is already settled.'}, status=status.HTTP_400_BAD_REQUEST)
        
        debt.is_settled = True
        debt.settled_date = timezone.now()
        debt.settled_by = request.user
        debt.outstanding_amount = Decimal('0')
        debt.save()
        
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='STUDENT_DEBT_SETTLED',
            ip_address=get_client_ip(request),
            details=f'Debt settled for student {debt.student} from {debt.academic_term}.'
        )
        return Response(StudentDebtRecordSerializer(debt).data)


class TeacherSalaryViewSet(viewsets.ModelViewSet):
    queryset = TeacherSalary.objects.all()
    serializer_class = TeacherSalarySerializer
    permission_classes = [permissions.IsAuthenticated, IsPayrollUser]
    filterset_fields = ['teacher', 'academic_term', 'payment_status']
    search_fields = ['teacher__user__first_name', 'teacher__user__last_name']
    ordering_fields = ['created_at', 'base_salary', 'payment_status']
    ordering = ['-created_at']

    @action(detail=True, methods=['post'], url_path='approve')
    def approve_salary(self, request, pk=None):
        salary = self.get_object()
        if salary.payment_status != 'pending':
            return Response({'detail': 'Only pending salaries can be approved.'}, status=status.HTTP_400_BAD_REQUEST)
        
        salary.payment_status = 'approved'
        salary.approved_by = request.user
        salary.save()
        
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TEACHER_SALARY_APPROVED',
            ip_address=get_client_ip(request),
            details=f'Salary approved for teacher {salary.teacher}.'
        )
        return Response(TeacherSalarySerializer(salary).data)

    @action(detail=True, methods=['post'], url_path='mark-paid')
    def mark_paid(self, request, pk=None):
        salary = self.get_object()
        if salary.payment_status == 'paid':
            return Response({'detail': 'Salary already marked as paid.'}, status=status.HTTP_400_BAD_REQUEST)
        
        salary.payment_status = 'paid'
        salary.paid_by = request.user
        salary.paid_date = timezone.now()
        salary.amount_paid = salary.base_salary
        salary.save()
        
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='TEACHER_SALARY_PAID',
            ip_address=get_client_ip(request),
            details=f'Salary paid for teacher {salary.teacher}.'
        )
        return Response(TeacherSalarySerializer(salary).data)


class TeacherAllowanceViewSet(viewsets.ModelViewSet):
    queryset = TeacherAllowance.objects.all()
    serializer_class = TeacherAllowanceSerializer
    permission_classes = [permissions.IsAuthenticated, IsPayrollUser]
    filterset_fields = ['teacher', 'academic_term', 'allowance_type', 'is_paid']
    search_fields = ['teacher__user__first_name', 'teacher__user__last_name']
    ordering_fields = ['created_at', 'amount', 'allowance_type']
    ordering = ['-created_at']

    @action(detail=True, methods=['post'], url_path='mark-paid')
    def mark_paid(self, request, pk=None):
        allowance = self.get_object()
        if allowance.is_paid:
            return Response({'detail': 'Allowance already marked as paid.'}, status=status.HTTP_400_BAD_REQUEST)
        
        allowance.is_paid = True
        allowance.paid_date = timezone.now()
        allowance.save()
        
        return Response(TeacherAllowanceSerializer(allowance).data)


class OtherStaffViewSet(viewsets.ModelViewSet):
    queryset = OtherStaff.objects.filter(is_active=True)
    serializer_class = OtherStaffSerializer
    permission_classes = [permissions.IsAuthenticated, IsPayrollUser]
    filterset_fields = ['role', 'is_active']
    search_fields = ['first_name', 'last_name', 'role']
    ordering_fields = ['first_name', 'last_name', 'base_salary', 'start_date']
    ordering = ['first_name', 'last_name']


class StaffPayrollViewSet(viewsets.ModelViewSet):
    queryset = StaffPayroll.objects.all()
    serializer_class = StaffPayrollSerializer
    permission_classes = [permissions.IsAuthenticated, IsPayrollUser]
    filterset_fields = ['academic_term', 'payment_status', 'payment_method']
    search_fields = ['teacher__user__first_name', 'teacher__user__last_name', 'other_staff__first_name', 'other_staff__last_name']
    ordering_fields = ['created_at', 'net_amount', 'payment_status']
    ordering = ['-created_at']

    def _can_manage_payroll(self, user):
        role = get_role(user)
        return bool(user and user.is_authenticated and (user.is_superuser or role in ['superadmin', 'director', 'headteacher', 'bursar']))

    def _notify_payroll_paid(self, payroll):
        teacher = getattr(payroll, 'teacher', None)
        teacher_user = getattr(teacher, 'user', None) if teacher else None
        if teacher_user:
            Notification.objects.create(
                user=teacher_user,
                category='finance',
                title='Salary payment processed',
                message=f'Your payroll for {getattr(payroll.academic_term, "__str__", lambda: "the selected term")()} has been marked as paid.',
                link_page='my_pay',
                link_object_id=payroll.id,
                meta={'payroll_id': payroll.id, 'payment_status': payroll.payment_status},
            )

    def _term_dashboard(self, academic_term):
        payments_qs = Payment.objects.filter(
            academic_year=academic_term.academic_year,
            term_number=academic_term.term_number,
            status__in=['approved', 'received'],
        )
        expenses_qs = Expense.objects.filter(
            status='approved',
            expense_date__range=(academic_term.start_date, academic_term.end_date),
        )
        payroll_qs = StaffPayroll.objects.filter(academic_term=academic_term)
        salary_qs = TeacherSalary.objects.filter(academic_term=academic_term)
        allowance_qs = TeacherAllowance.objects.filter(academic_term=academic_term)
        debt_qs = StudentDebtRecord.objects.filter(is_settled=False)

        collected_total = _to_decimal(payments_qs.aggregate(total=Sum('amount'))['total'])
        approved_expense_total = _to_decimal(expenses_qs.aggregate(total=Sum('amount'))['total'])
        paid_payroll_total = _to_decimal(payroll_qs.filter(payment_status='paid').aggregate(total=Sum('net_amount'))['total'])
        approved_payroll_total = _to_decimal(payroll_qs.filter(payment_status='approved').aggregate(total=Sum('net_amount'))['total'])
        pending_payroll_total = _to_decimal(payroll_qs.filter(payment_status='pending').aggregate(total=Sum('net_amount'))['total'])
        unpaid_teacher_salary_total = _to_decimal(salary_qs.exclude(payment_status='paid').aggregate(total=Sum('base_salary'))['total'])
        unpaid_allowance_total = _to_decimal(allowance_qs.filter(is_paid=False).aggregate(total=Sum('amount'))['total'])
        old_debt_total = _to_decimal(
            debt_qs.exclude(academic_term=academic_term).aggregate(total=Sum('outstanding_amount'))['total']
        )
        current_term_debt_total = _to_decimal(
            debt_qs.filter(academic_term=academic_term).aggregate(total=Sum('outstanding_amount'))['total']
        )

        class_rows = []
        active_students = Student.objects.select_related('current_class').filter(status='active')
        grouped = {}
        for stu in active_students:
            class_id = getattr(stu, 'current_class_id', None)
            if not class_id:
                continue
            class_name = getattr(getattr(stu, 'current_class', None), 'level', None) or 'Unassigned'
            row = grouped.setdefault(class_id, {
                'class_id': class_id,
                'class_name': class_name,
                'students': 0,
                'expected_fees': Decimal('0.00'),
                'collected_fees': Decimal('0.00'),
                'outstanding_fees': Decimal('0.00'),
            })
            row['students'] += 1
            opening = _opening_balance_before_term(stu, academic_term.academic_year, academic_term.term_number)
            adj_now = _adjustments_for_term(stu, academic_term.academic_year, academic_term.term_number)
            term_due = (_base_due_for_term(stu, academic_term.academic_year, academic_term.term_number) + _class_extras_for_term(stu, academic_term.academic_year, academic_term.term_number) + adj_now).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            paid_now = _payments_for_term(stu, academic_term.academic_year, academic_term.term_number)
            credit_bf = opening if opening > 0 else Decimal('0.00')
            arrears_bf = (-opening) if opening < 0 else Decimal('0.00')
            total_to_settle = (term_due + arrears_bf).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            available = (credit_bf + paid_now).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            paid_applied = min(available, total_to_settle)
            balance_due = (total_to_settle - paid_applied).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            row['expected_fees'] += total_to_settle
            row['collected_fees'] += paid_applied
            row['outstanding_fees'] += balance_due

        for row in sorted(grouped.values(), key=lambda item: item['class_name']):
            class_rows.append({
                'class_id': row['class_id'],
                'class_name': row['class_name'],
                'students': row['students'],
                'expected_fees': str(row['expected_fees'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'collected_fees': str(row['collected_fees'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'outstanding_fees': str(row['outstanding_fees'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            })

        expense_rows = list(
            expenses_qs.values('category__name')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')
        )
        expense_breakdown = [
            {
                'category': item.get('category__name') or 'Uncategorised',
                'count': int(item.get('count') or 0),
                'total_amount': str(_to_decimal(item.get('total')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            }
            for item in expense_rows
        ]

        recent_payroll = StaffPayrollSerializer(payroll_qs.select_related('teacher__user', 'other_staff', 'academic_term')[:12], many=True).data
        return {
            'term': {
                'id': academic_term.id,
                'academic_year': academic_term.academic_year,
                'term_number': academic_term.term_number,
                'start_date': academic_term.start_date,
                'end_date': academic_term.end_date,
            },
            'totals': {
                'collected_revenue': str(collected_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'approved_expenses': str(approved_expense_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'paid_payroll': str(paid_payroll_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'approved_payroll': str(approved_payroll_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'pending_payroll': str(pending_payroll_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'unpaid_teacher_salaries': str(unpaid_teacher_salary_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'unpaid_allowances': str(unpaid_allowance_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'current_term_debt': str(current_term_debt_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'old_term_debt': str(old_debt_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'profit_after_expenses': str((collected_total - approved_expense_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'profit_after_paid_payroll': str((collected_total - approved_expense_total - paid_payroll_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            },
            'counts': {
                'pending_salary_records': int(salary_qs.filter(payment_status='pending').count()),
                'approved_salary_records': int(salary_qs.filter(payment_status='approved').count()),
                'pending_payroll_records': int(payroll_qs.filter(payment_status='pending').count()),
                'approved_payroll_records': int(payroll_qs.filter(payment_status='approved').count()),
                'paid_payroll_records': int(payroll_qs.filter(payment_status='paid').count()),
                'other_staff_count': int(OtherStaff.objects.filter(is_active=True).count()),
            },
            'class_breakdown': class_rows,
            'expense_breakdown': expense_breakdown,
            'recent_payroll': recent_payroll,
        }

    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        if not self._can_manage_payroll(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        year_q = (request.query_params.get('year') or '').strip()
        term_q = (request.query_params.get('term') or '').strip()
        if year_q.isdigit() and term_q.isdigit():
            academic_term = AcademicTerm.objects.filter(academic_year=int(year_q), term_number=int(term_q)).first()
        else:
            academic_term = _current_term()
        if not academic_term:
            return Response({'detail': 'No academic term found.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._term_dashboard(academic_term))

    @action(detail=False, methods=['post'], url_path='generate-term')
    def generate_term_payroll(self, request):
        if not self._can_manage_payroll(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        term_id = (request.data or {}).get('academic_term')
        academic_term = AcademicTerm.objects.filter(id=term_id).first() if str(term_id or '').isdigit() else _current_term()
        if not academic_term:
            return Response({'detail': 'Academic term not found.'}, status=status.HTTP_400_BAD_REQUEST)

        created = 0
        updated = 0
        skipped = 0
        with transaction.atomic():
            for salary in TeacherSalary.objects.select_related('teacher__user').filter(academic_term=academic_term).exclude(payment_status='paid'):
                allowance_total = _to_decimal(
                    TeacherAllowance.objects.filter(teacher=salary.teacher, academic_term=academic_term, is_paid=False).aggregate(total=Sum('amount'))['total']
                )
                gross_amount = (_to_decimal(salary.base_salary) + allowance_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                active_qs = StaffPayroll.objects.filter(academic_term=academic_term, teacher=salary.teacher).exclude(payment_status='paid').order_by('-created_at')
                payroll = active_qs.first()
                if payroll is None:
                    StaffPayroll.objects.create(
                        academic_term=academic_term,
                        teacher=salary.teacher,
                        gross_amount=gross_amount,
                        deductions=Decimal('0.00'),
                        net_amount=gross_amount,
                        payment_method='cash',
                        payment_status='pending',
                        notes=f'Generated from salary and unpaid allowances for {academic_term}.',
                    )
                    created += 1
                else:
                    payroll.gross_amount = gross_amount
                    payroll.net_amount = (gross_amount - _to_decimal(payroll.deductions)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    payroll.notes = f'Updated from salary and unpaid allowances for {academic_term}.'
                    payroll.save(update_fields=['gross_amount', 'net_amount', 'notes', 'updated_at'])
                    updated += 1

            for staff in OtherStaff.objects.filter(is_active=True):
                active_qs = StaffPayroll.objects.filter(academic_term=academic_term, other_staff=staff).exclude(payment_status='paid').order_by('-created_at')
                payroll = active_qs.first()
                if payroll is None:
                    amount = _to_decimal(staff.base_salary)
                    StaffPayroll.objects.create(
                        academic_term=academic_term,
                        other_staff=staff,
                        gross_amount=amount,
                        deductions=Decimal('0.00'),
                        net_amount=amount,
                        payment_method='cash',
                        payment_status='pending',
                        notes=f'Generated from staff base salary for {academic_term}.',
                    )
                    created += 1
                else:
                    skipped += 1

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PAYROLL_GENERATED',
            ip_address=get_client_ip(request),
            details=f'Generated payroll for term id={academic_term.id}: created={created}, updated={updated}, skipped={skipped}.',
        )
        return Response({
            'detail': 'Payroll generated successfully.',
            'academic_term': academic_term.id,
            'created': created,
            'updated': updated,
            'skipped': skipped,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='my-summary', permission_classes=[permissions.IsAuthenticated])
    def my_summary(self, request):
        role = get_role(request.user)
        if role != 'teacher':
            return Response({'detail': 'Only teachers can view this summary.'}, status=status.HTTP_403_FORBIDDEN)
        teacher = Teacher.objects.filter(user=request.user).first()
        if not teacher:
            return Response({'detail': 'Teacher profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        salaries = TeacherSalary.objects.filter(teacher=teacher).select_related('academic_term').order_by('-created_at')
        allowances = TeacherAllowance.objects.filter(teacher=teacher).select_related('academic_term').order_by('-created_at')
        payroll = StaffPayroll.objects.filter(teacher=teacher).select_related('academic_term').order_by('-created_at')
        latest_salary = salaries.first()
        latest_payroll = payroll.first()
        return Response({
            'teacher_name': request.user.get_full_name() or request.user.username,
            'latest_salary': TeacherSalarySerializer(latest_salary).data if latest_salary else None,
            'latest_payroll': StaffPayrollSerializer(latest_payroll).data if latest_payroll else None,
            'salary_history': TeacherSalarySerializer(salaries[:12], many=True).data,
            'allowance_history': TeacherAllowanceSerializer(allowances[:12], many=True).data,
            'payroll_history': StaffPayrollSerializer(payroll[:12], many=True).data,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve_payroll(self, request, pk=None):
        if not self._can_manage_payroll(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        payroll = self.get_object()
        if payroll.payment_status != 'pending':
            return Response({'detail': 'Only pending payroll can be approved.'}, status=status.HTTP_400_BAD_REQUEST)
        
        payroll.payment_status = 'approved'
        payroll.approved_by = request.user
        payroll.save(update_fields=['payment_status', 'approved_by', 'updated_at'])
        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PAYROLL_APPROVED',
            ip_address=get_client_ip(request),
            details=f'Payroll approved id={payroll.id}.',
        )
        return Response(StaffPayrollSerializer(payroll).data)

    @action(detail=True, methods=['post'], url_path='mark-paid')
    def mark_paid(self, request, pk=None):
        if not self._can_manage_payroll(request.user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        payroll = self.get_object()
        if payroll.payment_status == 'paid':
            return Response({'detail': 'Payroll already marked as paid.'}, status=status.HTTP_400_BAD_REQUEST)
        
        payroll.payment_status = 'paid'
        payroll.paid_by = request.user
        payroll.paid_date = timezone.now()
        payroll.save(update_fields=['payment_status', 'paid_by', 'paid_date', 'updated_at'])

        if payroll.teacher:
            salary = TeacherSalary.objects.filter(teacher=payroll.teacher, academic_term=payroll.academic_term).exclude(payment_status='paid').order_by('-created_at').first()
            if salary:
                salary.payment_status = 'paid'
                salary.paid_by = request.user
                salary.paid_date = payroll.paid_date
                salary.amount_paid = _to_decimal(salary.base_salary)
                salary.save(update_fields=['payment_status', 'paid_by', 'paid_date', 'amount_paid', 'updated_at'])
            TeacherAllowance.objects.filter(
                teacher=payroll.teacher,
                academic_term=payroll.academic_term,
                is_paid=False,
            ).update(is_paid=True, paid_date=payroll.paid_date)

        SecurityAuditLog.objects.create(
            user=request.user,
            event_type='PAYROLL_PAID',
            ip_address=get_client_ip(request),
            details=f'Payroll paid id={payroll.id}.',
        )
        self._notify_payroll_paid(payroll)
        return Response(StaffPayrollSerializer(payroll).data)
