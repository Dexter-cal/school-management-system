# pyright: reportMissingImports=false, reportUndefinedVariable=false, reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportOperatorIssue=false, reportIndexIssue=false, reportOptionalMemberAccess=false, reportOptionalCall=false, reportOptionalIterable=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportTypedDictNotRequiredAccess=false, reportUntypedFunctionDecorator=false, reportUntypedClassDecorator=false, reportUntypedBaseClass=false, reportUntypedNamedTuple=false, reportPrivateUsage=false, reportConstantRedefinition=false, reportIncompatibleMethodOverride=false, reportIncompatibleVariableOverride=false, reportInconsistentConstructor=false, reportOverlappingOverload=false, reportMissingSuperCall=false, reportUninitializedInstanceVariable=false, reportInvalidStringEscapeSequence=false, reportUnknownParameterType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUntypedNamedTuple=false, reportMissingParameterType=false, reportMissingTypeArgument=false, reportInvalidTypeVarUse=false, reportCallInDefaultInitializer=false, reportUnnecessaryIsInstance=false, reportUnnecessaryCast=false, reportUnnecessaryComparison=false, reportAssertAlwaysTrue=false, reportSelfClsParameterName=false, reportImplicitStringConcatenation=false, reportUnboundVariable=false, reportFunctionMemberAccess=false, reportUnusedCoroutine=false
"""Tests for school app models, views, and serializers."""
# pylint: disable=all
# type: ignore[attr-defined]  # DRF test client response typing incomplete
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import Client
from django.test import override_settings
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APITestCase, APIClient

from .models import (
    APICredential,
    APICredentialHealthLog,
    AcademicTerm,
    Attendance,
    CashbookClose,
    DepositBatch,
    DocumentDraft,
    Expense,
    ExpenseCategory,
    Event,
    FeePromise,
    FeeReminderLog,
    Invoice,
    InvoiceAdjustment,
    InstallmentPlan,
    Mark,
    OTP,
    Payment,
    PrintQueueItem,
    ResultsHoldLog,
    SchoolClass,
    Student,
    StudentGuardianLink,
    SystemSetting,
    Timetable,
    Notification,
    UserProfile,
)


@override_settings(
    DEBUG=True,
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class BaseSchoolTestCase(APITestCase):
    client: APIClient  # type: ignore[override]

    def _request(self, method, *args: Any, **kwargs: Any) -> Response:
        """Helper to cast client method returns to Response type for type safety."""
        return cast(Response, getattr(self.client, method)(*args, **kwargs))

    def create_user(self, username, password, role, **profile_kwargs):
        user_kwargs = {}
        email = profile_kwargs.pop('email', f'{username}@example.com')
        for field in ('is_staff', 'is_superuser', 'is_active'):
            if field in profile_kwargs:
                user_kwargs[field] = profile_kwargs.pop(field)
        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=profile_kwargs.pop('first_name', username.title()),
            last_name=profile_kwargs.pop('last_name', role.title()),
            email=email,
            **user_kwargs,
        )
        UserProfile.objects.create(user=user, role=role, **profile_kwargs)
        return user

    def create_student(self, *, student_id, first_name, last_name, school_class, section='A', parent_name='Parent User', parent_phone='0700000000'):
        return Student.objects.create(
            student_id=student_id,
            first_name=first_name,
            last_name=last_name,
            gender='Female',
            current_class=school_class,
            section=section,
            parent_name=parent_name,
            parent_relationship='Mother',
            parent_phone=parent_phone,
        )


class AuthSecurityTests(BaseSchoolTestCase):
    def setUp(self):
        self.password = 'StrongPass123!'
        self.user = self.create_user(
            username='secureadmin',
            password=self.password,
            role='admin',
            phone_number='0701000001',
            email_address='secureadmin@example.com',
        )

    def test_login_requires_csrf_and_still_works_with_valid_token(self):
        csrf_client = Client(enforce_csrf_checks=True)

        missing_csrf = csrf_client.post(
            '/api/auth/login/',
            data=json.dumps({'identifier': self.user.username, 'password': self.password}),
            content_type='application/json',
        )
        self.assertEqual(missing_csrf.status_code, 403)

        csrf_seed = csrf_client.get('/api/auth/csrf/')
        self.assertEqual(csrf_seed.status_code, 200)
        token = csrf_seed.json()['csrfToken']

        ok = csrf_client.post(
            '/api/auth/login/',
            data=json.dumps({'identifier': self.user.username, 'password': self.password}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()['status'], 'logged in')

    def test_password_reset_request_is_generic_for_unknown_identifier(self):
        response = self.client.post(
            '/api/auth/request-password-reset/',
            {'identifier': 'missing-user@example.com'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('If an account exists', response.data['detail'])

    def test_password_reset_rejects_weak_new_password(self):
        OTP.objects.create(
            user=self.user,
            code='123456',
            purpose='password_reset',
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        response = self.client.post(
            '/api/auth/confirm-password-reset/',
            {
                'identifier': self.user.profile.phone_number if hasattr(self.user, 'profile') else self.user.email,  # type: ignore[attr-defined]
                'otp_code': '123456',
                'new_password': '12345678',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Password does not meet security requirements.', response.data['detail'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))


class APICredentialVerificationTests(BaseSchoolTestCase):
    def setUp(self):
        self.superadmin = self.create_user(
            username='superverify',
            password='SuperVerify123!',
            role='superadmin',
            phone_number='0701555000',
            email_address='superverify@example.com',
        )

    @patch('school.views.requests.post')
    def test_mtn_momo_verify_uses_token_endpoint(self, mock_post):
        response_mock = Mock()
        response_mock.status_code = 200
        response_mock.json.return_value = {
            'access_token': 'mtn-token',
            'token_type': 'Bearer',
            'expires_in': 3600,
        }
        response_mock.text = '{"access_token":"mtn-token"}'
        mock_post.return_value = response_mock

        cred = APICredential.objects.create(
            service_name='mtn_momo',
            client_id='demo-api-user',
            client_secret='demo-api-secret',
            api_key='demo-subscription-key',
            extra_data={
                'environment': 'sandbox',
                'product': 'collection',
            },
        )

        self.client.force_authenticate(user=self.superadmin)
        response = self.client.post(f'/api/api-credentials/{cred.pk}/verify/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ok'])
        self.assertTrue(response.data['extra']['has_access_token'])
        self.assertTrue(APICredentialHealthLog.objects.filter(credential=cred, service_name='mtn_momo', is_ok=True).exists())
        mock_post.assert_called_once()
        called_url = mock_post.call_args.args[0]
        called_headers = mock_post.call_args.kwargs['headers']
        self.assertEqual(called_url, 'https://sandbox.momodeveloper.mtn.com/collection/token/')
        self.assertEqual(called_headers['Ocp-Apim-Subscription-Key'], 'demo-subscription-key')
        self.assertEqual(called_headers['X-Target-Environment'], 'sandbox')
        self.assertTrue(called_headers['Authorization'].startswith('Basic '))

    @patch('school.views.requests.post')
    def test_airtel_money_verify_uses_configured_token_url(self, mock_post):
        response_mock = Mock()
        response_mock.status_code = 200
        response_mock.json.return_value = {
            'access_token': 'airtel-token',
            'expires_in': 1200,
        }
        response_mock.text = '{"access_token":"airtel-token"}'
        mock_post.return_value = response_mock

        cred = APICredential.objects.create(
            service_name='airtel_money',
            client_id='airtel-client-id',
            client_secret='airtel-client-secret',
            api_key='merchant-extra-key',
            extra_data={
                'environment': 'sandbox',
                'token_url': 'https://openapiuat.airtel.africa/auth/oauth2/token',
                'auth_style': 'body',
                'payload_format': 'json',
                'country': 'UG',
                'currency': 'UGX',
            },
        )

        self.client.force_authenticate(user=self.superadmin)
        response = self.client.post(f'/api/api-credentials/{cred.pk}/verify/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ok'])
        self.assertTrue(response.data['extra']['has_access_token'])
        self.assertTrue(APICredentialHealthLog.objects.filter(credential=cred, service_name='airtel_money', is_ok=True).exists())
        mock_post.assert_called_once()
        called_url = mock_post.call_args.args[0]
        called_headers = mock_post.call_args.kwargs['headers']
        called_json = mock_post.call_args.kwargs['json']
        self.assertEqual(called_url, 'https://openapiuat.airtel.africa/auth/oauth2/token')
        self.assertEqual(called_headers['X-Country'], 'UG')
        self.assertEqual(called_headers['X-Currency'], 'UGX')
        self.assertEqual(called_json['grant_type'], 'client_credentials')
        self.assertEqual(called_json['client_id'], 'airtel-client-id')
        self.assertEqual(called_json['client_secret'], 'airtel-client-secret')

    def test_gmail_credential_rejects_invalid_sender_address(self):
        self.client.force_authenticate(user=self.superadmin)
        response = self.client.post(
            '/api/api-credentials/',
            {
                'service_name': 'gmail_smtp',
                'client_secret': 'short-secret',
                'extra_data': {'username': 'not-an-email'},
                'is_active': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('extra_data', response.data)

    @patch('smtplib.SMTP')
    def test_gmail_smtp_verify_attempts_live_login(self, mock_smtp):
        cred = APICredential.objects.create(
            service_name='gmail_smtp',
            client_secret='abcdefghijklmnop',
            extra_data={'username': 'school@example.com'},
            is_active=True,
        )

        self.client.force_authenticate(user=self.superadmin)
        response = self.client.post(f'/api/api-credentials/{cred.pk}/verify/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ok'])
        smtp = mock_smtp.return_value.__enter__.return_value
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with('school@example.com', 'abcdefghijklmnop')


class DashboardSummaryTests(BaseSchoolTestCase):
    def setUp(self):
        self.bursar = self.create_user(
            username='dashbursar',
            password='DashBursar123!',
            role='bursar',
            phone_number='0701777000',
            email_address='dashbursar@example.com',
        )

    def test_credential_health_summary_returns_safe_statuses_for_finance_staff(self):
        APICredential.objects.create(
            service_name='gmail_smtp',
            client_secret='gmail-app-password',
            extra_data={'username': 'school@example.com'},
            is_active=True,
            last_verify_ok=True,
            last_verify_detail='SMTP login succeeded.',
        )
        APICredential.objects.create(
            service_name='mtn_momo',
            client_id='mtn-user',
            client_secret='mtn-secret',
            api_key='mtn-key',
            is_active=True,
            last_verify_ok=False,
            last_verify_detail='401 unauthorized',
        )
        APICredentialHealthLog.objects.create(
            service_name='mtn_momo',
            is_ok=False,
            detail='401 unauthorized',
            verified_by=self.bursar,
        )
        APICredential.objects.create(
            service_name='megasms',
            api_key='sms-key',
            extra_data={'url': 'https://sms.example.com', 'sender': 'BJS'},
            is_active=False,
        )

        self.client.force_authenticate(user=self.bursar)
        response = self.client.get('/api/api-credentials/health/')

        self.assertEqual(response.status_code, 200)
        providers = {item['code']: item for item in response.data['providers']}
        self.assertEqual(providers['gmail']['status'], 'healthy')
        self.assertEqual(providers['mtn']['status'], 'failing')
        self.assertEqual(providers['airtel']['status'], 'missing')
        self.assertEqual(providers['sms']['status'], 'inactive')
        self.assertEqual(providers['mtn']['last_failure_detail'], '401 unauthorized')
        self.assertNotIn('client_secret', providers['gmail'])
        self.assertIn('notifications', response.data)
        self.assertEqual(response.data['recent_failures'][0]['service_name'], 'mtn_momo')


class StaffCredentialDeliveryTests(BaseSchoolTestCase):
    def setUp(self):
        self.superadmin = self.create_user(
            username='staffsuper',
            password='StaffSuper123!',
            role='superadmin',
            phone_number='0701666000',
            email_address='staffsuper@example.com',
        )
        self.bursar = self.create_user(
            username='staffbursar',
            password='StaffBursar123!',
            role='bursar',
            phone_number='0701666009',
            email_address='staffbursar@example.com',
        )
        self.client.force_authenticate(user=self.superadmin)

    def test_staff_user_create_rejects_weak_manual_password(self):
        response = self.client.post(
            '/api/users/',
            {
                'username': 'weakstaff',
                'role': 'admin',
                'first_name': 'Weak',
                'last_name': 'Staff',
                'phone_number': '0701666001',
                'email_address': 'weakstaff@example.com',
                'password_mode': 'manual',
                'password': '12345678',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Password does not meet security requirements.', response.data['detail'])

    @patch('school.views.send_sms', return_value=True)
    @patch('school.views.send_email', return_value=True)
    def test_staff_user_create_returns_credentials_delivery_and_print(self, mock_send_email, mock_send_sms):
        response = self.client.post(
            '/api/users/',
            {
                'username': 'rosebursar',
                'role': 'bursar',
                'first_name': 'Rose',
                'last_name': 'Namutebi',
                'phone_number': '0701666002',
                'email_address': 'rose.bursar@example.com',
                'password_mode': 'manual',
                'password': 'RoseTemp123!',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['credentials']['username'], 'rosebursar')
        self.assertEqual(response.data['credentials']['email_address'], 'rose.bursar@example.com')
        self.assertTrue(response.data['delivery']['email_sent'])
        self.assertTrue(response.data['delivery']['sms_sent'])
        self.assertTrue(response.data['delivery']['email_attempted'])
        self.assertTrue(response.data['delivery']['sms_attempted'])
        mock_send_email.assert_called_once()
        mock_send_sms.assert_called_once()
        created_user = User.objects.get(username='rosebursar')
        self.assertTrue(Notification.objects.filter(user=self.superadmin, event_key=f'user_created:{created_user.id}').exists())
        self.assertTrue(Notification.objects.filter(user=created_user, event_key=f'user_account_ready:{created_user.id}').exists())

        print_path = response.data['handover']['print_credentials_url']
        pdf_response = self.client.get(print_path)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')

    def test_staff_user_create_auto_generates_readable_username_when_blank(self):
        response = self.client.post(
            '/api/users/',
            {
                'role': 'admin',
                'first_name': 'Grace',
                'last_name': 'Nabwire',
                'phone_number': '0701666012',
                'email_address': 'grace.nabwire@example.com',
                'password_mode': 'auto',
                'auto_password': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['credentials']['username'], 'grace.nabwire')

    def test_notification_filter_by_student_and_class_for_finance_alerts(self):
        school_class = SchoolClass.objects.create(
            level='P.3',
            sections=['A'],
            annual_fee=Decimal('350000.00'),
            max_students_per_section=40,
        )
        other_class = SchoolClass.objects.create(
            level='P.6',
            sections=['A'],
            annual_fee=Decimal('400000.00'),
            max_students_per_section=40,
        )
        student = self.create_student(
            student_id='BJS-2026-0401',
            first_name='Martha',
            last_name='Achieng',
            school_class=school_class,
        )
        other_student = self.create_student(
            student_id='BJS-2026-0402',
            first_name='Paul',
            last_name='Okello',
            school_class=other_class,
        )
        Notification.objects.create(
            user=self.bursar,
            category='finance',
            title='Payment pending approval',
            message='Martha bank slip pending.',
            student=student,
            school_class=school_class,
        )
        Notification.objects.create(
            user=self.bursar,
            category='finance',
            title='Fee promise missed',
            message='Paul missed his promise.',
            student=other_student,
            school_class=other_class,
        )

        self.client.force_authenticate(user=self.bursar)
        response = self.client.get('/api/notifications/', {'category': 'finance', 'class_id': school_class.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['student'], student.pk)

        response = self.client.get('/api/notifications/', {'category': 'finance', 'q': 'Paul'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['student'], other_student.pk)


class DjangoAdminTests(BaseSchoolTestCase):
    def setUp(self):
        self.staff_superadmin = self.create_user(
            username='staffsuper',
            password='StaffSuper123!',
            role='superadmin',
            phone_number='0701666000',
            email_address='staffsuper@example.com',
            is_staff=True,
        )
        self.staff_admin = self.create_user(
            username='staffadmin',
            password='StaffAdmin123!',
            role='admin',
            phone_number='0701666001',
            email_address='staffadmin@example.com',
            is_staff=True,
        )
        APICredential.objects.create(
            service_name='gmail_smtp',
            client_id='school@example.com',
            is_active=True,
        )

    def test_admin_index_loads_for_staff_superadmin(self):
        client = Client()
        client.force_login(self.staff_superadmin)
        response = client.get('/admin/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bitende Junior School Admin')

    def test_api_credential_admin_is_available_to_role_superadmin(self):
        client = Client()
        client.force_login(self.staff_superadmin)
        response = client.get('/admin/school/apicredential/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gmail SMTP (App Password)')

    def test_api_credential_admin_is_blocked_for_regular_admin(self):
        client = Client()
        client.force_login(self.staff_admin)
        response = client.get('/admin/school/apicredential/')
        self.assertEqual(response.status_code, 403)


class FinanceWorkflowTests(BaseSchoolTestCase):
    def setUp(self):
        self.school_class = SchoolClass.objects.create(
            level='P.5',
            sections=['A', 'B'],
            annual_fee=Decimal('900000.00'),
            max_students_per_section=40,
        )
        self.active_term = AcademicTerm.objects.create(
            academic_year=2026,
            term_number=1,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=90),
            is_archived=False,
        )
        self.bursar = self.create_user(
            username='bursar1',
            password='BursarPass123!',
            role='bursar',
            phone_number='0702000001',
            email_address='bursar@example.com',
        )
        self.admin = self.create_user(
            username='admin1',
            password='AdminPass123!',
            role='admin',
            phone_number='0702000002',
            email_address='admin@example.com',
        )
        self.parent_user = self.create_user(
            username='parent1',
            password='ParentPass123!',
            role='parent',
            phone_number='0702111222',
            email_address='parent@example.com',
        )
        self.student = self.create_student(
            student_id='BJS-2026-0001',
            first_name='Aisha',
            last_name='Nakato',
            school_class=self.school_class,
            parent_name='Mary Nakato',
            parent_phone='0702999999',
        )
        StudentGuardianLink.objects.create(
            parent_user=self.parent_user,
            student=self.student,
            relationship='mother',
            is_active=True,
            created_by=self.admin,
        )
        self.student_user = self.create_user(
            username=self.student.student_id,
            password='StudentPass123!',
            role='student',
            phone_number='0702333444',
            email_address='student.portal@example.com',
            first_name=self.student.first_name,
            last_name=self.student.last_name,
        )
        self.other_student = self.create_student(
            student_id='BJS-2026-0002',
            first_name='Brian',
            last_name='Mugisha',
            school_class=self.school_class,
            parent_name='John Mugisha',
            parent_phone='0702555666',
        )
        self.bank_payment = Payment.objects.create(
            student=self.student,
            amount=Decimal('50000.00'),
            method='bank',
            status='pending',
            reference='BANK-001',
            submitted_by=self.parent_user,
            receipt_image_url='https://example.com/slip.png',
            academic_year=2026,
            term_number=1,
        )
        self.invoice = Invoice.objects.create(
            student=self.student,
            academic_year=2026,
            term_number=1,
            amount_due=Decimal('300000.00'),
            amount_paid=Decimal('0.00'),
            status='unpaid',
        )

    def test_only_bursar_or_superadmin_can_approve_bank_slips(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/payments/{self.bank_payment.pk}/approve/', {}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_submitted_bank_slip_method_cannot_be_changed(self):
        self.client.force_authenticate(user=self.bursar)
        response = self.client.patch(
            f'/api/payments/{self.bank_payment.pk}/',
            {'method': 'cash', 'amount': '50000.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('method', response.data)
        self.bank_payment.refresh_from_db()
        self.assertEqual(self.bank_payment.method, 'bank')

    def test_parent_can_submit_bank_slip_for_explicitly_linked_student(self):
        self.client.force_authenticate(user=self.parent_user)
        response = self.client.post(
            '/api/payment-submissions/bank-slip/',
            {
                'student': self.student.pk,
                'amount': '75000.00',
                'academic_year': 2026,
                'term_number': 1,
                'receipt_image_url': 'https://example.com/new-slip.png',
                'reference': 'BANK-002',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['student'], self.student.pk)

    def test_student_cannot_submit_bank_slip_for_another_student(self):
        self.client.force_authenticate(user=self.student_user)
        response = self.client.post(
            '/api/payment-submissions/bank-slip/',
            {
                'student': self.other_student.pk,
                'amount': '10000.00',
                'academic_year': 2026,
                'term_number': 1,
                'receipt_image_url': 'https://example.com/not-allowed.png',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_student_search_filters_by_query_and_class_level(self):
        self.client.force_authenticate(user=self.bursar)
        response = self.client.get('/api/students/', {'q': 'Aisha', 'class_level': 'P.5'})
        self.assertEqual(response.status_code, 200)
        ids = [item['student_id'] for item in response.data]
        self.assertEqual(ids, ['BJS-2026-0001'])

    def test_cashbook_close_saves_reconciliation_snapshot(self):
        ExpenseCategory.objects.create(name='Utilities', is_active=True)
        category = ExpenseCategory.objects.get(name='Utilities')
        Payment.objects.create(
            student=self.student,
            amount=Decimal('120000.00'),
            method='cash',
            status='received',
            academic_year=2026,
            term_number=1,
            received_by=self.bursar,
            approved_by=self.bursar,
        )
        Payment.objects.create(
            student=self.student,
            amount=Decimal('50000.00'),
            method='bank',
            status='approved',
            academic_year=2026,
            term_number=1,
            received_by=self.bursar,
            approved_by=self.bursar,
        )
        Expense.objects.create(
            category=category,
            expense_date=timezone.localdate(),
            amount=Decimal('20000.00'),
            status='approved',
            created_by=self.bursar,
            approved_by=self.bursar,
        )

        self.client.force_authenticate(user=self.bursar)
        response = self.client.post(
            '/api/cashbook-closes/',
            {
                'close_date': timezone.localdate().isoformat(),
                'cashier': self.bursar.pk,
                'opening_cash': '10000.00',
                'counted_cash_on_hand': '110000.00',
                'notes': 'Till balanced after petty cash payout.',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['cash_received_total'], '120000.00')
        self.assertEqual(response.data['approved_expense_total'], '20000.00')
        self.assertEqual(response.data['expected_cash_on_hand'], '110000.00')
        self.assertEqual(response.data['variance_amount'], '0.00')
        self.assertEqual(response.data['deposit_batch_total'], '0.00')

    def test_installment_plan_auto_allocates_paid_amounts(self):
        self.client.force_authenticate(user=self.bursar)
        response = self.client.post(
            '/api/installment-plans/',
            {
                'student': self.student.pk,
                'academic_year': 2026,
                'term_number': 1,
                'title': 'Parent payment plan',
                'total_amount': '120000.00',
                'start_date': timezone.localdate().isoformat(),
                'items': [
                    {'label': 'First', 'due_date': timezone.localdate().isoformat(), 'amount': '50000.00'},
                    {'label': 'Second', 'due_date': (timezone.localdate() + timedelta(days=30)).isoformat(), 'amount': '70000.00'},
                ],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        plan_id = response.data['id']

        pay = self.client.post(
            '/api/payments/',
            {
                'student': self.student.pk,
                'amount': '50000.00',
                'academic_year': 2026,
                'term_number': 1,
                'method': 'cash',
                'reference': 'CASH-PLAN-1',
            },
            format='json',
        )
        self.assertEqual(pay.status_code, 201)

        fetch = self.client.get(f'/api/installment-plans/{plan_id}/')
        self.assertEqual(fetch.status_code, 200)
        items = fetch.data['items']
        self.assertEqual(items[0]['status'], 'paid')
        self.assertEqual(items[0]['amount_paid'], '50000.00')
        self.assertEqual(items[1]['status'], 'pending')
        self.assertEqual(items[1]['amount_paid'], '0.00')

    def test_finance_timeline_combines_commitments_and_holds(self):
        plan = InstallmentPlan.objects.create(
            student=self.student,
            invoice=self.invoice,
            academic_year=2026,
            term_number=1,
            title='Timeline plan',
            total_amount=Decimal('90000.00'),
            created_by=self.bursar,
        )
        promise = FeePromise.objects.create(
            student=self.student,
            academic_year=2026,
            term_number=1,
            promised_for=timezone.localdate() + timedelta(days=7),
            amount=Decimal('30000.00'),
            created_by=self.bursar,
        )
        FeeReminderLog.objects.create(
            student=self.student,
            invoice=self.invoice,
            plan=plan,
            promise=promise,
            academic_year=2026,
            term_number=1,
            channel='sms',
            status='sent',
            recipient='0702999999',
            message='Reminder message',
            created_by=self.bursar,
        )
        InvoiceAdjustment.objects.create(
            student=self.student,
            academic_year=2026,
            term_number=1,
            kind='discount',
            title='Scholarship',
            amount=Decimal('-5000.00'),
            created_by=self.bursar,
        )
        ResultsHoldLog.objects.create(
            invoice=self.invoice,
            action='held',
            reason='Outstanding balance',
            source='manual',
            acted_by=self.bursar,
            acted_at=timezone.now(),
        )
        Payment.objects.create(
            student=self.student,
            amount=Decimal('25000.00'),
            method='cash',
            status='received',
            academic_year=2026,
            term_number=1,
            received_by=self.bursar,
            approved_by=self.bursar,
        )

        self.client.force_authenticate(user=self.bursar)
        response = self.client.get(f'/api/students/{self.student.pk}/finance-timeline/')
        self.assertEqual(response.status_code, 200)
        kinds = {item['kind'] for item in response.data['timeline']}
        self.assertIn('invoice', kinds)
        self.assertIn('payment', kinds)
        self.assertIn('adjustment', kinds)
        self.assertIn('fee_promise', kinds)
        self.assertIn('reminder', kinds)
        self.assertIn('results_hold', kinds)

    def test_cashbook_handover_summary_includes_prior_close_deposits_and_promises(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        prior_close = CashbookClose.objects.create(
            close_date=yesterday,
            cashier=self.bursar,
            status='closed',
            opening_cash=Decimal('10000.00'),
            counted_cash_on_hand=Decimal('90000.00'),
            variance_amount=Decimal('5000.00'),
            closed_by=self.admin,
            notes='Carry forward petty cash envelope.',
        )
        batch = DepositBatch.objects.create(
            name='Banking Pending',
            deposit_date=timezone.localdate(),
            reference='DEP-001',
            is_posted=False,
            created_by=self.bursar,
        )
        Payment.objects.create(
            student=self.student,
            amount=Decimal('65000.00'),
            method='bank',
            status='approved',
            academic_year=2026,
            term_number=1,
            received_by=self.bursar,
            approved_by=self.bursar,
            deposit_batch=batch,
        )
        FeePromise.objects.create(
            student=self.student,
            academic_year=2026,
            term_number=1,
            promised_for=timezone.localdate(),
            amount=Decimal('40000.00'),
            status='open',
            created_by=self.bursar,
        )

        self.client.force_authenticate(user=self.bursar)
        response = self.client.get('/api/cashbook-closes/handover/', {
            'close_date': timezone.localdate().isoformat(),
            'cashier': self.bursar.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['opening_cash_suggestion'], '90000.00')
        self.assertEqual(response.data['pending_deposit_count'], 1)
        self.assertEqual(response.data['unresolved_promise_count'], 1)
        self.assertEqual(response.data['prior_close']['id'], prior_close.pk)
        self.assertEqual(response.data['prior_close']['variance_amount'], '5000.00')

    def test_cashbook_handover_creates_single_alert_notification_after_cutoff(self):
        SystemSetting.objects.update_or_create(key='cashier_handover_alert_enabled', defaults={'value': True})
        SystemSetting.objects.update_or_create(key='cashier_handover_alert_time', defaults={'value': '00:00'})
        batch = DepositBatch.objects.create(
            name='Late Banking',
            deposit_date=timezone.localdate(),
            reference='DEP-ALERT',
            is_posted=False,
            created_by=self.bursar,
        )
        Payment.objects.create(
            student=self.student,
            amount=Decimal('25000.00'),
            method='bank',
            status='approved',
            academic_year=2026,
            term_number=1,
            received_by=self.bursar,
            approved_by=self.bursar,
            deposit_batch=batch,
        )

        self.client.force_authenticate(user=self.bursar)
        for _ in range(2):
            response = self.client.get('/api/cashbook-closes/handover/', {
                'close_date': timezone.localdate().isoformat(),
                'cashier': self.bursar.pk,
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data['handover_alert_due'])

        notices = Notification.objects.filter(user=self.bursar, event_key__startswith='cashier_handover:')
        self.assertEqual(notices.count(), 1)
        self.assertEqual(notices.first().category, 'finance')

    def test_parent_fee_view_carries_credit_from_previous_year(self):
        self.invoice.amount_due = Decimal('300000.00')
        self.invoice.amount_paid = Decimal('300000.00')
        self.invoice.status = 'paid'
        self.invoice.save(update_fields=['amount_due', 'amount_paid', 'status'])
        Payment.objects.create(
            student=self.student,
            amount=Decimal('300000.00'),
            method='cash',
            status='received',
            academic_year=2026,
            term_number=1,
            received_by=self.bursar,
            approved_by=self.bursar,
        )
        self.active_term.is_archived = True
        self.active_term.save(update_fields=['is_archived'])
        AcademicTerm.objects.create(
            academic_year=2026,
            term_number=3,
            start_date=timezone.localdate() - timedelta(days=200),
            end_date=timezone.localdate() - timedelta(days=120),
            is_archived=True,
        )
        AcademicTerm.objects.create(
            academic_year=2027,
            term_number=1,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=90),
            is_archived=False,
        )
        Invoice.objects.create(
            student=self.student,
            academic_year=2026,
            term_number=3,
            amount_due=Decimal('300000.00'),
            amount_paid=Decimal('500000.00'),
            status='paid',
        )
        Payment.objects.create(
            student=self.student,
            amount=Decimal('500000.00'),
            method='cash',
            status='received',
            academic_year=2026,
            term_number=3,
            received_by=self.bursar,
            approved_by=self.bursar,
        )
        Invoice.objects.create(
            student=self.student,
            academic_year=2027,
            term_number=1,
            amount_due=Decimal('300000.00'),
            amount_paid=Decimal('0.00'),
            status='unpaid',
        )

        self.client.force_authenticate(user=self.parent_user)
        response = self.client.get('/api/invoices/mine/')
        self.assertEqual(response.status_code, 200)
        entry = response.data['students'][0]
        self.assertEqual(entry['credit_brought_forward'], '200000.00')
        self.assertEqual(entry['paid'], '200000.00')
        self.assertEqual(entry['balance'], '100000.00')


class AcademicTermFlowTests(BaseSchoolTestCase):
    def setUp(self):
        self.admin = self.create_user(
            username='termadmin',
            password='TermAdmin123!',
            role='admin',
            phone_number='0705111000',
            email_address='termadmin@example.com',
        )
        self.school_class = SchoolClass.objects.create(
            level='P.4',
            sections=['A'],
            annual_fee=Decimal('600000.00'),
            max_students_per_section=40,
        )
        self.client.force_authenticate(user=self.admin)

    def test_start_new_term_creates_calendar_events_and_active_calendar(self):
        response = self.client.post(
            '/api/terms/start-new/',
            {
                'academic_year': 2026,
                'term_number': 2,
                'start_date': '2026-05-04',
                'end_date': '2026-07-31',
                'holiday_break_days': 14,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        term_id = response.data['term']['id']

        titles = set(Event.objects.values_list('title', flat=True))
        self.assertIn('Academic Term 2 2026 begins', titles)
        self.assertIn('Academic Term 2 2026 ends', titles)
        self.assertIn('Academic Term 2 2026 holiday break', titles)

        calendar_response = self.client.get('/api/terms/active-calendar/')
        self.assertEqual(calendar_response.status_code, 200)
        self.assertEqual(calendar_response.data['term']['id'], term_id)
        self.assertEqual(calendar_response.data['holiday_break']['days'], 14)
        self.assertGreater(calendar_response.data['weekend_count'], 0)
        self.assertTrue(any(ev['title'] == 'Academic Term 2 2026 begins' for ev in calendar_response.data['events']))

    def test_edit_term_updates_calendar_event_dates(self):
        term = AcademicTerm.objects.create(
            academic_year=2026,
            term_number=1,
            start_date=date(2026, 2, 2),
            end_date=date(2026, 4, 24),
            holiday_break_days=7,
            is_archived=False,
        )
        Event.objects.create(
            title='Academic Term 1 2026 begins',
            description='old',
            start_date=term.start_date,
            end_date=term.start_date,
            is_published=True,
        )
        Event.objects.create(
            title='Academic Term 1 2026 ends',
            description='old',
            start_date=term.end_date,
            end_date=term.end_date,
            is_published=True,
        )
        Event.objects.create(
            title='Academic Term 1 2026 holiday break',
            description='old',
            start_date=term.end_date + timedelta(days=1),
            end_date=term.end_date + timedelta(days=7),
            is_published=True,
        )

        response = self.client.patch(
            f'/api/terms/{term.pk}/edit/',
            {
                'start_date': '2026-02-09',
                'end_date': '2026-05-01',
                'holiday_break_days': 10,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        start_event = Event.objects.get(title='Academic Term 1 2026 begins')
        end_event = Event.objects.get(title='Academic Term 1 2026 ends')
        break_event = Event.objects.get(title='Academic Term 1 2026 holiday break')
        self.assertEqual(start_event.start_date.isoformat(), '2026-02-09')
        self.assertEqual(end_event.start_date.isoformat(), '2026-05-01')
        self.assertEqual(break_event.start_date.isoformat(), '2026-05-02')
        self.assertEqual(break_event.end_date.isoformat(), '2026-05-11')

        calendar_response = self.client.get(f'/api/terms/{term.pk}/calendar/')
        self.assertEqual(calendar_response.status_code, 200)
        self.assertEqual(calendar_response.data['holiday_break']['end_date'], '2026-05-11')

    def test_start_new_term_rejects_overlap(self):
        AcademicTerm.objects.create(
            academic_year=2026,
            term_number=1,
            start_date=date(2026, 1, 12),
            end_date=date(2026, 4, 10),
            holiday_break_days=0,
            is_archived=True,
        )

        response = self.client.post(
            '/api/terms/start-new/',
            {
                'academic_year': 2026,
                'term_number': 2,
                'start_date': '2026-04-01',
                'end_date': '2026-06-30',
                'holiday_break_days': 5,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('overlaps', response.data['detail'])

    def test_start_new_term_archives_existing_attendance_instead_of_deleting(self):
        active = AcademicTerm.objects.create(
            academic_year=2026,
            term_number=1,
            start_date=date(2026, 2, 2),
            end_date=date(2026, 4, 24),
            holiday_break_days=0,
            is_archived=False,
        )
        student = self.create_student(
            student_id='BJS-2026-ATT-1',
            first_name='Term',
            last_name='Archive',
            school_class=self.school_class,
        )
        att = Attendance.objects.create(
            student=student,
            date=date(2026, 4, 20),
            status='present',
            marked_by=self.admin,
        )

        response = self.client.post(
            '/api/terms/start-new/',
            {
                'academic_year': 2026,
                'term_number': 2,
                'start_date': '2026-05-05',
                'end_date': '2026-07-30',
                'holiday_break_days': 0,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        att.refresh_from_db()
        self.assertTrue(att.is_archived)
        self.assertEqual(att.academic_year, active.academic_year)
        self.assertEqual(att.term_number, active.term_number)

    def test_timetable_for_class_prefers_active_term_row(self):
        AcademicTerm.objects.create(
            academic_year=2026,
            term_number=2,
            start_date=date(2026, 5, 5),
            end_date=date(2026, 7, 30),
            holiday_break_days=0,
            is_archived=False,
        )
        Timetable.objects.create(
            school_class=self.school_class,
            section='A',
            slots={'monday': ['08:00']},
            cells={'monday_1': 'Legacy Math'},
        )
        Timetable.objects.create(
            school_class=self.school_class,
            section='A',
            academic_year=2026,
            term_number=2,
            slots={'monday': ['08:00']},
            cells={'monday_1': 'Term Science'},
        )

        response = self.client.get(f'/api/timetable/for-class/{self.school_class.pk}/A/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['academic_year'], 2026)
        self.assertEqual(response.data['term_number'], 2)
        self.assertEqual(response.data['cells']['monday_1'], 'Term Science')

    @patch('school.views.requests.get')
    def test_sync_public_holidays_creates_events(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {'date': '2026-06-09', 'localName': 'National Heroes Day', 'name': 'National Heroes Day'},
        ]
        mock_get.return_value = mock_response
        SystemSetting.objects.update_or_create(
            key='public_holiday_settings',
            defaults={'value': {'enabled': True, 'country_code': 'UG'}},
        )
        term = AcademicTerm.objects.create(
            academic_year=2026,
            term_number=2,
            start_date=date(2026, 5, 5),
            end_date=date(2026, 7, 30),
            holiday_break_days=0,
            is_archived=False,
        )

        response = self.client.post(f'/api/terms/{term.pk}/sync-public-holidays/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Event.objects.filter(title__icontains='National Heroes Day').exists())

    def test_event_create_rejects_dates_outside_term_window(self):
        AcademicTerm.objects.create(
            academic_year=2026,
            term_number=2,
            start_date=date(2026, 5, 5),
            end_date=date(2026, 7, 30),
            holiday_break_days=0,
            is_archived=False,
        )
        response = self.client.post(
            '/api/events/',
            {
                'title': 'Out of term event',
                'start_date': '2026-08-20',
                'end_date': '2026-08-20',
                'is_published': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_class_charge_defaults_to_active_term_and_rejects_due_date_outside_term(self):
        AcademicTerm.objects.create(
            academic_year=2026,
            term_number=2,
            start_date=date(2026, 5, 5),
            end_date=date(2026, 7, 30),
            holiday_break_days=0,
            is_archived=False,
        )
        bad = self.client.post(
            '/api/class-charges/',
            {
                'school_class': self.school_class.pk,
                'section': 'A',
                'title': 'Trip fee',
                'amount': '25000.00',
                'due_date': '2026-08-15',
                'is_published': True,
                'is_active': True,
            },
            format='json',
        )
        self.assertEqual(bad.status_code, 400)

        ok = self.client.post(
            '/api/class-charges/',
            {
                'school_class': self.school_class.pk,
                'section': 'A',
                'title': 'Workbook fee',
                'amount': '15000.00',
                'due_date': '2026-06-15',
                'is_published': True,
                'is_active': True,
            },
            format='json',
        )
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.data['academic_year'], 2026)
        self.assertEqual(ok.data['term_number'], 2)

    def test_attendance_rejects_date_outside_live_term(self):
        student = self.create_student(
            student_id='BJS-2026-ATT-2',
            first_name='Late',
            last_name='Entry',
            school_class=self.school_class,
        )
        AcademicTerm.objects.create(
            academic_year=2026,
            term_number=2,
            start_date=date(2026, 5, 5),
            end_date=date(2026, 7, 30),
            holiday_break_days=0,
            is_archived=False,
        )
        response = self.client.post(
            '/api/attendance/',
            {
                'student': student.pk,
                'date': '2026-08-22',
                'status': 'present',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_marks_bulk_upsert_rejects_non_active_term(self):
        student = self.create_student(
            student_id='BJS-2026-MARK-1',
            first_name='Mark',
            last_name='Window',
            school_class=self.school_class,
        )
        AcademicTerm.objects.create(
            academic_year=2026,
            term_number=2,
            start_date=date(2026, 5, 5),
            end_date=date(2026, 7, 30),
            holiday_break_days=0,
            is_archived=False,
        )
        response = self.client.post(
            '/api/marks/bulk-upsert/',
            {
                'year': 2026,
                'term': 1,
                'subject': 'Mathematics',
                'items': [{'student': student.pk, 'score': 78}],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class ResultsHoldHistoryTests(BaseSchoolTestCase):
    def setUp(self):
        self.school_class = SchoolClass.objects.create(
            level='P.6',
            sections=['A'],
            annual_fee=Decimal('960000.00'),
            max_students_per_section=40,
        )
        self.parent_user = self.create_user(
            username='parent-history',
            password='ParentPass123!',
            role='parent',
            phone_number='0703000001',
            email_address='history-parent@example.com',
        )
        self.student = self.create_student(
            student_id='BJS-2026-0100',
            first_name='Joyce',
            last_name='Nambi',
            school_class=self.school_class,
            section='A',
            parent_name='Mary Nambi',
            parent_phone='0703888999',
        )
        StudentGuardianLink.objects.create(
            parent_user=self.parent_user,
            student=self.student,
            relationship='guardian',
            is_active=True,
        )
        AcademicTerm.objects.create(
            academic_year=2026,
            term_number=2,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=90),
            is_archived=False,
        )
        Invoice.objects.create(
            student=self.student,
            academic_year=2026,
            term_number=2,
            amount_due=Decimal('120000.00'),
            amount_paid=Decimal('20000.00'),
            status='partial',
            results_blocked=True,
            results_block_reason='Outstanding balance',
        )
        Payment.objects.create(
            student=self.student,
            amount=Decimal('20000.00'),
            method='cash',
            status='received',
            academic_year=2026,
            term_number=2,
        )
        Mark.objects.create(student=self.student, subject='Mathematics', score=83, term=2, year=2026)
        Attendance.objects.create(student=self.student, date=timezone.localdate(), status='Present')

    def test_parent_history_hides_marks_when_results_are_blocked(self):
        self.client.force_authenticate(user=self.parent_user)
        response = self.client.get(f'/api/students/{self.student.pk}/history/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['results_blocked'])
        self.assertEqual(response.data['marks'], [])
        self.assertEqual(len(response.data['payments']), 1)
        self.assertEqual(len(response.data['attendance']), 1)


class RegistrationAndCommunicationTests(BaseSchoolTestCase):
    def setUp(self):
        self.school_class = SchoolClass.objects.create(
            level='P.2',
            sections=['A'],
            annual_fee=Decimal('500000.00'),
            max_students_per_section=40,
        )
        self.admin = self.create_user(
            username='regadmin',
            password='RegAdmin123!',
            role='admin',
            phone_number='0704000001',
            email_address='regadmin@example.com',
        )
        self.parent_user = self.create_user(
            username='0704555666',
            password='ParentDemo123!',
            role='parent',
            phone_number='0704555666',
            email_address='guardian@example.com',
            first_name='Mary',
            last_name='Guardian',
        )
        self.client.force_authenticate(user=self.admin)

    @patch('school.views.send_sms', return_value=True)
    @patch('school.views.send_email', return_value=True)
    def test_student_registration_returns_delivery_and_family_credentials_print(self, mock_send_email, mock_send_sms):
        response = self.client.post(
            '/api/students/',
            {
                'first_name': 'Aisha',
                'last_name': 'Nalugo',
                'gender': 'Female',
                'current_class': self.school_class.pk,
                'section': 'A',
                'parent_name': 'Mary Guardian',
                'parent_relationship': 'Mother',
                'parent_phone': '0704555666',
                'parent_email': 'guardian@example.com',
                'parent_password_mode': 'manual',
                'parent_password': 'ParentTemp123!',
                'student_password_mode': 'manual',
                'student_password': 'StudentTemp123!',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['credentials']['parent_email'], 'guardian@example.com')
        self.assertTrue(response.data['delivery']['email_sent'])
        self.assertTrue(response.data['delivery']['sms_sent'])
        mock_send_email.assert_called()
        mock_send_sms.assert_called()

        student_id = response.data['id']
        print_path = response.data['handover']['print_credentials_url']
        pdf_response = self.client.get(print_path)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        self.assertIn(f'/api/students/{student_id}/print-credentials/', print_path)
        self.assertTrue(Notification.objects.filter(user=self.admin, event_key=f'student_registered:{student_id}').exists())
        self.assertTrue(Notification.objects.filter(user=self.parent_user, event_key__startswith=f'parent_student_registered:{student_id}:').exists())

    @patch('school.views.send_email', return_value=True)
    def test_mail_merge_preview_queue_and_send(self, mock_send_email):
        student = self.create_student(
            student_id='BJS-2026-0201',
            first_name='Brian',
            last_name='Okello',
            school_class=self.school_class,
            parent_name='Mary Guardian',
            parent_phone='0704555666',
        )
        doc = DocumentDraft.objects.create(
            created_by=self.admin,
            kind='letter',
            title='Reminder for {student_name}',
            body='Dear {recipient_name}, please confirm registration for {student_name} in {class_label}.',
            school_class=self.school_class,
            status='draft',
        )

        preview = self.client.post(
            f'/api/document-drafts/{doc.pk}/preview-merge/',
            {'student': student.pk, 'audience': 'guardians'},
            format='json',
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data['count'], 1)
        self.assertIn('Brian Okello', preview.data['preview']['body'])

        queued = self.client.post(
            f'/api/document-drafts/{doc.pk}/queue-merge/',
            {'school_class': self.school_class.pk, 'audience': 'guardians'},
            format='json',
        )
        self.assertEqual(queued.status_code, 200)
        self.assertTrue(PrintQueueItem.objects.filter(kind='mail_merge_letter').exists())

        sent = self.client.post(
            f'/api/document-drafts/{doc.pk}/send-merge/',
            {'student': student.pk, 'audience': 'guardians', 'channel': 'email'},
            format='json',
        )
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.data['sent'], 1)
        mock_send_email.assert_called()

    def test_communication_html_is_sanitized_and_preview_contains_plain_and_html(self):
        student = self.create_student(
            student_id='BJS-2026-0202',
            first_name='Jovia',
            last_name='Nampiima',
            school_class=self.school_class,
            parent_name='Mary Guardian',
            parent_phone='0704555666',
        )
        payload = {
            'kind': 'letter',
            'title': 'Notice for {student_name}',
            'body': '<p onclick="alert(1)"><strong>Hello {student_name}</strong></p><script>alert(1)</script><p>Class {class_label}</p>',
            'school_class': self.school_class.pk,
            'status': 'draft',
        }
        create_resp = self.client.post('/api/document-drafts/', payload, format='json')
        self.assertEqual(create_resp.status_code, 201)
        doc_id = create_resp.data['id']

        doc = DocumentDraft.objects.get(pk=doc_id)
        self.assertIn('<strong>', doc.body)
        self.assertNotIn('<script', doc.body.lower())
        self.assertNotIn('onclick=', doc.body.lower())

        preview = self.client.post(
            f'/api/document-drafts/{doc.pk}/preview-merge/',
            {'student': student.pk, 'audience': 'guardians'},
            format='json',
        )
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.data['preview']['body_html'])
        self.assertTrue(preview.data['preview']['body_text'])
