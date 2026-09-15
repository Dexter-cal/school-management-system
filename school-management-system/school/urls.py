from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SchoolClassViewSet, TeacherViewSet, StudentViewSet, FeeStructureViewSet,
    MarkViewSet, AttendanceViewSet, TeacherAttendanceViewSet, TimetableViewSet, UserViewSet, AuthViewSet,
    PromotionViewSet, AcademicTermViewSet, ReportCardViewSet, GradingScaleViewSet,
    SecurityAuditLogViewSet, APICredentialViewSet, SubjectViewSet, ClassSubjectViewSet, DocumentDraftViewSet, UploadViewSet, PaymentSubmissionViewSet,
    PrintQueueViewSet,
    AIToolsViewSet,
    PaymentViewSet, InvoiceViewSet, ClassChargeViewSet, EventViewSet, AnnouncementViewSet,
    NotificationViewSet, SystemSettingViewSet, SecurityAdminViewSet, ExamPaperViewSet,
    InvoiceAdjustmentViewSet, StudentGuardianLinkViewSet,
    DepositBatchViewSet, CashbookCloseViewSet, InstallmentPlanViewSet, FeePromiseViewSet,
    FeeReminderLogViewSet, ExpenseCategoryViewSet, ExpenseViewSet,
    CommunicationCampaignViewSet, CommunicationDeliveryViewSet,
    # New viewsets
    ExamTypeViewSet, AcademicCalendarEventViewSet, TermInstallmentPlanViewSet, StudentDebtRecordViewSet,
    TeacherSalaryViewSet, TeacherAllowanceViewSet, OtherStaffViewSet, StaffPayrollViewSet, ChatMessageViewSet,
    index  # Added new ViewSets
)

router = DefaultRouter()
router.register(r'classes', SchoolClassViewSet)
router.register(r'teachers', TeacherViewSet)
router.register(r'students', StudentViewSet)
router.register(r'fees', FeeStructureViewSet)
router.register(r'marks', MarkViewSet)
router.register(r'attendance', AttendanceViewSet)
router.register(r'teacher-attendance', TeacherAttendanceViewSet, basename='teacher-attendance')
router.register(r'timetable', TimetableViewSet)
router.register(r'users', UserViewSet)
router.register(r'auth', AuthViewSet, basename='auth')
router.register(r'promotions', PromotionViewSet, basename='promotions')  # Registered PromotionViewSet
router.register(r'terms', AcademicTermViewSet, basename='terms')  # Registered AcademicTermViewSet
router.register(r'report-cards', ReportCardViewSet, basename='report-cards')
router.register(r'grading-scales', GradingScaleViewSet)
router.register(r'audit-logs', SecurityAuditLogViewSet, basename='audit-logs')
router.register(r'api-credentials', APICredentialViewSet, basename='api-credentials')
router.register(r'subjects', SubjectViewSet, basename='subjects')
router.register(r'class-subjects', ClassSubjectViewSet, basename='class-subjects')
router.register(r'document-drafts', DocumentDraftViewSet, basename='document-drafts')
router.register(r'uploads', UploadViewSet, basename='uploads')
router.register(r'print-queue', PrintQueueViewSet, basename='print-queue')
router.register(r'exam-papers', ExamPaperViewSet, basename='exam-papers')
router.register(r'ai-tools', AIToolsViewSet, basename='ai-tools')
router.register(r'payments', PaymentViewSet, basename='payments')
router.register(r'payment-submissions', PaymentSubmissionViewSet, basename='payment-submissions')
router.register(r'invoices', InvoiceViewSet, basename='invoices')
router.register(r'invoice-adjustments', InvoiceAdjustmentViewSet, basename='invoice-adjustments')
router.register(r'class-charges', ClassChargeViewSet, basename='class-charges')
router.register(r'events', EventViewSet, basename='events')
router.register(r'announcements', AnnouncementViewSet, basename='announcements')
router.register(r'notifications', NotificationViewSet, basename='notifications')
router.register(r'system-settings', SystemSettingViewSet, basename='system-settings')
router.register(r'security', SecurityAdminViewSet, basename='security')
router.register(r'guardian-links', StudentGuardianLinkViewSet, basename='guardian-links')
router.register(r'deposit-batches', DepositBatchViewSet, basename='deposit-batches')
router.register(r'cashbook-closes', CashbookCloseViewSet, basename='cashbook-closes')
router.register(r'installment-plans', InstallmentPlanViewSet, basename='installment-plans')
router.register(r'fee-promises', FeePromiseViewSet, basename='fee-promises')
router.register(r'fee-reminders', FeeReminderLogViewSet, basename='fee-reminders')
router.register(r'expense-categories', ExpenseCategoryViewSet, basename='expense-categories')
router.register(r'expenses', ExpenseViewSet, basename='expenses')
router.register(r'communication-campaigns', CommunicationCampaignViewSet, basename='communication-campaigns')
router.register(r'communication-deliveries', CommunicationDeliveryViewSet, basename='communication-deliveries')

# New model routers
router.register(r'exam-types', ExamTypeViewSet, basename='exam-types')
router.register(r'academic-calendar-events', AcademicCalendarEventViewSet, basename='academic-calendar-events')
router.register(r'term-installment-plans', TermInstallmentPlanViewSet, basename='term-installment-plans')
router.register(r'student-debts', StudentDebtRecordViewSet, basename='student-debts')
router.register(r'teacher-salaries', TeacherSalaryViewSet, basename='teacher-salaries')
router.register(r'teacher-allowances', TeacherAllowanceViewSet, basename='teacher-allowances')
router.register(r'other-staff', OtherStaffViewSet, basename='other-staff')
router.register(r'staff-payroll', StaffPayrollViewSet, basename='staff-payroll')
router.register(r'chat-messages', ChatMessageViewSet, basename='chat-messages')

urlpatterns = [
    path('', index, name='index'),
    path('api/', include(router.urls)),
]
