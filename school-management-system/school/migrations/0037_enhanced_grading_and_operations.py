from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('school', '0036_rename_school_timet_academi_4e93b0_idx_school_time_academi_55d1e0_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='gradingscale',
            name='created_at',
            field=models.DateTimeField(default=django.utils.timezone.now, auto_now_add=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='gradingscale',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_grading_scales', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='gradingscale',
            name='description',
            field=models.TextField(blank=True, help_text='Description of this grading scale', null=True),
        ),
        migrations.AddField(
            model_name='gradingscale',
            name='is_template',
            field=models.BooleanField(default=False, help_text='Mark as True if this is a template for reuse'),
        ),
        migrations.AddField(
            model_name='gradingscale',
            name='template_type',
            field=models.CharField(choices=[('5grade', '5-Grade System (A, B, C, D, F)'), ('13grade', '13-Grade System (A+, A, A-, B+, ...)'), ('7point', '7-Point Scale'), ('custom', 'Custom')], default='custom', max_length=20),
        ),
        migrations.AddField(
            model_name='gradingscale',
            name='updated_at',
            field=models.DateTimeField(default=django.utils.timezone.now, auto_now=True),
            preserve_default=False,
        ),
        migrations.AddIndex(
            model_name='gradingscale',
            index=models.Index(fields=['template_type'], name='school_grad_template_68bb9b_idx'),
        ),
        migrations.AddIndex(
            model_name='gradingscale',
            index=models.Index(fields=['is_default'], name='school_grad_is_defa_9aa3e6_idx'),
        ),
        migrations.CreateModel(
            name='ExamType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('exam_type', models.CharField(choices=[('beginning', 'Beginning of Term'), ('midterm', 'Midterm'), ('endterm', 'End of Term'), ('other', 'Other')], max_length=20)),
                ('description', models.TextField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'indexes': [models.Index(fields=['is_active'], name='school_exam_is_acti_f5dc47_idx')],
                'unique_together': {('name', 'exam_type')},
            },
        ),
        migrations.AddField(
            model_name='mark',
            name='exam_type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='marks', to='school.examtype'),
        ),
        migrations.CreateModel(
            name='AcademicCalendarEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('exam', 'Exam'), ('visitation_day', 'Visitation Day (VD)'), ('payment_deadline', 'Payment Deadline'), ('holiday', 'Holiday'), ('school_closure', 'School Closure'), ('event', 'Event'), ('other', 'Other')], max_length=20)),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True, null=True)),
                ('event_date', models.DateField()),
                ('start_time', models.TimeField(blank=True, null=True)),
                ('end_time', models.TimeField(blank=True, null=True)),
                ('notify_parents', models.BooleanField(default=False)),
                ('notify_teachers', models.BooleanField(default=False)),
                ('notify_staff', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='calendar_events', to='school.academicterm')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_calendar_events', to=settings.AUTH_USER_MODEL)),
                ('exam_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='school.examtype')),
            ],
            options={
                'ordering': ['event_date', 'start_time'],
                'indexes': [
                    models.Index(fields=['academic_term', 'event_date'], name='school_acad_academi_f1a14c_idx'),
                    models.Index(fields=['event_type', 'event_date'], name='school_acad_event_t_905b96_idx'),
                ],
            },
        ),
        migrations.AddField(
            model_name='academicterm',
            name='assessment_config',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name='OtherStaff',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=100)),
                ('last_name', models.CharField(max_length=100)),
                ('role', models.CharField(choices=[('cook', 'Cook'), ('cleaner', 'Cleaner'), ('guard', 'Guard'), ('driver', 'Driver'), ('laborer', 'Laborer'), ('maintenance', 'Maintenance'), ('other', 'Other')], max_length=20)),
                ('phone_number', models.CharField(blank=True, max_length=20, null=True)),
                ('email', models.EmailField(blank=True, max_length=254, null=True)),
                ('base_salary', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(default='UGX', max_length=3)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_other_staff', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['first_name', 'last_name'],
            },
        ),
        migrations.CreateModel(
            name='StudentDebtRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('outstanding_amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('reason', models.CharField(default='Unpaid fees from previous term', max_length=200)),
                ('is_settled', models.BooleanField(default=False)),
                ('settled_date', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='school.academicterm')),
                ('settled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='settled_debts', to=settings.AUTH_USER_MODEL)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='debt_records', to='school.student')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['student', 'is_settled'], name='school_stud_student_596f37_idx'),
                    models.Index(fields=['academic_term', 'is_settled'], name='school_stud_academi_251a88_idx'),
                ],
                'unique_together': {('student', 'academic_term')},
            },
        ),
        migrations.CreateModel(
            name='TeacherAllowance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('allowance_type', models.CharField(choices=[('transport', 'Transport Allowance'), ('housing', 'Housing Allowance'), ('meal', 'Meal Allowance'), ('performance', 'Performance Bonus'), ('other', 'Other')], max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(default='UGX', max_length=3)),
                ('is_paid', models.BooleanField(default=False)),
                ('paid_date', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='school.academicterm')),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_allowances', to=settings.AUTH_USER_MODEL)),
                ('teacher', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='allowances', to='school.teacher')),
            ],
        ),
        migrations.CreateModel(
            name='TeacherSalary',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('base_salary', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(default='UGX', max_length=3)),
                ('payment_status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('paid', 'Paid'), ('partial', 'Partial Payment')], default='pending', max_length=20)),
                ('amount_paid', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12)),
                ('paid_date', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='school.academicterm')),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_teacher_salaries', to=settings.AUTH_USER_MODEL)),
                ('paid_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='paid_teacher_salaries', to=settings.AUTH_USER_MODEL)),
                ('teacher', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='salary_records', to='school.teacher')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['teacher', 'academic_term'], name='school_teac_teacher_7a4451_idx'),
                    models.Index(fields=['payment_status', 'paid_date'], name='school_teac_payment_52121d_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='TermInstallmentPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number_of_installments', models.IntegerField(choices=[(2, '2 Installments'), (3, '3 Installments')], default=2)),
                ('installments', models.JSONField(default=list, help_text='List of installments: [{"number": 1, "due_date": "YYYY-MM-DD", "percentage": 50}, ...]')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='installment_plan', to='school.academicterm')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_term_installment_plans', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='StaffPayroll',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gross_amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('deductions', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12)),
                ('net_amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(default='UGX', max_length=3)),
                ('payment_method', models.CharField(choices=[('cash', 'Cash'), ('bank_transfer', 'Bank Transfer'), ('mobile_money', 'Mobile Money'), ('check', 'Check')], default='cash', max_length=50)),
                ('payment_status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('paid', 'Paid')], default='pending', max_length=20)),
                ('paid_date', models.DateTimeField(blank=True, null=True)),
                ('reference_number', models.CharField(blank=True, max_length=100, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='school.academicterm')),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_payroll', to=settings.AUTH_USER_MODEL)),
                ('other_staff', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payroll_records', to='school.otherstaff')),
                ('paid_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='paid_payroll', to=settings.AUTH_USER_MODEL)),
                ('teacher', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payroll_records', to='school.teacher')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['academic_term', 'payment_status'], name='school_staf_academi_20dc8c_idx'),
                    models.Index(fields=['paid_date'], name='school_staf_paid_da_cad60d_idx'),
                ],
            },
        ),
    ]
