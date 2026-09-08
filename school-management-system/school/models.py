from decimal import Decimal

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone # Added for OTP expiry
import secrets
import uuid

CONDUCT_GRADE_CHOICES = [
    ('excellent', 'Excellent'),
    ('good', 'Good'),
    ('satisfactory', 'Satisfactory'),
    ('needs_improvement', 'Needs Improvement'),
]

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=[
        ('superadmin', 'Super Admin'),
        ('director', 'Director/Head Director'),
        # Administrators (non-superadmin)
        ('admin', 'Administrator'),
        ('headteacher', 'Headteacher'),
        ('deputy', 'Deputy Headteacher'),
        ('dos', 'Director of Studies (DOS)'),
        ('bursar', 'Bursar'),
        ('reception', 'Reception'),
        ('teacher', 'Teacher'),
        ('parent', 'Parent'),
        ('student', 'Student'),
    ])
    avatar = models.CharField(max_length=2, blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True, unique=True) # Added for login and OTP
    email_address = models.EmailField(blank=True, null=True, unique=True) # Added for login and OTP (can be different from User.email)
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)
    last_login_ua = models.TextField(blank=True, null=True)
    photo_url = models.URLField(blank=True, null=True)
    # When accounts are created with an admin-generated (temporary) password,
    # force the user to change it after first login. We never store plain-text
    # passwords; this is only a boolean reminder/enforcement flag.
    must_change_password = models.BooleanField(default=False)
    # Reserved for future 2FA enforcement (TOTP/email OTP). Kept as a simple flag for now.
    two_factor_enabled = models.BooleanField(default=False)
    # Per-user in-app notification preferences (Settings page).
    # Example: {"in_app": true, "finance": true, "academic": true, "events": true, "security": true}
    notification_prefs = models.JSONField(default=dict, blank=True, null=True)
    # Flexible profile fields (address, bio, etc.) editable in Settings without schema churn.
    profile_data = models.JSONField(default=dict, blank=True, null=True)

ACADEMIC_STATUS_CHOICES = [
    ('active', 'Active'),
    ('promoted', 'Promoted'),
    ('repeating', 'Repeating'),
    ('graduate', 'Graduate'),
    ('transfer_out', 'Transfer Out'),
    ('withdrawn', 'Withdrawn'),
    ('alumnus', 'Alumnus'),
    ('inactive', 'Inactive'), # General inactive status, can be used for transfers/withdrawals
]

PROMOTION_DECISION_CHOICES = [
    ('promote', 'Promote'),
    ('repeat_year', 'Repeat Year'),
    ('graduate', 'Graduate'),
    ('transfer_out', 'Transfer Out'),
    ('withdraw', 'Withdraw'),
]

class SchoolClass(models.Model):
    level = models.CharField(max_length=20)
    sections = models.JSONField(default=list)
    annual_fee = models.DecimalField(max_digits=12, decimal_places=2)
    max_students_per_section = models.IntegerField(default=40)
    teacher_a = models.CharField(max_length=100, blank=True, null=True)
    teacher_b = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"Class {self.level}"


class Subject(models.Model):
    """
    Academic subject master list (e.g. Mathematics, English).
    Administrators attach subjects to classes via ClassSubject.
    """
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=20, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name


class ClassSubject(models.Model):
    """
    Links a Subject to a SchoolClass, with optional scheduling hints.
    """
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name='class_subjects')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='class_links')
    periods_per_week = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = (('school_class', 'subject'),)
        indexes = [
            models.Index(fields=['school_class', 'is_active']),
            models.Index(fields=['subject', 'is_active']),
        ]

    def __str__(self):
        return f"{self.school_class.level}: {self.subject.name}"


class Teacher(models.Model): 
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='teacher_profile', null=True, blank=True) 
    first_name = models.CharField(max_length=100) 
    last_name = models.CharField(max_length=100) 
    phone = models.CharField(max_length=20, unique=True) # Ensure phone is unique 
    # Email is optional in many Ugandan schools; keep unique when provided. 
    email = models.EmailField(blank=True, null=True, unique=True) 
    subjects = models.JSONField(default=list) 
    assigned_class = models.CharField(max_length=100, blank=True, null=True) 
    # Optional "Class Teacher" promotion: gives a teacher extra oversight for a specific class/section. 
    class_teacher_class = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name='class_teacher_assignments') 
    class_teacher_section = models.CharField(max_length=10, blank=True, null=True) 
    is_class_teacher = models.BooleanField(default=False) 
    employment_type = models.CharField(max_length=50, default='Permanent') 
    employee_id = models.CharField(max_length=20, unique=True) 
 
    def __str__(self): 
        return f"{self.first_name} {self.last_name}" 

class Student(models.Model):
    student_id = models.CharField(max_length=20, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    dob = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10)
    district = models.CharField(max_length=100, blank=True, null=True)
    religion = models.CharField(max_length=50, blank=True, null=True)
    current_class = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True)
    section = models.CharField(max_length=10)
    enrollment_date = models.DateField(auto_now_add=True)
    previous_school = models.CharField(max_length=200, blank=True, null=True)
    parent_name = models.CharField(max_length=100)
    parent_relationship = models.CharField(max_length=50)
    parent_phone = models.CharField(max_length=20)
    parent_phone2 = models.CharField(max_length=20, blank=True, null=True)
    home_address = models.TextField(blank=True, null=True)
    allergies = models.TextField(blank=True, null=True)
    medical_conditions = models.TextField(blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True, null=True)
    transport_route = models.CharField(max_length=100, blank=True, null=True)
    photo = models.ImageField(upload_to='student_photos/', blank=True, null=True)
    status = models.CharField(max_length=20, default='active', choices=ACADEMIC_STATUS_CHOICES) # Repurposing the existing status field
    promotion_notes = models.TextField(blank=True, null=True)
    previous_class = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name='students_from_previous_class')
    previous_section = models.CharField(max_length=10, blank=True, null=True)
    promotion_year = models.IntegerField(null=True, blank=True)
    promotion_term = models.IntegerField(null=True, blank=True)
    conduct_grade = models.CharField(max_length=20, choices=CONDUCT_GRADE_CHOICES, default='good') # Added for report cards
    head_teacher_remarks = models.TextField(blank=True, null=True) # Added for report cards

    def __str__(self):
        status_label = getattr(self, 'get_status_display', lambda: '')()
        return f"{self.first_name} {self.last_name} ({self.student_id}) ({status_label})"

class FeeStructure(models.Model):
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE)
    term = models.IntegerField()
    year = models.IntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)


PAYMENT_METHOD_CHOICES = [
    ('cash', 'Cash (Manual)'),
    ('mtn_momo', 'MTN Mobile Money'),
    ('airtel_money', 'Airtel Money'),
    ('bank', 'Bank'),
    ('other', 'Other'),
]

PAYMENT_STATUS_CHOICES = [
    ('pending', 'Pending Approval'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('received', 'Received'),  # legacy synonym for approved (kept for backward compatibility)
    ('reversed', 'Reversed'),
]


class Payment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cash')
    reference = models.CharField(max_length=80, blank=True, null=True)
    gateway_reference = models.CharField(max_length=120, blank=True, null=True, unique=True, db_index=True)
    provider_name = models.CharField(max_length=40, blank=True, null=True)
    provider_status = models.CharField(max_length=40, blank=True, null=True)
    provider_payload = models.JSONField(default=dict, blank=True, null=True)
    # For bank/mobile-money slips submitted by parents/students in the portal.
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_payments')
    received_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_payments')
    received_at = models.DateTimeField(default=timezone.now)
    # Nullable for legacy rows; new rows get defaults automatically.
    created_at = models.DateTimeField(blank=True, null=True, default=timezone.now)
    updated_at = models.DateTimeField(blank=True, null=True, auto_now=True)
    academic_year = models.IntegerField(null=True, blank=True)
    term_number = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='received')
    receipt_image_url = models.URLField(blank=True, null=True)
    # Human-friendly receipt number (generated on approval/receipt).
    receipt_number = models.CharField(max_length=32, blank=True, null=True, unique=True, db_index=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_payments')
    approved_at = models.DateTimeField(blank=True, null=True)
    review_notes = models.TextField(blank=True, null=True)
    # Optional deposit batching (bank reconciliation helper).
    deposit_batch = models.ForeignKey('DepositBatch', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')

    class Meta:
        indexes = [
            models.Index(fields=['received_at']),
            models.Index(fields=['method']),
            models.Index(fields=['status']),
            models.Index(fields=['academic_year', 'term_number']),
        ]

    def __str__(self):
        return f"{self.student.student_id} - {self.amount} ({self.method})"


ADJUSTMENT_KIND_CHOICES = [
    ('discount', 'Discount'),
    ('waiver', 'Waiver'),
    ('penalty', 'Late Penalty'),
    ('correction', 'Correction'),
]


class InvoiceAdjustment(models.Model):
    """
    Manual finance adjustments that affect the term ledger.

    Amount is signed:
    - negative values reduce amount due (discounts/waivers)
    - positive values increase amount due (penalties/corrections)
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='invoice_adjustments')
    academic_year = models.IntegerField()
    term_number = models.IntegerField(choices=[(1, 'Term 1'), (2, 'Term 2'), (3, 'Term 3')])
    kind = models.CharField(max_length=20, choices=ADJUSTMENT_KIND_CHOICES)
    title = models.CharField(max_length=160, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_adjustments')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['academic_year', 'term_number']),
            models.Index(fields=['student', 'academic_year', 'term_number']),
            models.Index(fields=['kind']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"Adj {self.student.student_id} T{self.term_number}/{self.academic_year} {self.kind} {self.amount}"


class StudentGuardianLink(models.Model):
    """
    Explicit linking for 'one parent with multiple children' across different classes/phones.

    This complements the legacy phone-number matching.
    """
    parent_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='guardian_links')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='guardian_links')
    relationship = models.CharField(max_length=30, default='parent')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_guardian_links')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('parent_user', 'student'),)
        indexes = [
            models.Index(fields=['parent_user', 'is_active']),
            models.Index(fields=['student', 'is_active']),
        ]

    def __str__(self):
        return f"{self.parent_user.username} -> {self.student.student_id} ({self.relationship})"


INVOICE_STATUS_CHOICES = [
    ('unpaid', 'Unpaid'),
    ('partial', 'Partial'),
    ('paid', 'Paid'),
]


class Invoice(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='invoices')
    academic_year = models.IntegerField()
    term_number = models.IntegerField(choices=[(1, 'Term 1'), (2, 'Term 2'), (3, 'Term 3')])
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default='unpaid')
    # Results/reports hold (e.g. end-of-term fees not cleared).
    # This is enforced for parent/student access to report cards and marks.
    results_blocked = models.BooleanField(default=False)
    results_block_reason = models.CharField(max_length=200, blank=True, null=True)
    results_blocked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='results_blocks_set')
    results_blocked_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('student', 'academic_year', 'term_number'),)
        indexes = [
            models.Index(fields=['academic_year', 'term_number']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Invoice {self.student.student_id} T{self.term_number}/{self.academic_year}"

class ClassCharge(models.Model):
    """
    Additional class-level charges outside base school fees (e.g. tours, requirements).
    These are shown to parents/students only for their class and can be included in fee breakdown.
    """
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name='charges')
    # Optional: some schools have sections; keep blank for "all sections".
    section = models.CharField(max_length=10, blank=True, null=True)

    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    image_url = models.URLField(blank=True, null=True)

    # Optional scoping: if null, applies to any year/term (useful for one-off requirements).
    academic_year = models.IntegerField(blank=True, null=True)
    term_number = models.IntegerField(blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)

    is_published = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['school_class', 'is_active', 'is_published']),
            models.Index(fields=['academic_year', 'term_number']),
        ]

    def __str__(self):
        sec = (self.section or '').strip()
        scope = f"{self.school_class.level}{sec}" if sec else self.school_class.level
        return f"{scope}: {self.title}"


class Event(models.Model):
    """
    Simple school event / announcement entry for dashboards.
    """
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, null=True)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    audience_roles = models.JSONField(default=list, blank=True, null=True)  # e.g. ["parent","teacher"]
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class SystemSetting(models.Model):
    """
    Simple key/value settings store (DB-backed).
    Used for feature flags and operational toggles controlled by Super Admin.
    """
    key = models.CharField(max_length=80, unique=True)
    value = models.JSONField(default=dict, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


NOTIFICATION_CATEGORY_CHOICES = [
    ('finance', 'Finance'),
    ('academic', 'Academic'),
    ('events', 'Events'),
    ('security', 'Security'),
    ('system', 'System'),
]


class Notification(models.Model):
    """
    In-app notification (per-user).
    We create one row per recipient user (small/medium schools).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    category = models.CharField(max_length=30, choices=NOTIFICATION_CATEGORY_CHOICES, default='system')
    title = models.CharField(max_length=180)
    message = models.TextField(blank=True, null=True)
    student = models.ForeignKey('Student', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    school_class = models.ForeignKey('SchoolClass', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    link_page = models.CharField(max_length=60, blank=True, null=True)  # SPA page key
    link_object_id = models.IntegerField(blank=True, null=True)
    event_key = models.CharField(max_length=120, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    meta = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'is_read', 'created_at']),
            models.Index(fields=['category']),
            models.Index(fields=['student', 'created_at']),
            models.Index(fields=['school_class', 'created_at']),
            models.Index(fields=['event_key', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.title}"


class Announcement(models.Model):
    """
    Broadcast-style notices for dashboards (distinct from dated Events).
    """
    title = models.CharField(max_length=180)
    body = models.TextField()
    image_url = models.URLField(blank=True, null=True)
    audience_roles = models.JSONField(default=list, blank=True, null=True)  # [] => all
    is_published = models.BooleanField(default=True)
    is_pinned = models.BooleanField(default=False)
    # Optional lifecycle controls.
    expires_at = models.DateTimeField(blank=True, null=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['is_published', 'is_pinned', 'created_at']),
        ]

    def __str__(self):
        return self.title

class Mark(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    subject = models.CharField(max_length=100)
    score = models.IntegerField()
    term = models.IntegerField()
    year = models.IntegerField()
    exam_type = models.ForeignKey('ExamType', on_delete=models.SET_NULL, null=True, blank=True, related_name='marks')
    teacher = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True)
    remarks = models.TextField(blank=True, null=True)

class Attendance(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    date = models.DateField()
    status = models.CharField(max_length=10) # Present, Absent, Late
    marked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    academic_year = models.IntegerField(blank=True, null=True)
    term_number = models.IntegerField(blank=True, null=True)
    is_archived = models.BooleanField(default=False)


TEACHER_ATTENDANCE_STATUS_CHOICES = [
    ('present', 'Present'),
    ('absent', 'Absent'),
    ('late', 'Late'),
    ('excused', 'Excused'),
]

TEACHER_ATTENDANCE_METHOD_CHOICES = [
    ('manual', 'Manual'),
    ('qr', 'QR Scan'),
]


class TeacherAttendance(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='attendance')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=TEACHER_ATTENDANCE_STATUS_CHOICES, default='present')
    method = models.CharField(max_length=20, choices=TEACHER_ATTENDANCE_METHOD_CHOICES, default='manual')
    marked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='marked_teacher_attendance')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('teacher', 'date'),)
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.teacher} {self.date} ({self.status})"


class TeacherAttendanceQRToken(models.Model):
    """
    QR token displayed by Reception/Admin for a given date.
    Teachers scan while authenticated; scan marks THEIR attendance only.
    """
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date = models.DateField(default=timezone.localdate)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"Teacher QR {self.date} ({self.token})"

class Timetable(models.Model):
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE)
    # Some schools do not use sections (A/B). Use empty string in that case.
    section = models.CharField(max_length=10, blank=True, default='')
    academic_year = models.IntegerField(blank=True, null=True)
    term_number = models.IntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    slots = models.JSONField(default=dict)
    cells = models.JSONField(default=dict)

    class Meta:
        unique_together = (('school_class', 'section', 'academic_year', 'term_number'),)
        indexes = [
            models.Index(fields=['school_class', 'section']),
            models.Index(fields=['academic_year', 'term_number', 'is_active']),
        ]


EXAM_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('submitted', 'Submitted To Reception'),
    ('printed', 'Printed'),
]


class ExamPaper(models.Model):
    """
    Teacher-uploaded exam/test paper file that Reception can print.
    """
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    school_class = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, blank=True)
    section = models.CharField(max_length=10, blank=True, default='')
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, blank=True, related_name='exam_papers')
    file_url = models.URLField()
    status = models.CharField(max_length=20, choices=EXAM_STATUS_CHOICES, default='draft')
    submitted_at = models.DateTimeField(blank=True, null=True)
    printed_at = models.DateTimeField(blank=True, null=True)
    printed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='printed_exam_papers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['school_class', 'section']),
        ]

    def __str__(self):
        return self.title

class AcademicTerm(models.Model):
    academic_year = models.IntegerField()
    term_number = models.IntegerField(choices=[(1, 'Term 1'), (2, 'Term 2'), (3, 'Term 3')])
    start_date = models.DateField()
    end_date = models.DateField()
    assessment_config = models.JSONField(default=dict, blank=True)
    holiday_break_days = models.IntegerField(default=0)
    auto_generate_invoices_on_start = models.BooleanField(default=False)
    sms_parents_on_start = models.BooleanField(default=False)
    open_mark_entry_on_start = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    # Marks locking (DOS/Superadmin) to prevent late edits.
    marks_locked = models.BooleanField(default=False)
    marks_locked_at = models.DateTimeField(blank=True, null=True)
    marks_locked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='marks_locked_terms')
    marks_lock_reason = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f"Year {self.academic_year} - Term {self.term_number}"


class DepositBatch(models.Model):
    """
    Bank deposit batching for approved bank payments (helps reconciliation).
    """
    name = models.CharField(max_length=120, blank=True, null=True)  # e.g. "Banking 2026-03-15"
    bank_name = models.CharField(max_length=120, blank=True, null=True)
    deposit_date = models.DateField(default=timezone.localdate)
    reference = models.CharField(max_length=80, blank=True, null=True)  # bank deposit ref
    slip_image_url = models.URLField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    is_posted = models.BooleanField(default=False)  # posted to bank
    posted_at = models.DateTimeField(blank=True, null=True)
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='posted_deposit_batches')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_deposit_batches')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['deposit_date']),
            models.Index(fields=['is_posted', 'deposit_date']),
        ]

    def __str__(self):
        return self.name or f"Deposit {getattr(self, 'pk', '')} ({self.deposit_date})"


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


EXPENSE_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]


class Expense(models.Model):
    """
    Minimal expense tracking.
    """
    category = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True)
    expense_date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    vendor = models.CharField(max_length=160, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    receipt_image_url = models.URLField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=EXPENSE_STATUS_CHOICES, default='pending')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_expenses')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_expenses')
    approved_at = models.DateTimeField(blank=True, null=True)
    review_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['expense_date']),
            models.Index(fields=['status', 'expense_date']),
            models.Index(fields=['category', 'expense_date']),
        ]

    def __str__(self):
        return f"Expense {self.amount} ({self.expense_date})"


CASHBOOK_CLOSE_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('closed', 'Closed'),
]


class CashbookClose(models.Model):
    """
    Close-of-day bursar cashbook snapshot.

    Snapshot stores the live reconciliation breakdown at the moment the close is created
    so printing/auditing stays stable even if payments are edited later.
    """
    close_date = models.DateField(default=timezone.localdate)
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='cashbook_closes')
    status = models.CharField(max_length=20, choices=CASHBOOK_CLOSE_STATUS_CHOICES, default='closed')
    opening_cash = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    cash_received_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    non_cash_received_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    approved_expense_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    expected_cash_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    counted_cash_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    variance_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    deposit_batch_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    payment_count = models.IntegerField(default=0)
    expense_count = models.IntegerField(default=0)
    notes = models.TextField(blank=True, null=True)
    snapshot = models.JSONField(default=dict, blank=True, null=True)
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='closed_cashbooks')
    closed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['close_date', 'status']),
            models.Index(fields=['cashier', 'close_date']),
        ]

    def __str__(self):
        cashier_id = getattr(self, 'cashier_id', None)
        cashier_username = getattr(getattr(self, 'cashier', None), 'username', '')
        if cashier_id:
            return f"Cashbook {self.close_date} - {cashier_username}"
        return f"Cashbook {self.close_date}"


INSTALLMENT_PLAN_STATUS_CHOICES = [
    ('active', 'Active'),
    ('completed', 'Completed'),
    ('defaulted', 'Defaulted'),
    ('cancelled', 'Cancelled'),
]


class InstallmentPlan(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='installment_plans')
    invoice = models.ForeignKey('Invoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='installment_plans')
    academic_year = models.IntegerField()
    term_number = models.IntegerField(choices=[(1, 'Term 1'), (2, 'Term 2'), (3, 'Term 3')])
    title = models.CharField(max_length=160, default='Fee installment plan')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    start_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, choices=INSTALLMENT_PLAN_STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_installment_plans')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_installment_plans')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['student', 'academic_year', 'term_number']),
            models.Index(fields=['status', 'start_date']),
        ]

    def __str__(self):
        return f"Plan {self.student.student_id} T{self.term_number}/{self.academic_year}"


INSTALLMENT_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('partial', 'Partial'),
    ('paid', 'Paid'),
    ('overdue', 'Overdue'),
    ('cancelled', 'Cancelled'),
]


class InstallmentPlanItem(models.Model):
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.CASCADE, related_name='items')
    label = models.CharField(max_length=120, blank=True, null=True)
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField(max_length=20, choices=INSTALLMENT_STATUS_CHOICES, default='pending')
    reminder_count = models.IntegerField(default=0)
    last_reminder_at = models.DateTimeField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['plan', 'due_date']),
            models.Index(fields=['status', 'due_date']),
        ]

    def __str__(self):
        return f"{self.plan} - {self.label or self.due_date}"


FEE_PROMISE_STATUS_CHOICES = [
    ('open', 'Open'),
    ('kept', 'Kept'),
    ('missed', 'Missed'),
    ('cancelled', 'Cancelled'),
]


class FeePromise(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='fee_promises')
    installment = models.ForeignKey(InstallmentPlanItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='fee_promises')
    academic_year = models.IntegerField()
    term_number = models.IntegerField(choices=[(1, 'Term 1'), (2, 'Term 2'), (3, 'Term 3')])
    promise_date = models.DateField(default=timezone.localdate)
    promised_for = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField(max_length=20, choices=FEE_PROMISE_STATUS_CHOICES, default='open')
    reminder_count = models.IntegerField(default=0)
    last_reminder_at = models.DateTimeField(blank=True, null=True)
    fulfilled_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_fee_promises')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['student', 'academic_year', 'term_number']),
            models.Index(fields=['status', 'promised_for']),
        ]

    def __str__(self):
        return f"Promise {self.student.student_id} UGX {self.amount} by {self.promised_for}"


REMINDER_CHANNEL_CHOICES = [
    ('sms', 'SMS'),
    ('email', 'Email'),
    ('in_app', 'In App'),
    ('manual', 'Manual'),
]


REMINDER_STATUS_CHOICES = [
    ('sent', 'Sent'),
    ('failed', 'Failed'),
    ('skipped', 'Skipped'),
]


class FeeReminderLog(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='fee_reminders')
    invoice = models.ForeignKey('Invoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='fee_reminders')
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name='reminders')
    installment = models.ForeignKey(InstallmentPlanItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='reminders')
    promise = models.ForeignKey(FeePromise, on_delete=models.SET_NULL, null=True, blank=True, related_name='reminders')
    academic_year = models.IntegerField(null=True, blank=True)
    term_number = models.IntegerField(null=True, blank=True)
    channel = models.CharField(max_length=20, choices=REMINDER_CHANNEL_CHOICES, default='sms')
    status = models.CharField(max_length=20, choices=REMINDER_STATUS_CHOICES, default='sent')
    recipient = models.CharField(max_length=160, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    provider = models.CharField(max_length=50, blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_fee_reminders')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['student', 'created_at']),
            models.Index(fields=['academic_year', 'term_number']),
            models.Index(fields=['channel', 'status']),
        ]

    def __str__(self):
        return f"Reminder {self.student.student_id} via {self.channel} on {self.created_at:%Y-%m-%d}"


RESULTS_HOLD_ACTION_CHOICES = [
    ('held', 'Held'),
    ('released', 'Released'),
]


class ResultsHoldLog(models.Model):
    invoice = models.ForeignKey('Invoice', on_delete=models.CASCADE, related_name='hold_logs')
    action = models.CharField(max_length=20, choices=RESULTS_HOLD_ACTION_CHOICES)
    reason = models.CharField(max_length=200, blank=True, null=True)
    source = models.CharField(max_length=30, blank=True, null=True)
    acted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='results_hold_actions')
    acted_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['invoice', 'acted_at']),
            models.Index(fields=['action', 'acted_at']),
        ]

    def __str__(self):
        return f"{self.invoice} {self.action} at {self.acted_at:%Y-%m-%d %H:%M}"

class PromotionAudit(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    admin_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    decision_date = models.DateTimeField(auto_now_add=True)
    decision = models.CharField(max_length=20, choices=PROMOTION_DECISION_CHOICES)
    old_class = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, related_name='promotions_from_class')
    new_class = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name='promotions_to_class')
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.student.first_name} {self.student.last_name} - {self.decision} ({self.decision_date.strftime('%Y-%m-%d')})"

class AlumniRegister(models.Model):
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name='alumni_profile')
    graduation_year = models.IntegerField()
    certificate_pdf = models.FileField(upload_to='graduation_certificates/', blank=True, null=True)

    def __str__(self):
        return f"{self.student.first_name} {self.student.last_name} (Alumnus {self.graduation_year})"

class OTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=50, choices=[
        ('password_reset', 'Password Reset'),
        ('login_2fa', 'Login 2FA'),
        ('new_device_login', 'New Device Login'),
        ('teacher_credential', 'Teacher Credential'),
        ('parent_credential', 'Parent Credential'),
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def is_valid(self):
        return not self.is_used and self.expires_at > timezone.now()
    
    def __str__(self):
        return f"OTP for {self.user.username} - {self.purpose}"

class IDCounter(models.Model):
    entity_type = models.CharField(max_length=50, unique=True)
    current_count = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.entity_type} Counter: {self.current_count}"

class GradingScale(models.Model):
    """
    Enhanced grading scale with template support and better organization.
    Supports multiple grading systems (5-grade, 13-grade, 7-point, custom).
    """
    TEMPLATE_CHOICES = [
        ('5grade', '5-Grade System (A, B, C, D, F)'),
        ('13grade', '13-Grade System (A+, A, A-, B+, ...)'),
        ('7point', '7-Point Scale'),
        ('custom', 'Custom'),
    ]
    
    name = models.CharField(max_length=100, unique=True)
    template_type = models.CharField(max_length=20, choices=TEMPLATE_CHOICES, default='custom')
    description = models.TextField(blank=True, null=True, help_text='Description of this grading scale')
    scale_data = models.JSONField(
        default=list,
        help_text='[{"grade": "A+", "min_score": 90, "max_score": 100, "gpa_points": 4.0, "status": "Pass", "implication": "Promote / Graduate"}]'
    )
    is_default = models.BooleanField(default=False)
    is_template = models.BooleanField(default=False, help_text='Mark as True if this is a template for reuse')
    school_class = models.OneToOneField(SchoolClass, on_delete=models.CASCADE, null=True, blank=True, related_name='custom_grading_scale')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_grading_scales')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', 'name']
        indexes = [
            models.Index(fields=['is_default']),
            models.Index(fields=['template_type']),
        ]

    def __str__(self):
        return self.name

class UserSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40, unique=True)
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Session for {self.user.username} at {self.ip_address}"

class SecurityAuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=100)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.event_type} by {self.user.username if self.user else 'N/A'} on {self.timestamp.strftime('%Y-%m-%d %H:%M')}"

class APICredential(models.Model):
    SERVICE_CHOICES = [
        ('google_oauth', 'Google OAuth'),
        ('mtn_momo', 'MTN Mobile Money'),
        ('airtel_money', 'Airtel Mobile Money'),
        ('twilio_sms', 'Twilio SMS'), # Assuming Twilio might also be configured
        ('email_smtp', 'Email SMTP'), # For dynamic SMTP settings
        ('gmail_smtp', 'Gmail SMTP (App Password)'), # No Google Console required for SMTP
        ('megasms', 'MegaSMS Uganda (SMS Gateway)'),
        ('zapier_webhook', 'Zapier Webhook (Automation)'),
        ('openai', 'OpenAI (AI Key)'),
        ('gemini', 'Google Gemini (AI Key)'),
        # Add other services as needed
    ]
    service_name = models.CharField(max_length=50, choices=SERVICE_CHOICES, unique=True)
    client_id = models.CharField(max_length=255, blank=True, null=True)
    client_secret = models.CharField(max_length=255, blank=True, null=True)
    api_key = models.CharField(max_length=255, blank=True, null=True)
    extra_data = models.JSONField(default=dict, blank=True, null=True) # For any other service-specific details
    is_active = models.BooleanField(default=True)
    # Verification metadata (best-effort, may be offline depending on server internet access).
    last_verified_at = models.DateTimeField(blank=True, null=True)
    last_verify_ok = models.BooleanField(blank=True, null=True)  # null = never verified
    last_verify_detail = models.TextField(blank=True, null=True)
    last_verify_extra = models.JSONField(default=dict, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        service_label = getattr(self, 'get_service_name_display', lambda: '')()
        return service_label + (" (Active)" if self.is_active else " (Inactive)")


class APICredentialHealthLog(models.Model):
    """
    Historical verification trail for provider credentials.
    Keeps failure reasons over time so ops can review when a provider broke and why.
    """
    credential = models.ForeignKey(APICredential, on_delete=models.SET_NULL, null=True, blank=True, related_name='health_logs')
    service_name = models.CharField(max_length=50, choices=APICredential.SERVICE_CHOICES)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='credential_health_checks')
    is_ok = models.BooleanField(default=False)
    detail = models.TextField(blank=True, null=True)
    extra = models.JSONField(default=dict, blank=True, null=True)
    verified_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['service_name', 'verified_at']),
            models.Index(fields=['credential', 'verified_at']),
            models.Index(fields=['is_ok', 'verified_at']),
        ]
        ordering = ['-verified_at', '-id']

    def __str__(self):
        state = 'OK' if self.is_ok else 'FAIL'
        return f"{self.service_name} {state} @ {self.verified_at:%Y-%m-%d %H:%M}"


DOCUMENT_KIND_CHOICES = [
    ('test', 'Test'),
    ('exam', 'Exam'),
    ('notes', 'Notes'),
    ('letter', 'Letter'),
    ('notice', 'Notice'),
    ('message', 'Message'),
]

DOCUMENT_STATUS_CHOICES = [ 
    ('draft', 'Draft'), 
    ('submitted', 'Submitted for printing'), 
    ('printed', 'Printed'), 
    ('rejected', 'Rejected'), 
] 

TEMPLATE_WORKFLOW_CHOICES = [
    ('draft', 'Draft'),
    ('approved', 'Approved'),
    ('published', 'Published'),
    ('archived', 'Archived'),
]

TEMPLATE_LIBRARY_SCOPE_CHOICES = [
    ('all', 'All Staff'),
    ('teacher', 'Teacher Library'),
    ('admin', 'Admin Library'),
    ('bursar', 'Bursar Library'),
    ('reception', 'Reception Library'),
]

DOCUMENT_HEADER_PRESET_CHOICES = [
    ('standard', 'Standard School Header'),
    ('finance', 'Finance Header'),
    ('academic', 'Academic Header'),
    ('minimal', 'Minimal Header'),
]

DOCUMENT_FOOTER_PRESET_CHOICES = [
    ('standard', 'Standard Footer'),
    ('finance', 'Finance Footer'),
    ('academic', 'Academic Footer'),
    ('minimal', 'Minimal Footer'),
]


PRINT_QUEUE_KIND_CHOICES = [
    ('admission_letter', 'Admission Letter'),
    ('student_credentials', 'Student Credentials'),
    ('parent_credentials', 'Parent Credentials'),
    ('mail_merge_letter', 'Mail Merge Letter'),
    ('teacher_credentials', 'Teacher Credentials'),
    ('staff_credentials', 'Staff Credentials'),
    ('report_card', 'Report Card'),
]

PRINT_QUEUE_STATUS_CHOICES = [
    ('queued', 'Queued'),
    ('printed', 'Printed'),
    ('cancelled', 'Cancelled'),
    ('expired', 'Expired'),
]


class DocumentDraft(models.Model): 
    """
    Teacher-created drafts (AI-assisted or manual) that can be submitted to Reception for printing.
    """
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='document_drafts')
    kind = models.CharField(max_length=20, choices=DOCUMENT_KIND_CHOICES, default='test')
    title = models.CharField(max_length=160)
    body = models.TextField()
    school_class = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, blank=True)
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True)
    template_key = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    version_number = models.PositiveIntegerField(default=1)
    previous_version = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='next_versions')
    workflow_status = models.CharField(max_length=20, choices=TEMPLATE_WORKFLOW_CHOICES, default='draft')
    workflow_notes = models.TextField(blank=True, null=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_document_templates')
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='published_document_templates')
    library_scope = models.CharField(max_length=20, choices=TEMPLATE_LIBRARY_SCOPE_CHOICES, default='all')
    header_preset = models.CharField(max_length=20, choices=DOCUMENT_HEADER_PRESET_CHOICES, default='standard')
    footer_preset = models.CharField(max_length=20, choices=DOCUMENT_FOOTER_PRESET_CHOICES, default='standard')
    include_signature_block = models.BooleanField(default=False)
    include_school_stamp = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='draft')
    submitted_at = models.DateTimeField(null=True, blank=True)
    printed_at = models.DateTimeField(null=True, blank=True)
    printed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='printed_documents')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['created_by', 'created_at']),
            models.Index(fields=['template_key', 'version_number']),
            models.Index(fields=['workflow_status', 'library_scope']),
        ]

    def __str__(self): 
        return f"{self.title} v{self.version_number} ({self.kind})"


COMMUNICATION_CHANNEL_CHOICES = [
    ('email', 'Email'),
    ('sms', 'SMS'),
]

CAMPAIGN_STATUS_CHOICES = [
    ('scheduled', 'Scheduled'),
    ('running', 'Running'),
    ('completed', 'Completed'),
    ('partially_failed', 'Partially Failed'),
    ('cancelled', 'Cancelled'),
]

DELIVERY_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('sent', 'Sent'),
    ('retry_pending', 'Retry Pending'),
    ('failed', 'Failed'),
    ('skipped', 'Skipped'),
    ('opened', 'Opened'),
    ('confirmed', 'Confirmed'),
    ('replied', 'Replied'),
]


def _default_ack_token():
    return secrets.token_urlsafe(18)


class CommunicationCampaign(models.Model):
    document = models.ForeignKey(DocumentDraft, on_delete=models.CASCADE, related_name='campaigns')
    channel = models.CharField(max_length=10, choices=COMMUNICATION_CHANNEL_CHOICES, default='email')
    audience = models.CharField(max_length=20, default='guardians')
    school_class = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, blank=True)
    student = models.ForeignKey('Student', on_delete=models.SET_NULL, null=True, blank=True)
    scheduled_for = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=20, choices=CAMPAIGN_STATUS_CHOICES, default='scheduled', db_index=True)
    retry_limit = models.PositiveIntegerField(default=2)
    retry_delay_minutes = models.PositiveIntegerField(default=30)
    notes = models.TextField(blank=True, null=True)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_campaigns')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'scheduled_for']),
            models.Index(fields=['created_by', 'created_at']),
        ]
        ordering = ['-scheduled_for', '-id']

    def __str__(self):
        return f"{self.document.title} [{self.channel}] @ {self.scheduled_for:%Y-%m-%d %H:%M}"


class CommunicationDelivery(models.Model):
    campaign = models.ForeignKey(CommunicationCampaign, on_delete=models.CASCADE, related_name='deliveries')
    student = models.ForeignKey('Student', on_delete=models.SET_NULL, null=True, blank=True)
    recipient_name = models.CharField(max_length=150, blank=True, null=True)
    recipient_email = models.EmailField(blank=True, null=True)
    recipient_phone = models.CharField(max_length=30, blank=True, null=True)
    channel = models.CharField(max_length=10, choices=COMMUNICATION_CHANNEL_CHOICES, default='email')
    message_subject = models.CharField(max_length=200, blank=True, null=True)
    message_body = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=DELIVERY_STATUS_CHOICES, default='pending', db_index=True)
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, null=True)
    provider_message_id = models.CharField(max_length=120, blank=True, null=True)
    ack_token = models.CharField(max_length=80, unique=True, default=_default_ack_token, db_index=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['campaign', 'status']),
            models.Index(fields=['next_attempt_at', 'status']),
        ]
        ordering = ['-id']

    def __str__(self):
        ref = self.pk if self.pk is not None else 'new'
        return f"Delivery #{ref} {self.channel} {self.status}"


class PrintQueueItem(models.Model):
    """
    Persistent print queue for Reception.
    Some items are sensitive (contain temporary passwords). For those, we keep payload
    only briefly and wipe it after printing or expiry.
    """

    kind = models.CharField(max_length=40, choices=PRINT_QUEUE_KIND_CHOICES)
    status = models.CharField(max_length=20, choices=PRINT_QUEUE_STATUS_CHOICES, default='queued')

    title = models.CharField(max_length=200)
    note = models.TextField(blank=True, null=True)

    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, blank=True)

    payload = models.JSONField(default=dict, blank=True, null=True)
    is_sensitive = models.BooleanField(default=False)
    expires_at = models.DateTimeField(blank=True, null=True)
    wiped_at = models.DateTimeField(blank=True, null=True)

    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='printqueue_requested')
    printed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='printqueue_printed')
    printed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['kind', 'status']),
            models.Index(fields=['expires_at']),
        ]

    def is_expired(self):
        return bool(self.expires_at) and self.expires_at <= timezone.now()

    def __str__(self):
        return f"{self.kind}: {self.title} ({self.status})"


# ==================== NEW MODELS FOR ENHANCED SYSTEM ====================

class ExamType(models.Model):
    """
    Define the types of exams used in the school (e.g., Midterm, End of Term, Beginning of Term).
    Admins can select which exam types are active for each term.
    """
    EXAM_TYPE_CHOICES = [
        ('beginning', 'Beginning of Term'),
        ('midterm', 'Midterm'),
        ('endterm', 'End of Term'),
        ('other', 'Other'),
    ]
    
    name = models.CharField(max_length=100)
    exam_type = models.CharField(max_length=20, choices=EXAM_TYPE_CHOICES)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('name', 'exam_type')
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.exam_type})"


class AcademicCalendarEvent(models.Model):
    """
    Mark important dates in the academic calendar (exams, visitation days, payment deadlines, etc.).
    Helps coordinate school activities and remind parents/staff.
    """
    EVENT_TYPE_CHOICES = [
        ('exam', 'Exam'),
        ('visitation_day', 'Visitation Day (VD)'),
        ('payment_deadline', 'Payment Deadline'),
        ('holiday', 'Holiday'),
        ('school_closure', 'School Closure'),
        ('event', 'Event'),
        ('other', 'Other'),
    ]
    
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name='calendar_events')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    exam_type = models.ForeignKey(ExamType, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    event_date = models.DateField()
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    notify_parents = models.BooleanField(default=False)
    notify_teachers = models.BooleanField(default=False)
    notify_staff = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_calendar_events')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['event_date', 'start_time']
        indexes = [
            models.Index(fields=['academic_term', 'event_date']),
            models.Index(fields=['event_type', 'event_date']),
        ]

    def __str__(self):
        return f"{self.title} ({self.event_date})"


class TermInstallmentPlan(models.Model):
    """
    Define installment payment plans for a term (e.g., 2 or 3 installments).
    Splits the term into periods and specifies payment deadlines for each installment.
    """
    academic_term = models.OneToOneField(AcademicTerm, on_delete=models.CASCADE, related_name='installment_plan')
    number_of_installments = models.IntegerField(choices=[(2, '2 Installments'), (3, '3 Installments')], default=2)
    installments = models.JSONField(
        default=list,
        help_text='List of installments: [{"number": 1, "due_date": "YYYY-MM-DD", "percentage": 50}, ...]'
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_term_installment_plans')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.academic_term} - {self.number_of_installments} Installments"


class StudentDebtRecord(models.Model):
    """
    Track unpaid fees/debt from previous terms separately from current term fees.
    Helps distinguish between new fees and carried-forward debt.
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='debt_records')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT)
    original_amount = models.DecimalField(max_digits=12, decimal_places=2)
    outstanding_amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=200, default='Unpaid fees from previous term')
    is_settled = models.BooleanField(default=False)
    settled_date = models.DateTimeField(blank=True, null=True)
    settled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='settled_debts')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('student', 'academic_term')
        indexes = [
            models.Index(fields=['student', 'is_settled']),
            models.Index(fields=['academic_term', 'is_settled']),
        ]

    def __str__(self):
        return f"Debt: {self.student} - {self.outstanding_amount}"


class TeacherSalary(models.Model):
    """
    Track teacher salary/compensation records.
    """
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='salary_records')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.SET_NULL, null=True, blank=True)
    base_salary = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='UGX')
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('paid', 'Paid'),
            ('partial', 'Partial Payment'),
        ],
        default='pending'
    )
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_teacher_salaries')
    paid_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='paid_teacher_salaries')
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    paid_date = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['teacher', 'academic_term']),
            models.Index(fields=['payment_status', 'paid_date']),
        ]

    def __str__(self):
        teacher_name = str(self.teacher) if self.teacher else 'N/A'
        return f"{teacher_name} - {self.base_salary} ({self.payment_status})"


class TeacherAllowance(models.Model):
    """
    Track additional allowances for teachers (transport, housing, etc.).
    """
    ALLOWANCE_TYPE_CHOICES = [
        ('transport', 'Transport Allowance'),
        ('housing', 'Housing Allowance'),
        ('meal', 'Meal Allowance'),
        ('performance', 'Performance Bonus'),
        ('other', 'Other'),
    ]
    
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='allowances')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.SET_NULL, null=True, blank=True)
    allowance_type = models.CharField(max_length=20, choices=ALLOWANCE_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='UGX')
    is_paid = models.BooleanField(default=False)
    paid_date = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_allowances')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        teacher_name = str(self.teacher) if self.teacher else 'N/A'
        allowance_label = dict(self.ALLOWANCE_TYPE_CHOICES).get(self.allowance_type, self.allowance_type)
        return f"{teacher_name} - {allowance_label}"


class OtherStaff(models.Model):
    """
    Track non-portal staff workers (cooks, cleaners, guards, etc.) who need to be paid
    but don't have user accounts in the system.
    """
    STAFF_ROLE_CHOICES = [
        ('cook', 'Cook'),
        ('cleaner', 'Cleaner'),
        ('guard', 'Guard'),
        ('driver', 'Driver'),
        ('laborer', 'Laborer'),
        ('maintenance', 'Maintenance'),
        ('other', 'Other'),
    ]
    
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=STAFF_ROLE_CHOICES)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    base_salary = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='UGX')
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_other_staff')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['first_name', 'last_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.role})"


class StaffPayroll(models.Model):
    """
    Track payroll records for all staff (teachers via TeacherSalary, other staff via OtherStaff).
    This provides a unified payroll history.
    """
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.SET_NULL, null=True, blank=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, blank=True, related_name='payroll_records')
    other_staff = models.ForeignKey(OtherStaff, on_delete=models.SET_NULL, null=True, blank=True, related_name='payroll_records')
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='UGX')
    payment_method = models.CharField(
        max_length=50,
        choices=[
            ('cash', 'Cash'),
            ('bank_transfer', 'Bank Transfer'),
            ('mobile_money', 'Mobile Money'),
            ('check', 'Check'),
        ],
        default='cash'
    )
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('paid', 'Paid'),
        ],
        default='pending'
    )
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_payroll')
    paid_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='paid_payroll')
    paid_date = models.DateTimeField(blank=True, null=True)
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['academic_term', 'payment_status']),
            models.Index(fields=['paid_date']),
        ]

    def __str__(self):
        staff_name = ""
        if self.teacher:
            staff_name = str(self.teacher)
        elif self.other_staff:
            staff_name = f"{self.other_staff.first_name} {self.other_staff.last_name}"
        return f"Payroll: {staff_name} - {self.net_amount} ({self.payment_status})"
