from rest_framework import serializers
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .models import (
    SchoolClass, Subject, ClassSubject, Teacher, Student, FeeStructure, Mark, Attendance, Timetable, UserProfile,
    AcademicTerm, PromotionAudit, AlumniRegister, OTP, IDCounter, GradingScale, UserSession, SecurityAuditLog, APICredential,
    APICredentialHealthLog,
    Payment, Invoice, ClassCharge, Event, SystemSetting, TeacherAttendance, TeacherAttendanceQRToken,
    Notification, Announcement, DocumentDraft, ExamPaper, InvoiceAdjustment, StudentGuardianLink, PrintQueueItem,
    DepositBatch, ExpenseCategory, Expense, CashbookClose, InstallmentPlan, InstallmentPlanItem,
    FeePromise, FeeReminderLog, ResultsHoldLog, CommunicationCampaign, CommunicationDelivery  # Added new models
)
from .utils import sanitize_rich_text_html
from django.contrib.auth.models import User

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            'role', 'avatar',
            'phone_number', 'email_address',
            'photo_url',
            'last_login_ip', 'last_login_ua',
            'notification_prefs',
            'must_change_password', 'two_factor_enabled',
            'profile_data',
        ]

class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    caps = serializers.SerializerMethodField(read_only=True)
    # Add a writable field for password if needed for user creation/reset
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'profile', 'caps', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def get_caps(self, obj):
        """
        Small set of UI capabilities used by the SPA to hide sensitive features.
        Keep this conservative: only enable when prerequisites are truly met.
        """
        try:
            role = obj.profile.role
        except Exception:
            role = None

        caps = { 
            'ai_tools': False, 
            'term_manage': False, 
            'class_teacher': False, 
        } 

        # Term management: only special administrators.
        try:
            role = obj.profile.role
        except Exception:
            role = None
        if obj.is_superuser or role in ['superadmin', 'admin', 'headteacher', 'dos']:
            caps['term_manage'] = True

        # AI tools: teacher-only, global toggle, and requires a verified+active AI credential. 
        if role == 'teacher': 
            try: 
                t = getattr(obj, 'teacher_profile', None) 
                caps['class_teacher'] = bool(t and getattr(t, 'is_class_teacher', False) and getattr(t, 'class_teacher_class_id', None)) 
            except Exception: 
                caps['class_teacher'] = False 
            try: 
                from .models import SystemSetting, APICredential 
                enabled = SystemSetting.objects.filter(key='ai_tools_enabled').values_list('value', flat=True).first() 
                enabled = bool(enabled.get('enabled', True)) if isinstance(enabled, dict) else bool(enabled) if enabled is not None else True 
                if enabled: 
                    ok = APICredential.objects.filter(
                        service_name__in=['openai', 'gemini'],
                        is_active=True,
                        last_verify_ok=True,
                    ).exists()
                    caps['ai_tools'] = bool(ok)
            except Exception:
                caps['ai_tools'] = False

        return caps
    
    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = User.objects.create(**validated_data)
        if password is not None:
            user.set_password(password)
            user.save()
        return user
    
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        user = super().update(instance, validated_data)
        if password is not None:
            user.set_password(password)
            user.save()
        return user

class SchoolClassSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolClass
        fields = '__all__'


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = '__all__'


class ClassSubjectSerializer(serializers.ModelSerializer):
    school_class_level = serializers.CharField(source='school_class.level', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)

    class Meta:
        model = ClassSubject
        fields = '__all__'

class TeacherSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    class_teacher_class_level = serializers.CharField(source='class_teacher_class.level', read_only=True)

    class Meta:
        model = Teacher
        fields = '__all__'
        # These are system-managed identifiers/links.
        read_only_fields = ('user', 'employee_id')

class StudentSerializer(serializers.ModelSerializer):
    previous_class_name = serializers.CharField(source='previous_class.level', read_only=True) # Added for display
    current_class_level = serializers.CharField(source='current_class.level', read_only=True)
    class_teacher = serializers.SerializerMethodField(read_only=True)
    parent_email = serializers.SerializerMethodField(read_only=True)
    photo_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Student
        fields = '__all__' # Will now include new fields like conduct_grade, head_teacher_remarks
        # IDs and auto-managed timestamps should not be edited from the client.
        read_only_fields = ('student_id', 'enrollment_date')

    def get_class_teacher(self, obj):
        """
        Used by Parent dashboard to show "contact class teacher" per child.
        Teacher is considered the class teacher if they are explicitly assigned for the student's class/section.
        """
        try:
            if not getattr(obj, 'current_class_id', None):
                return None
            section = (getattr(obj, 'section', None) or '').strip().upper() or None
            qs = Teacher.objects.filter(is_class_teacher=True, class_teacher_class_id=obj.current_class_id)
            if section:
                qs = qs.filter(class_teacher_section__iexact=section)
            else:
                qs = qs.filter(class_teacher_section__isnull=True)
            t = qs.select_related('user').first()
            if not t:
                return None
            name = f"{t.first_name} {t.last_name}".strip() or None
            email = (t.email or (t.user.email if hasattr(t, 'user') and t.user else None)) or None  # type: ignore[attr-defined]
            phone = (t.phone or None)
            return {
                'teacher_id': t.id,  # type: ignore[attr-defined]
                'name': name,
                'phone': phone,
                'email': email,
                'class_level': getattr(t.class_teacher_class, 'level', None) if getattr(t, 'class_teacher_class_id', None) else None,
                'section': (t.class_teacher_section or None),
            }
        except Exception:
            return None

    def get_parent_email(self, obj):
        try:
            profile = UserProfile.objects.filter(role='parent', phone_number=obj.parent_phone).first()
            if profile and profile.email_address:
                return profile.email_address
        except Exception:
            pass
        return None

    def get_photo_url(self, obj):
        try:
            return obj.photo.url if obj.photo else None
        except Exception:
            return None

class FeeStructureSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeStructure
        fields = '__all__'


class ExamPaperSerializer(serializers.ModelSerializer):
    school_class_level = serializers.CharField(source='school_class.level', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    teacher_name = serializers.SerializerMethodField(read_only=True)
    printed_by_username = serializers.CharField(source='printed_by.username', read_only=True)

    class Meta:
        model = ExamPaper
        fields = '__all__'

    def get_teacher_name(self, obj):
        try:
            if obj.teacher:
                return f"{obj.teacher.first_name} {obj.teacher.last_name}"
        except Exception:
            pass
        return None


class PrintQueueItemSerializer(serializers.ModelSerializer):
    requested_by_username = serializers.CharField(source='requested_by.username', read_only=True)
    printed_by_username = serializers.CharField(source='printed_by.username', read_only=True)
    student_name = serializers.SerializerMethodField(read_only=True)
    teacher_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PrintQueueItem
        fields = '__all__'

    def get_student_name(self, obj):
        try:
            if obj.student:
                return f"{obj.student.first_name} {obj.student.last_name}".strip()
        except Exception:
            pass
        return None

    def get_teacher_name(self, obj):
        try:
            if obj.teacher:
                return f"{obj.teacher.first_name} {obj.teacher.last_name}".strip()
        except Exception:
            pass
        return None

class MarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mark
        fields = '__all__'

class AttendanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = '__all__'


class TeacherAttendanceSerializer(serializers.ModelSerializer):
    teacher_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TeacherAttendance
        fields = '__all__'

    def get_teacher_name(self, obj):
        try:
            return f"{obj.teacher.first_name} {obj.teacher.last_name}".strip()
        except Exception:
            return str(obj.teacher_id)


class TeacherAttendanceQRTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherAttendanceQRToken
        fields = '__all__'

class TimetableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Timetable
        fields = '__all__'

class AcademicTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicTerm
        fields = '__all__'

class PromotionAuditSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.__str__', read_only=True)
    admin_username = serializers.CharField(source='admin_user.username', read_only=True)
    old_class_name = serializers.CharField(source='old_class.level', read_only=True)
    new_class_name = serializers.CharField(source='new_class.level', read_only=True)

    class Meta:
        model = PromotionAudit
        fields = '__all__'

class AlumniRegisterSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.__str__', read_only=True)

    class Meta:
        model = AlumniRegister
        fields = '__all__'

class OTPSerializer(serializers.ModelSerializer):
    class Meta:
        model = OTP
        fields = '__all__'

class IDCounterSerializer(serializers.ModelSerializer):
    class Meta:
        model = IDCounter
        fields = '__all__'

class GradingScaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradingScale
        fields = '__all__'

class UserSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSession
        fields = '__all__'

class SecurityAuditLogSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = SecurityAuditLog
        fields = '__all__'


class APICredentialSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        instance = getattr(self, 'instance', None)
        service_name = data.get('service_name') or getattr(instance, 'service_name', None)
        extra_data = data.get('extra_data')
        if extra_data is None and instance is not None:
            extra_data = instance.extra_data or {}
        extra_data = extra_data or {}

        if service_name == 'gmail_smtp':
            username = str(extra_data.get('username') or '').strip()
            if not username:
                raise serializers.ValidationError({'extra_data': {'username': 'Gmail address is required.'}})
            try:
                validate_email(username)
            except ValidationError:
                raise serializers.ValidationError({'extra_data': {'username': 'Enter a valid Gmail address.'}})

            client_secret = str(data.get('client_secret') or getattr(instance, 'client_secret', '') or '').replace(' ', '')
            if client_secret and len(client_secret) < 16:
                raise serializers.ValidationError({'client_secret': 'Gmail app password looks incomplete. Use the full 16-character app password.'})

        if service_name == 'email_smtp':
            username = str(extra_data.get('username') or '').strip()
            if username:
                try:
                    validate_email(username)
                except ValidationError:
                    raise serializers.ValidationError({'extra_data': {'username': 'Enter a valid SMTP username email address.'}})

        return data

    class Meta:
        model = APICredential
        fields = '__all__'


class APICredentialHealthLogSerializer(serializers.ModelSerializer):
    credential_service_label = serializers.CharField(source='credential.get_service_name_display', read_only=True)
    verified_by_username = serializers.CharField(source='verified_by.username', read_only=True)

    class Meta:
        model = APICredentialHealthLog
        fields = '__all__'
        read_only_fields = ('credential', 'service_name', 'verified_by', 'verified_at', 'created_at')


class PaymentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField(read_only=True)
    student_system_id = serializers.CharField(source='student.student_id', read_only=True)
    received_by_username = serializers.CharField(source='received_by.username', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)
    submitted_by_username = serializers.CharField(source='submitted_by.username', read_only=True)
    deposit_batch_name = serializers.CharField(source='deposit_batch.name', read_only=True)

    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = (
            'received_by',
            'approved_by',
            'approved_at',
            'receipt_number',
            'submitted_by',
            'deposit_batch',
            'status',
        )

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"

    def validate_amount(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)
        if not instance:
            return attrs

        new_method = attrs.get('method', instance.method)
        is_submitted_bank_slip = bool(instance.submitted_by_id or instance.receipt_image_url) and (instance.method or '').lower() == 'bank'
        if is_submitted_bank_slip and new_method != instance.method:
            raise serializers.ValidationError({
                'method': 'Submitted bank slip payments cannot change method. Use the approve or reject review actions instead.'
            })
        return attrs


class DepositBatchSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    posted_by_username = serializers.CharField(source='posted_by.username', read_only=True)
    payments_count = serializers.SerializerMethodField(read_only=True)
    total_amount = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DepositBatch
        fields = '__all__'

    def get_payments_count(self, obj):
        try:
            return obj.payments.count()
        except Exception:
            return 0

    def get_total_amount(self, obj):
        try:
            from django.db.models import Sum
            v = obj.payments.aggregate(s=Sum('amount'))['s'] or 0
            return str(v)
        except Exception:
            return "0"


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = '__all__'


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = Expense
        fields = '__all__'

    def validate_amount(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value


class CashbookCloseSerializer(serializers.ModelSerializer):
    cashier_username = serializers.CharField(source='cashier.username', read_only=True)
    closed_by_username = serializers.CharField(source='closed_by.username', read_only=True)

    class Meta:
        model = CashbookClose
        fields = '__all__'
        read_only_fields = (
            'cash_received_total',
            'non_cash_received_total',
            'approved_expense_total',
            'expected_cash_on_hand',
            'variance_amount',
            'deposit_batch_total',
            'payment_count',
            'expense_count',
            'snapshot',
            'closed_by',
            'closed_at',
        )


class InstallmentPlanItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstallmentPlanItem
        fields = '__all__'
        read_only_fields = ('plan', 'amount_paid', 'status', 'reminder_count', 'last_reminder_at', 'paid_at')

    def validate_amount(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value


class InstallmentPlanSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField(read_only=True)
    student_system_id = serializers.CharField(source='student.student_id', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)
    items = InstallmentPlanItemSerializer(many=True, required=False)

    class Meta:
        model = InstallmentPlan
        fields = '__all__'
        read_only_fields = ('created_by', 'approved_by')

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"

    def validate_total_amount(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Total amount must be greater than zero.')
        return value

    def validate(self, attrs):
        data = super().validate(attrs)
        items = self.initial_data.get('items') if self.initial_data else None  # type: ignore[attr-defined]
        if isinstance(items, list) and items:
            total = Decimal('0.00')
            for item in items:
                amount = item.get('amount')
                try:
                    amount_d = Decimal(str(amount))
                except Exception:
                    raise serializers.ValidationError({'items': 'Each installment amount must be numeric.'})
                if amount_d <= 0:
                    raise serializers.ValidationError({'items': 'Each installment amount must be greater than zero.'})
                total += amount_d
            total_amount = data.get('total_amount')
            if total_amount is None and self.instance is not None:
                total_amount = self.instance.total_amount
            if total_amount is not None and total.quantize(Decimal('0.01')) != Decimal(str(total_amount)).quantize(Decimal('0.01')):
                raise serializers.ValidationError({'items': 'Installment amounts must add up to the plan total.'})
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        with transaction.atomic():
            plan = InstallmentPlan.objects.create(**validated_data)
            for idx, item in enumerate(items_data, start=1):
                InstallmentPlanItem.objects.create(
                    plan=plan,
                    label=item.get('label') or f'Installment {idx}',
                    due_date=item['due_date'],
                    amount=item['amount'],
                    notes=item.get('notes'),
                )
        return plan

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            if items_data is not None:
                instance.items.all().delete()
                for idx, item in enumerate(items_data, start=1):
                    InstallmentPlanItem.objects.create(
                        plan=instance,
                        label=item.get('label') or f'Installment {idx}',
                        due_date=item['due_date'],
                        amount=item['amount'],
                        notes=item.get('notes'),
                    )
        return instance


class FeePromiseSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField(read_only=True)
    student_system_id = serializers.CharField(source='student.student_id', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    installment_label = serializers.CharField(source='installment.label', read_only=True)

    class Meta:
        model = FeePromise
        fields = '__all__'
        read_only_fields = ('created_by', 'reminder_count', 'last_reminder_at', 'fulfilled_at')

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"

    def validate_amount(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Promise amount must be greater than zero.')
        return value


class FeeReminderLogSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField(read_only=True)
    student_system_id = serializers.CharField(source='student.student_id', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = FeeReminderLog
        fields = '__all__'

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"


class ResultsHoldLogSerializer(serializers.ModelSerializer):
    acted_by_username = serializers.CharField(source='acted_by.username', read_only=True)

    class Meta:
        model = ResultsHoldLog
        fields = '__all__'


class InvoiceSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField(read_only=True)
    student_system_id = serializers.CharField(source='student.student_id', read_only=True)

    class Meta:
        model = Invoice
        fields = '__all__'

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"


class InvoiceAdjustmentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField(read_only=True)
    student_system_id = serializers.CharField(source='student.student_id', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = InvoiceAdjustment
        fields = '__all__'

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"


class StudentGuardianLinkSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField(read_only=True)
    student_system_id = serializers.CharField(source='student.student_id', read_only=True)
    parent_username = serializers.CharField(source='parent_user.username', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = StudentGuardianLink
        fields = '__all__'

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"

class ClassChargeSerializer(serializers.ModelSerializer):
    school_class_level = serializers.CharField(source='school_class.level', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = ClassCharge
        fields = '__all__'


class EventSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Event
        fields = '__all__'


class SystemSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = '__all__'


class NotificationSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField(read_only=True)
    school_class_level = serializers.CharField(source='school_class.level', read_only=True)

    class Meta:
        model = Notification
        fields = '__all__'
        read_only_fields = ('user', 'created_at', 'read_at')

    def get_student_name(self, obj):
        try:
            return f"{obj.student.first_name} {obj.student.last_name}".strip()
        except Exception:
            return None


class AnnouncementSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Announcement
        fields = '__all__'


class DocumentDraftSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    school_class_level = serializers.CharField(source='school_class.level', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    printed_by_username = serializers.CharField(source='printed_by.username', read_only=True)
    approved_by_username = serializers.CharField(source='approved_by.username', read_only=True)
    published_by_username = serializers.CharField(source='published_by.username', read_only=True)
    previous_version_title = serializers.CharField(source='previous_version.title', read_only=True)

    class Meta:
        model = DocumentDraft
        fields = '__all__'
        read_only_fields = (
            'created_by',
            'submitted_at',
            'printed_at',
            'printed_by',
            'template_key',
            'version_number',
            'approved_at',
            'approved_by',
            'published_at',
            'published_by',
            'created_at',
            'updated_at',
        )

    def validate_body(self, value):
        cleaned = sanitize_rich_text_html(value)
        if not str(cleaned or '').strip():
            raise serializers.ValidationError('Body cannot be empty.')
        return cleaned


class CommunicationDeliverySerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField(read_only=True)
    campaign_title = serializers.CharField(source='campaign.document.title', read_only=True)
    campaign_status = serializers.CharField(source='campaign.status', read_only=True)

    class Meta:
        model = CommunicationDelivery
        fields = '__all__'
        read_only_fields = (
            'ack_token',
            'attempt_count',
            'last_attempt_at',
            'sent_at',
            'opened_at',
            'confirmed_at',
            'replied_at',
            'created_at',
            'updated_at',
        )

    def get_student_name(self, obj):
        try:
            return f"{obj.student.first_name} {obj.student.last_name}".strip()
        except Exception:
            return None


class CommunicationCampaignSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    document_title = serializers.CharField(source='document.title', read_only=True)
    school_class_level = serializers.CharField(source='school_class.level', read_only=True)
    student_name = serializers.SerializerMethodField(read_only=True)
    deliveries = CommunicationDeliverySerializer(many=True, read_only=True)

    class Meta:
        model = CommunicationCampaign
        fields = '__all__'
        read_only_fields = (
            'created_by',
            'sent_count',
            'failed_count',
            'skipped_count',
            'started_at',
            'last_run_at',
            'finished_at',
            'created_at',
            'updated_at',
        )

    def get_student_name(self, obj):
        try:
            if obj.student:
                return f"{obj.student.first_name} {obj.student.last_name}".strip()
        except Exception:
            pass
        return None
