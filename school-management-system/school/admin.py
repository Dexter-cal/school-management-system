# pyright: reportMissingModuleSource=false
from django.contrib import admin
from django.utils import timezone

from .models import (
    APICredential,
    APICredentialHealthLog,
    AcademicTerm,
    AlumniRegister,
    Announcement,
    Attendance,
    CashbookClose,
    ClassCharge,
    ClassSubject,
    CommunicationCampaign,
    CommunicationDelivery,
    DepositBatch,
    DocumentDraft,
    Event,
    ExamPaper,
    Expense,
    ExpenseCategory,
    FeePromise,
    FeeReminderLog,
    FeeStructure,
    GradingScale,
    IDCounter,
    InstallmentPlan,
    InstallmentPlanItem,
    Invoice,
    InvoiceAdjustment,
    Mark,
    Notification,
    OTP,
    Payment,
    PrintQueueItem,
    PromotionAudit,
    ResultsHoldLog,
    SchoolClass,
    SecurityAuditLog,
    Student,
    StudentGuardianLink,
    Subject,
    SystemSetting,
    Teacher,
    TeacherAttendance,
    TeacherAttendanceQRToken,
    Timetable,
    UserProfile,
    UserSession,
    # New models
    ExamType,
    AcademicCalendarEvent,
    TermInstallmentPlan,
    StudentDebtRecord,
    TeacherSalary,
    TeacherAllowance,
    OtherStaff,
    StaffPayroll,
)


admin.site.site_header = "Bitende Junior School Admin"
admin.site.site_title = "BJS Admin"
admin.site.index_title = "School Operations"


def _user_role(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return "superadmin"
    profile = getattr(user, "profile", None)
    return getattr(profile, "role", None)


def _is_superadmin_user(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and _user_role(user) == "superadmin")


class GuardianLinkInline(admin.TabularInline):
    model = StudentGuardianLink
    fk_name = "student"
    extra = 0
    autocomplete_fields = ("parent_user", "created_by")
    fields = ("parent_user", "relationship", "is_active", "created_by", "created_at")
    readonly_fields = ("created_at",)
    verbose_name = "Guardian Link"
    verbose_name_plural = "Guardian Links"


class InstallmentPlanItemInline(admin.TabularInline):
    model = InstallmentPlanItem
    extra = 0
    fields = (
        "label",
        "due_date",
        "amount",
        "amount_paid",
        "status",
        "reminder_count",
        "last_reminder_at",
        "paid_at",
        "notes",
    )
    readonly_fields = ("amount_paid", "reminder_count", "last_reminder_at", "paid_at")


@admin.register(APICredential)
class APICredentialAdmin(admin.ModelAdmin):
    list_display = ("service_name", "is_active", "last_verify_ok", "last_verified_at", "updated_at", "created_at")
    list_filter = ("service_name", "is_active", "last_verify_ok")
    search_fields = ("service_name", "client_id")
    readonly_fields = (
        "created_at",
        "updated_at",
        "last_verified_at",
        "last_verify_ok",
        "last_verify_detail",
        "last_verify_extra",
    )
    fieldsets = (
        ("Service", {"fields": ("service_name", "is_active")}),
        ("Credentials", {"fields": ("client_id", "client_secret", "api_key", "extra_data")}),
        (
            "Verification",
            {
                "fields": (
                    "last_verified_at",
                    "last_verify_ok",
                    "last_verify_detail",
                    "last_verify_extra",
                )
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_module_permission(self, request):
        return _is_superadmin_user(request)

    def has_view_permission(self, request, obj=None):
        return _is_superadmin_user(request)

    def has_add_permission(self, request):
        return _is_superadmin_user(request)

    def has_change_permission(self, request, obj=None):
        return _is_superadmin_user(request)

    def has_delete_permission(self, request, obj=None):
        return _is_superadmin_user(request)


@admin.register(APICredentialHealthLog)
class APICredentialHealthLogAdmin(admin.ModelAdmin):
    list_display = ("service_name", "is_ok", "verified_at", "verified_by", "detail_short")
    list_filter = ("service_name", "is_ok", "verified_at")
    search_fields = ("service_name", "detail", "verified_by__username")
    list_select_related = ("credential", "verified_by")
    autocomplete_fields = ("credential", "verified_by")
    readonly_fields = ("credential", "service_name", "verified_by", "is_ok", "detail", "extra", "verified_at", "created_at")
    date_hierarchy = "verified_at"

    @admin.display(description="Detail")
    def detail_short(self, obj):
        text = (obj.detail or "").strip()
        return text[:80] + ("..." if len(text) > 80 else "")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return _is_superadmin_user(request)


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("level", "section_list", "annual_fee", "max_students_per_section", "teacher_a", "teacher_b")
    search_fields = ("level", "teacher_a", "teacher_b")
    ordering = ("level",)

    @admin.display(description="Sections")
    def section_list(self, obj):
        return ", ".join(obj.sections or []) or "-"


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = (
        "employee_id",
        "first_name",
        "last_name",
        "assigned_class",
        "class_teacher_assignment",
        "phone",
        "employment_type",
    )
    list_filter = ("employment_type", "is_class_teacher")
    search_fields = (
        "employee_id",
        "first_name",
        "last_name",
        "phone",
        "email",
        "assigned_class",
        "user__username",
    )
    list_select_related = ("user", "class_teacher_class")
    autocomplete_fields = ("user", "class_teacher_class")

    @admin.display(description="Class Teacher")
    def class_teacher_assignment(self, obj):
        if not obj.is_class_teacher or not obj.class_teacher_class_id:
            return "-"
        section = f" {obj.class_teacher_section}" if obj.class_teacher_section else ""
        return f"{obj.class_teacher_class.level}{section}"


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "student_id",
        "first_name",
        "last_name",
        "current_class",
        "section",
        "status",
        "parent_name",
        "parent_phone",
    )
    list_filter = ("status", "gender", "current_class", "section")
    search_fields = (
        "student_id",
        "first_name",
        "last_name",
        "parent_name",
        "parent_phone",
        "parent_phone2",
        "home_address",
    )
    list_select_related = ("current_class", "previous_class")
    autocomplete_fields = ("current_class", "previous_class")
    inlines = [GuardianLinkInline]


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ("school_class", "term", "year", "amount")
    list_filter = ("year", "term", "school_class")
    search_fields = ("school_class__level",)
    list_select_related = ("school_class",)
    autocomplete_fields = ("school_class",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "role",
        "phone_number",
        "email_address",
        "must_change_password",
        "two_factor_enabled",
    )
    list_filter = ("role", "must_change_password", "two_factor_enabled")
    search_fields = ("user__username", "user__first_name", "user__last_name", "phone_number", "email_address")
    list_select_related = ("user",)
    autocomplete_fields = ("user",)


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = (
        "academic_year",
        "term_number",
        "start_date",
        "end_date",
        "is_archived",
        "marks_locked",
        "auto_generate_invoices_on_start",
        "sms_parents_on_start",
    )
    list_filter = ("academic_year", "term_number", "is_archived", "marks_locked")
    search_fields = ("marks_lock_reason",)
    list_select_related = ("marks_locked_by",)
    autocomplete_fields = ("marks_locked_by",)
    date_hierarchy = "start_date"
    ordering = ("-academic_year", "term_number")


@admin.register(PromotionAudit)
class PromotionAuditAdmin(admin.ModelAdmin):
    list_display = ("student", "decision", "old_class", "new_class", "admin_user", "decision_date")
    list_filter = ("decision", "decision_date")
    search_fields = (
        "student__student_id",
        "student__first_name",
        "student__last_name",
        "notes",
        "admin_user__username",
    )
    list_select_related = ("student", "old_class", "new_class", "admin_user")
    autocomplete_fields = ("student", "old_class", "new_class", "admin_user")
    date_hierarchy = "decision_date"


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "code", "is_used", "created_at", "expires_at")
    list_filter = ("purpose", "is_used")
    search_fields = ("user__username", "user__first_name", "user__last_name", "code")
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    date_hierarchy = "created_at"


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "session_key", "login_time", "logout_time", "ip_address", "is_active")
    list_filter = ("is_active",)
    search_fields = ("user__username", "session_key", "ip_address", "user_agent")
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    date_hierarchy = "login_time"


@admin.register(SecurityAuditLog)
class SecurityAuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "event_type", "user", "ip_address")
    list_filter = ("event_type", "timestamp")
    search_fields = ("event_type", "user__username", "details", "ip_address")
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    date_hierarchy = "timestamp"
    ordering = ("-timestamp",)
    readonly_fields = ("user", "event_type", "timestamp", "ip_address", "details")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.action(description="Mark selected payments as approved")
def mark_payments_approved(modeladmin, request, queryset):
    queryset.update(status="approved", approved_by_id=request.user.id, approved_at=timezone.now())


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "student",
        "amount",
        "method",
        "status",
        "academic_year",
        "term_number",
        "receipt_number",
        "received_at",
    )
    list_filter = ("status", "method", "academic_year", "term_number")
    search_fields = (
        "student__student_id",
        "student__first_name",
        "student__last_name",
        "reference",
        "receipt_number",
    )
    list_select_related = ("student", "received_by", "approved_by", "submitted_by", "deposit_batch")
    autocomplete_fields = ("student", "submitted_by", "received_by", "approved_by", "deposit_batch")
    readonly_fields = ("created_at", "updated_at", "approved_at")
    date_hierarchy = "received_at"
    actions = [mark_payments_approved]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "academic_year",
        "term_number",
        "amount_due",
        "amount_paid",
        "balance_due",
        "status",
        "results_blocked",
    )
    list_filter = ("status", "academic_year", "term_number", "results_blocked")
    search_fields = ("student__student_id", "student__first_name", "student__last_name")
    list_select_related = ("student", "results_blocked_by")
    autocomplete_fields = ("student", "results_blocked_by")
    readonly_fields = ("created_at", "updated_at", "balance_due")
    date_hierarchy = "created_at"

    @admin.display(description="Balance")
    def balance_due(self, obj):
        return (obj.amount_due or 0) - (obj.amount_paid or 0)


@admin.register(InvoiceAdjustment)
class InvoiceAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("student", "academic_year", "term_number", "kind", "amount", "is_active", "created_at")
    list_filter = ("kind", "is_active", "academic_year", "term_number")
    search_fields = (
        "student__student_id",
        "student__first_name",
        "student__last_name",
        "title",
        "notes",
    )
    list_select_related = ("student", "created_by")
    autocomplete_fields = ("student", "created_by")
    date_hierarchy = "created_at"


@admin.register(ClassCharge)
class ClassChargeAdmin(admin.ModelAdmin):
    list_display = (
        "school_class",
        "section",
        "title",
        "amount",
        "academic_year",
        "term_number",
        "due_date",
        "is_published",
        "is_active",
    )
    list_filter = ("is_published", "is_active", "academic_year", "term_number", "school_class")
    search_fields = ("school_class__level", "title", "description", "section")
    list_select_related = ("school_class", "created_by")
    autocomplete_fields = ("school_class", "created_by")
    date_hierarchy = "due_date"


@admin.register(DepositBatch)
class DepositBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "bank_name", "deposit_date", "reference", "is_posted", "created_by", "posted_by")
    list_filter = ("is_posted", "bank_name", "deposit_date")
    search_fields = ("name", "reference", "bank_name", "notes")
    list_select_related = ("created_by", "posted_by")
    autocomplete_fields = ("created_by", "posted_by")
    readonly_fields = ("posted_at", "created_at", "updated_at")
    date_hierarchy = "deposit_date"


@admin.register(CashbookClose)
class CashbookCloseAdmin(admin.ModelAdmin):
    list_display = (
        "close_date",
        "cashier",
        "status",
        "cash_received_total",
        "approved_expense_total",
        "expected_cash_on_hand",
        "counted_cash_on_hand",
        "variance_amount",
        "closed_by",
    )
    list_filter = ("close_date", "status", "cashier")
    search_fields = ("cashier__username", "closed_by__username", "notes")
    list_select_related = ("cashier", "closed_by")
    autocomplete_fields = ("cashier", "closed_by")
    readonly_fields = (
        "cash_received_total",
        "non_cash_received_total",
        "approved_expense_total",
        "expected_cash_on_hand",
        "variance_amount",
        "deposit_batch_total",
        "payment_count",
        "expense_count",
        "snapshot",
        "closed_at",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "close_date"


@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "academic_year",
        "term_number",
        "title",
        "total_amount",
        "status",
        "created_by",
        "approved_by",
        "created_at",
    )
    list_filter = ("status", "academic_year", "term_number")
    search_fields = (
        "student__student_id",
        "student__first_name",
        "student__last_name",
        "title",
        "notes",
    )
    list_select_related = ("student", "invoice", "created_by", "approved_by")
    autocomplete_fields = ("student", "invoice", "created_by", "approved_by")
    inlines = [InstallmentPlanItemInline]
    date_hierarchy = "start_date"


@admin.register(InstallmentPlanItem)
class InstallmentPlanItemAdmin(admin.ModelAdmin):
    list_display = ("plan", "label", "due_date", "amount", "amount_paid", "status", "reminder_count", "paid_at")
    list_filter = ("status", "due_date")
    search_fields = ("plan__student__student_id", "plan__student__first_name", "plan__student__last_name", "label", "notes")
    list_select_related = ("plan", "plan__student")
    autocomplete_fields = ("plan",)
    readonly_fields = ("amount_paid", "reminder_count", "last_reminder_at", "paid_at", "created_at", "updated_at")
    date_hierarchy = "due_date"


@admin.action(description="Mark selected fee promises as kept")
def mark_promises_kept(modeladmin, request, queryset):
    queryset.update(status="kept", fulfilled_at=timezone.now())


@admin.action(description="Mark selected fee promises as missed")
def mark_promises_missed(modeladmin, request, queryset):
    queryset.update(status="missed")


@admin.register(FeePromise)
class FeePromiseAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "academic_year",
        "term_number",
        "promised_for",
        "amount",
        "status",
        "created_by",
        "reminder_count",
    )
    list_filter = ("status", "academic_year", "term_number")
    search_fields = ("student__student_id", "student__first_name", "student__last_name", "notes")
    list_select_related = ("student", "installment", "created_by")
    autocomplete_fields = ("student", "installment", "created_by")
    readonly_fields = ("last_reminder_at", "fulfilled_at", "created_at", "updated_at")
    date_hierarchy = "promised_for"
    actions = [mark_promises_kept, mark_promises_missed]


@admin.register(FeeReminderLog)
class FeeReminderLogAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "channel",
        "status",
        "recipient",
        "academic_year",
        "term_number",
        "created_by",
        "created_at",
    )
    list_filter = ("channel", "status", "academic_year", "term_number")
    search_fields = (
        "student__student_id",
        "student__first_name",
        "student__last_name",
        "recipient",
        "message",
    )
    list_select_related = ("student", "invoice", "plan", "installment", "promise", "created_by")
    autocomplete_fields = ("student", "invoice", "plan", "installment", "promise", "created_by")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


@admin.register(ResultsHoldLog)
class ResultsHoldLogAdmin(admin.ModelAdmin):
    list_display = ("invoice", "action", "reason", "source", "acted_by", "acted_at")
    list_filter = ("action", "source", "acted_at")
    search_fields = (
        "invoice__student__student_id",
        "invoice__student__first_name",
        "invoice__student__last_name",
        "reason",
    )
    list_select_related = ("invoice", "acted_by")
    autocomplete_fields = ("invoice", "acted_by")
    readonly_fields = ("invoice", "action", "reason", "source", "acted_by", "acted_at")
    date_hierarchy = "acted_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.action(description="Mark selected expenses as approved")
def mark_expenses_approved(modeladmin, request, queryset):
    queryset.update(status="approved", approved_by_id=request.user.id, approved_at=timezone.now())


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("expense_date", "category", "amount", "vendor", "status", "created_by", "approved_by")
    list_filter = ("status", "category", "expense_date")
    search_fields = ("vendor", "description", "category__name")
    list_select_related = ("category", "created_by", "approved_by")
    autocomplete_fields = ("category", "created_by", "approved_by")
    readonly_fields = ("approved_at", "created_at", "updated_at")
    date_hierarchy = "expense_date"
    actions = [mark_expenses_approved]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "start_date", "end_date", "is_published", "created_by", "created_at")
    list_filter = ("is_published", "start_date")
    search_fields = ("title", "description")
    list_select_related = ("created_by",)
    autocomplete_fields = ("created_by",)
    date_hierarchy = "start_date"


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "updated_at")
    search_fields = ("key",)
    readonly_fields = ("updated_at",)


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "is_pinned", "is_archived", "expires_at", "created_by", "created_at")
    list_filter = ("is_published", "is_pinned", "is_archived")
    search_fields = ("title", "body")
    list_select_related = ("created_by",)
    autocomplete_fields = ("created_by",)
    date_hierarchy = "created_at"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "category", "title", "student", "school_class", "event_key", "is_read", "read_at", "created_at")
    list_filter = ("category", "school_class", "is_read", "created_at")
    search_fields = ("user__username", "title", "message", "student__student_id", "student__first_name", "student__last_name", "school_class__level", "event_key")
    list_select_related = ("user", "student", "school_class")
    autocomplete_fields = ("user", "student", "school_class")
    date_hierarchy = "created_at"


@admin.register(ExamPaper)
class ExamPaperAdmin(admin.ModelAdmin):
    list_display = ("title", "school_class", "section", "subject", "teacher", "status", "submitted_at", "printed_at")
    list_filter = ("status", "school_class", "section")
    search_fields = ("title", "description", "teacher__first_name", "teacher__last_name", "subject__name")
    list_select_related = ("school_class", "subject", "teacher", "printed_by")
    autocomplete_fields = ("school_class", "subject", "teacher", "printed_by")
    date_hierarchy = "created_at"


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "description")


@admin.register(ClassSubject)
class ClassSubjectAdmin(admin.ModelAdmin):
    list_display = ("school_class", "subject", "periods_per_week", "is_active")
    list_filter = ("is_active", "school_class")
    search_fields = ("school_class__level", "subject__name", "notes")
    list_select_related = ("school_class", "subject")
    autocomplete_fields = ("school_class", "subject")


@admin.register(DocumentDraft)
class DocumentDraftAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "kind",
        "version_number",
        "workflow_status",
        "library_scope",
        "status",
        "created_by",
        "school_class",
        "subject",
        "submitted_at",
        "printed_at",
    )
    list_filter = ("kind", "workflow_status", "library_scope", "status", "school_class")
    search_fields = ("title", "body", "created_by__username")
    list_select_related = ("created_by", "school_class", "subject", "printed_by", "approved_by", "published_by", "previous_version")
    autocomplete_fields = ("created_by", "school_class", "subject", "printed_by", "approved_by", "published_by", "previous_version")
    date_hierarchy = "created_at"


@admin.register(CommunicationCampaign)
class CommunicationCampaignAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "document",
        "channel",
        "audience",
        "scheduled_for",
        "status",
        "sent_count",
        "failed_count",
        "skipped_count",
        "created_by",
    )
    list_filter = ("channel", "audience", "status")
    search_fields = ("document__title", "created_by__username", "notes")
    list_select_related = ("document", "school_class", "student", "created_by")
    autocomplete_fields = ("document", "school_class", "student", "created_by")
    date_hierarchy = "scheduled_for"


@admin.register(CommunicationDelivery)
class CommunicationDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "campaign",
        "channel",
        "recipient_name",
        "recipient_email",
        "recipient_phone",
        "status",
        "attempt_count",
        "last_attempt_at",
        "sent_at",
        "opened_at",
        "confirmed_at",
        "replied_at",
    )
    list_filter = ("channel", "status")
    search_fields = (
        "campaign__document__title",
        "recipient_name",
        "recipient_email",
        "recipient_phone",
        "student__student_id",
        "ack_token",
    )
    list_select_related = ("campaign", "campaign__document", "student")
    autocomplete_fields = ("campaign", "student")
    readonly_fields = (
        "ack_token",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"


@admin.register(StudentGuardianLink)
class StudentGuardianLinkAdmin(admin.ModelAdmin):
    list_display = ("parent_user", "student", "relationship", "is_active", "created_by", "created_at")
    list_filter = ("relationship", "is_active")
    search_fields = (
        "parent_user__username",
        "student__student_id",
        "student__first_name",
        "student__last_name",
    )
    list_select_related = ("parent_user", "student", "created_by")
    autocomplete_fields = ("parent_user", "student", "created_by")
    date_hierarchy = "created_at"


@admin.register(PrintQueueItem)
class PrintQueueItemAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "title", "status", "student", "teacher", "requested_by", "expires_at", "printed_at")
    list_filter = ("kind", "status", "is_sensitive")
    search_fields = (
        "title",
        "student__student_id",
        "student__first_name",
        "student__last_name",
        "teacher__employee_id",
    )
    list_select_related = ("student", "teacher", "requested_by", "printed_by")
    autocomplete_fields = ("student", "teacher", "requested_by", "printed_by")
    date_hierarchy = "created_at"


admin.site.register(Mark)
admin.site.register(Attendance)
admin.site.register(TeacherAttendance)
admin.site.register(TeacherAttendanceQRToken)
admin.site.register(Timetable)
admin.site.register(AlumniRegister)
admin.site.register(IDCounter)
admin.site.register(GradingScale)


# ==================== NEW MODEL ADMIN REGISTRATIONS ====================

@admin.register(ExamType)
class ExamTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'exam_type', 'is_active', 'created_at')
    list_filter = ('exam_type', 'is_active', 'created_at')
    search_fields = ('name', 'description')


@admin.register(AcademicCalendarEvent)
class AcademicCalendarEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'event_type', 'event_date', 'academic_term', 'created_by')
    list_filter = ('event_type', 'event_date', 'academic_term', 'notify_parents', 'notify_teachers')
    search_fields = ('title', 'description')
    date_hierarchy = 'event_date'
    readonly_fields = ('created_by', 'created_at', 'updated_at')
    
    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(TermInstallmentPlan)
class TermInstallmentPlanAdmin(admin.ModelAdmin):
    list_display = ('academic_term', 'number_of_installments', 'created_by', 'created_at')
    list_filter = ('number_of_installments', 'created_at')
    readonly_fields = ('created_by', 'created_at', 'updated_at')
    
    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(StudentDebtRecord)
class StudentDebtRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'academic_term', 'outstanding_amount', 'is_settled', 'created_at')
    list_filter = ('is_settled', 'academic_term', 'created_at')
    search_fields = ('student__first_name', 'student__last_name')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'


@admin.register(TeacherSalary)
class TeacherSalaryAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'academic_term', 'base_salary', 'payment_status', 'paid_date', 'created_at')
    list_filter = ('payment_status', 'academic_term', 'created_at', 'paid_date')
    search_fields = ('teacher__user__first_name', 'teacher__user__last_name')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'


@admin.register(TeacherAllowance)
class TeacherAllowanceAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'allowance_type', 'amount', 'is_paid', 'academic_term', 'created_at')
    list_filter = ('allowance_type', 'is_paid', 'academic_term', 'created_at')
    search_fields = ('teacher__user__first_name', 'teacher__user__last_name')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'


@admin.register(OtherStaff)
class OtherStaffAdmin(admin.ModelAdmin):
    list_display = ('get_full_name', 'role', 'base_salary', 'is_active', 'start_date', 'end_date')
    list_filter = ('role', 'is_active', 'start_date')
    search_fields = ('first_name', 'last_name', 'email', 'phone_number')
    readonly_fields = ('created_by', 'created_at', 'updated_at')
    date_hierarchy = 'start_date'
    
    @admin.display(description='Name')
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"
    
    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(StaffPayroll)
class StaffPayrollAdmin(admin.ModelAdmin):
    list_display = ('get_staff_name', 'academic_term', 'net_amount', 'payment_status', 'paid_date', 'created_at')
    list_filter = ('payment_status', 'academic_term', 'payment_method', 'created_at', 'paid_date')
    search_fields = ('teacher__user__first_name', 'teacher__user__last_name', 'other_staff__first_name', 'other_staff__last_name')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    
    @admin.display(description='Staff Member')
    def get_staff_name(self, obj):
        if obj.teacher:
            teacher_user = getattr(obj.teacher, 'user', None)
            return teacher_user.get_full_name() if teacher_user else f'Teacher #{obj.teacher_id or "N/A"}'
        elif obj.other_staff:
            return f"{obj.other_staff.first_name} {obj.other_staff.last_name}"
        return "N/A"
