from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from school.models import (
    AcademicTerm,
    CashbookClose,
    DepositBatch,
    Expense,
    ExpenseCategory,
    FeePromise,
    FeeReminderLog,
    FeeStructure,
    InstallmentPlan,
    InstallmentPlanItem,
    Invoice,
    InvoiceAdjustment,
    Payment,
    ResultsHoldLog,
    SchoolClass,
    Student,
    StudentGuardianLink,
    UserProfile,
)


class Command(BaseCommand):
    help = "Seed safe demo finance data for bursar workflow testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Delete existing demo finance records before reseeding.",
        )

    def _ensure_user(self, *, username, password, role, first_name, last_name, email, phone, is_staff=False, is_superuser=False):
        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "email": email or "",
                "is_staff": is_staff,
                "is_superuser": is_superuser,
            },
        )
        user.first_name = first_name
        user.last_name = last_name
        user.email = email or ""
        user.is_staff = is_staff or is_superuser
        user.is_superuser = is_superuser
        user.set_password(password)
        user.save()
        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "role": role,
                "avatar": (first_name[:1] + last_name[:1]).upper(),
                "phone_number": phone,
                "email_address": email or None,
            },
        )
        return user

    def _purge_demo(self):
        demo_students = Student.objects.filter(student_id__startswith="DEMO-2026-")
        demo_ids = list(demo_students.values_list("id", flat=True))
        if demo_ids:
            CashbookClose.objects.filter(notes__icontains="[demo-seed]").delete()
            FeeReminderLog.objects.filter(student_id__in=demo_ids).delete()
            ResultsHoldLog.objects.filter(invoice__student_id__in=demo_ids, source="demo_seed").delete()
            InvoiceAdjustment.objects.filter(student_id__in=demo_ids).delete()
            Payment.objects.filter(student_id__in=demo_ids).delete()
            Invoice.objects.filter(student_id__in=demo_ids).delete()
            InstallmentPlan.objects.filter(student_id__in=demo_ids).delete()
            FeePromise.objects.filter(student_id__in=demo_ids).delete()
            StudentGuardianLink.objects.filter(student_id__in=demo_ids).delete()
            Student.objects.filter(id__in=demo_ids).delete()

        DepositBatch.objects.filter(reference__startswith="DEMO-DEP-").delete()
        Expense.objects.filter(vendor__startswith="DEMO ").delete()
        ExpenseCategory.objects.filter(name__startswith="Demo ").delete()
        get_user_model().objects.filter(username__in=["demo_bursar", "demo_parent_mary", "demo_parent_john", "demo_admin"]).delete()

    def _sync_invoice(self, invoice):
        paid_total = Payment.objects.filter(
            student=invoice.student,
            academic_year=invoice.academic_year,
            term_number=invoice.term_number,
            status__in=["received", "approved"],
        ).values_list("amount", flat=True)
        paid_total = sum((Decimal(str(v)) for v in paid_total), Decimal("0.00"))
        invoice.amount_paid = paid_total
        if paid_total <= Decimal("0.00"):
            invoice.status = "unpaid"
        elif paid_total < Decimal(str(invoice.amount_due or 0)):
            invoice.status = "partial"
        else:
            invoice.status = "paid"
        invoice.save(update_fields=["amount_paid", "status", "updated_at"])

    def handle(self, *args, **options):
        today = timezone.localdate()
        now = timezone.now()

        if options["purge"]:
            self._purge_demo()
            self.stdout.write("Removed prior demo finance records.")

        with transaction.atomic():
            admin_user = get_user_model().objects.filter(username="admin").first()
            if not admin_user:
                admin_user = self._ensure_user(
                    username="demo_admin",
                    password="DemoAdmin@2026",
                    role="superadmin",
                    first_name="Demo",
                    last_name="Admin",
                    email="demo.admin@bitende.local",
                    phone="+256700000900",
                    is_staff=True,
                    is_superuser=True,
                )

            bursar_user = self._ensure_user(
                username="demo_bursar",
                password="DemoBursar@2026",
                role="bursar",
                first_name="Rose",
                last_name="Namutebi",
                email="demo.bursar@bitende.local",
                phone="+256700000901",
                is_staff=True,
            )
            parent_mary = self._ensure_user(
                username="demo_parent_mary",
                password="DemoParent@2026",
                role="parent",
                first_name="Mary",
                last_name="Nakato",
                email="demo.parent.mary@bitende.local",
                phone="+256700000902",
            )
            parent_john = self._ensure_user(
                username="demo_parent_john",
                password="DemoParent@2026",
                role="parent",
                first_name="John",
                last_name="Ssemanda",
                email="demo.parent.john@bitende.local",
                phone="+256700000903",
            )

            active_term = AcademicTerm.objects.filter(is_archived=False).order_by("-academic_year", "-term_number").first()
            if active_term:
                year = int(active_term.academic_year)
                term = int(active_term.term_number)
            else:
                year = today.year
                term = 1
                active_term = AcademicTerm.objects.create(
                    academic_year=year,
                    term_number=term,
                    start_date=today - timedelta(days=45),
                    end_date=today + timedelta(days=45),
                    is_archived=False,
                    auto_generate_invoices_on_start=False,
                    sms_parents_on_start=False,
                    open_mark_entry_on_start=True,
                )

            class_specs = {
                "P.4": Decimal("380000.00"),
                "P.5": Decimal("420000.00"),
                "P.6": Decimal("450000.00"),
            }
            class_map = {}
            for level, annual_fee in class_specs.items():
                cls, _ = SchoolClass.objects.update_or_create(
                    level=level,
                    defaults={
                        "sections": ["A", "B"],
                        "annual_fee": annual_fee,
                        "max_students_per_section": 40,
                        "teacher_a": f"Demo {level} A",
                        "teacher_b": f"Demo {level} B",
                    },
                )
                class_map[level] = cls
                FeeStructure.objects.update_or_create(
                    school_class=cls,
                    year=year,
                    term=term,
                    defaults={"amount": annual_fee},
                )
            student_specs = [
                {
                    "student_id": "DEMO-2026-0001",
                    "first_name": "Aisha",
                    "last_name": "Nakato",
                    "gender": "Female",
                    "current_class": class_map["P.5"],
                    "section": "A",
                    "parent_name": "Mary Nakato",
                    "parent_relationship": "Mother",
                    "parent_phone": "+256700000902",
                    "parent_phone2": "+256700001002",
                    "district": "Kampala",
                    "religion": "Christian",
                    "home_address": "Demo Road, Kampala",
                },
                {
                    "student_id": "DEMO-2026-0002",
                    "first_name": "Brian",
                    "last_name": "Ssemanda",
                    "gender": "Male",
                    "current_class": class_map["P.5"],
                    "section": "B",
                    "parent_name": "John Ssemanda",
                    "parent_relationship": "Father",
                    "parent_phone": "+256700000903",
                    "parent_phone2": "+256700001003",
                    "district": "Wakiso",
                    "religion": "Christian",
                    "home_address": "Demo View, Wakiso",
                },
                {
                    "student_id": "DEMO-2026-0003",
                    "first_name": "Esther",
                    "last_name": "Nambooze",
                    "gender": "Female",
                    "current_class": class_map["P.4"],
                    "section": "A",
                    "parent_name": "Mary Nakato",
                    "parent_relationship": "Guardian",
                    "parent_phone": "+256700000902",
                    "parent_phone2": "",
                    "district": "Mukono",
                    "religion": "Muslim",
                    "home_address": "Demo Hill, Mukono",
                },
                {
                    "student_id": "DEMO-2026-0004",
                    "first_name": "Joel",
                    "last_name": "Okello",
                    "gender": "Male",
                    "current_class": class_map["P.6"],
                    "section": "A",
                    "parent_name": "John Ssemanda",
                    "parent_relationship": "Guardian",
                    "parent_phone": "+256700000903",
                    "parent_phone2": "",
                    "district": "Jinja",
                    "religion": "Christian",
                    "home_address": "Demo Lane, Jinja",
                },
            ]

            students = {}
            for spec in student_specs:
                student, _ = Student.objects.update_or_create(
                    student_id=spec["student_id"],
                    defaults={
                        "first_name": spec["first_name"],
                        "last_name": spec["last_name"],
                        "gender": spec["gender"],
                        "district": spec["district"],
                        "religion": spec["religion"],
                        "current_class": spec["current_class"],
                        "section": spec["section"],
                        "parent_name": spec["parent_name"],
                        "parent_relationship": spec["parent_relationship"],
                        "parent_phone": spec["parent_phone"],
                        "parent_phone2": spec["parent_phone2"] or None,
                        "home_address": spec["home_address"],
                        "allergies": "None known",
                        "medical_conditions": "None",
                        "emergency_contact_name": spec["parent_name"],
                        "emergency_contact_phone": spec["parent_phone"],
                        "status": "active",
                    },
                )
                students[spec["student_id"]] = student

            StudentGuardianLink.objects.update_or_create(
                parent_user=parent_mary,
                student=students["DEMO-2026-0001"],
                defaults={"relationship": "mother", "is_active": True, "created_by": admin_user},
            )
            StudentGuardianLink.objects.update_or_create(
                parent_user=parent_mary,
                student=students["DEMO-2026-0003"],
                defaults={"relationship": "guardian", "is_active": True, "created_by": admin_user},
            )
            StudentGuardianLink.objects.update_or_create(
                parent_user=parent_john,
                student=students["DEMO-2026-0002"],
                defaults={"relationship": "father", "is_active": True, "created_by": admin_user},
            )
            StudentGuardianLink.objects.update_or_create(
                parent_user=parent_john,
                student=students["DEMO-2026-0004"],
                defaults={"relationship": "guardian", "is_active": True, "created_by": admin_user},
            )

            invoice_specs = {
                "DEMO-2026-0001": Decimal("420000.00"),
                "DEMO-2026-0002": Decimal("420000.00"),
                "DEMO-2026-0003": Decimal("380000.00"),
                "DEMO-2026-0004": Decimal("450000.00"),
            }
            invoices = {}
            for student_id, amount_due in invoice_specs.items():
                invoice, _ = Invoice.objects.update_or_create(
                    student=students[student_id],
                    academic_year=year,
                    term_number=term,
                    defaults={
                        "amount_due": amount_due,
                        "amount_paid": Decimal("0.00"),
                        "status": "unpaid",
                        "results_blocked": False,
                        "results_block_reason": "",
                        "results_blocked_by": None,
                        "results_blocked_at": None,
                    },
                )
                invoices[student_id] = invoice

            InvoiceAdjustment.objects.update_or_create(
                student=students["DEMO-2026-0002"],
                academic_year=year,
                term_number=term,
                title="Demo penalty",
                defaults={
                    "kind": "penalty",
                    "amount": Decimal("15000.00"),
                    "notes": "Demo late payment penalty for finance timeline testing.",
                    "is_active": True,
                    "created_by": admin_user,
                },
            )

            batch, _ = DepositBatch.objects.update_or_create(
                reference=f"DEMO-DEP-{year}-{term}",
                defaults={
                    "name": f"DEMO Banking {today.isoformat()}",
                    "bank_name": "Demo Bank Uganda",
                    "deposit_date": today,
                    "notes": "Demo batch for bursar reconciliation.",
                    "is_posted": True,
                    "posted_at": now,
                    "posted_by": bursar_user,
                    "created_by": bursar_user,
                },
            )
            payment_specs = [
                {
                    "student": students["DEMO-2026-0001"],
                    "reference": "DEMO-CASH-001",
                    "amount": Decimal("120000.00"),
                    "method": "cash",
                    "status": "received",
                    "receipt_number": f"DEMO-RCPT-{year}{term}-001",
                    "received_by": bursar_user,
                    "approved_by": bursar_user,
                    "approved_at": now - timedelta(days=2),
                    "received_at": now - timedelta(days=2),
                    "notes": "Demo walk-in cash payment.",
                },
                {
                    "student": students["DEMO-2026-0001"],
                    "reference": "DEMO-BANK-001",
                    "amount": Decimal("80000.00"),
                    "method": "bank",
                    "status": "approved",
                    "receipt_number": f"DEMO-RCPT-{year}{term}-002",
                    "received_by": bursar_user,
                    "approved_by": bursar_user,
                    "approved_at": now - timedelta(days=1),
                    "received_at": now - timedelta(days=1),
                    "deposit_batch": batch,
                    "receipt_image_url": "https://example.com/demo-slip-aisha.png",
                    "notes": "Approved demo bank slip.",
                },
                {
                    "student": students["DEMO-2026-0001"],
                    "reference": "DEMO-MTN-001",
                    "amount": Decimal("90000.00"),
                    "method": "mtn_momo",
                    "status": "received",
                    "receipt_number": f"DEMO-RCPT-{year}{term}-003",
                    "received_by": bursar_user,
                    "approved_by": bursar_user,
                    "approved_at": now - timedelta(hours=18),
                    "received_at": now - timedelta(hours=18),
                    "notes": "Demo MTN collection.",
                },
                {
                    "student": students["DEMO-2026-0002"],
                    "reference": "DEMO-CASH-002",
                    "amount": Decimal("150000.00"),
                    "method": "cash",
                    "status": "received",
                    "receipt_number": f"DEMO-RCPT-{year}{term}-004",
                    "received_by": bursar_user,
                    "approved_by": bursar_user,
                    "approved_at": now - timedelta(hours=12),
                    "received_at": now - timedelta(hours=12),
                    "notes": "Demo partial cash payment.",
                },
                {
                    "student": students["DEMO-2026-0002"],
                    "reference": "DEMO-BANK-PENDING-001",
                    "amount": Decimal("85000.00"),
                    "method": "bank",
                    "status": "pending",
                    "received_by": None,
                    "approved_by": None,
                    "approved_at": None,
                    "received_at": now - timedelta(hours=4),
                    "submitted_by": parent_john,
                    "receipt_image_url": "https://example.com/demo-slip-brian-pending.png",
                    "notes": "Pending demo bank slip for approvals page.",
                },
                {
                    "student": students["DEMO-2026-0004"],
                    "reference": "DEMO-AIRTEL-001",
                    "amount": Decimal("450000.00"),
                    "method": "airtel_money",
                    "status": "received",
                    "receipt_number": f"DEMO-RCPT-{year}{term}-005",
                    "received_by": bursar_user,
                    "approved_by": bursar_user,
                    "approved_at": now - timedelta(hours=6),
                    "received_at": now - timedelta(hours=6),
                    "notes": "Demo Airtel payment.",
                },
            ]

            for spec in payment_specs:
                lookup = {
                    "student": spec["student"],
                    "reference": spec["reference"],
                    "academic_year": year,
                    "term_number": term,
                }
                defaults = {
                    "amount": spec["amount"],
                    "method": spec["method"],
                    "status": spec["status"],
                    "receipt_number": spec.get("receipt_number"),
                    "received_by": spec.get("received_by"),
                    "approved_by": spec.get("approved_by"),
                    "approved_at": spec.get("approved_at"),
                    "received_at": spec.get("received_at", now),
                    "notes": spec.get("notes"),
                    "submitted_by": spec.get("submitted_by"),
                    "deposit_batch": spec.get("deposit_batch"),
                    "receipt_image_url": spec.get("receipt_image_url"),
                }
                Payment.objects.update_or_create(**lookup, defaults=defaults)

            stationery, _ = ExpenseCategory.objects.update_or_create(
                name="Demo Stationery",
                defaults={"is_active": True},
            )
            fuel, _ = ExpenseCategory.objects.update_or_create(
                name="Demo Transport",
                defaults={"is_active": True},
            )
            Expense.objects.update_or_create(
                vendor="DEMO Stationery House",
                amount=Decimal("30000.00"),
                expense_date=today,
                defaults={
                    "category": stationery,
                    "description": "Demo stationery purchase for bursar cashbook testing.",
                    "status": "approved",
                    "created_by": bursar_user,
                    "approved_by": admin_user,
                    "approved_at": now - timedelta(hours=5),
                },
            )
            Expense.objects.update_or_create(
                vendor="DEMO Fuel Point",
                amount=Decimal("15000.00"),
                expense_date=today,
                defaults={
                    "category": fuel,
                    "description": "Demo transport fuel expense.",
                    "status": "approved",
                    "created_by": bursar_user,
                    "approved_by": admin_user,
                    "approved_at": now - timedelta(hours=3),
                },
            )

            brian_plan, _ = InstallmentPlan.objects.update_or_create(
                student=students["DEMO-2026-0002"],
                academic_year=year,
                term_number=term,
                title="Demo Brian installment plan",
                defaults={
                    "invoice": invoices["DEMO-2026-0002"],
                    "total_amount": Decimal("285000.00"),
                    "start_date": today - timedelta(days=20),
                    "status": "active",
                    "notes": "Demo staged plan tied to the outstanding balance plus penalty.",
                    "created_by": bursar_user,
                    "approved_by": admin_user,
                },
            )
            esther_plan, _ = InstallmentPlan.objects.update_or_create(
                student=students["DEMO-2026-0003"],
                academic_year=year,
                term_number=term,
                title="Demo Esther rescue plan",
                defaults={
                    "invoice": invoices["DEMO-2026-0003"],
                    "total_amount": Decimal("380000.00"),
                    "start_date": today - timedelta(days=30),
                    "status": "active",
                    "notes": "Demo overdue installment plan for recovery follow-up.",
                    "created_by": bursar_user,
                    "approved_by": admin_user,
                },
            )

            brian_items = [
                ("Installment 1", today - timedelta(days=14), Decimal("95000.00")),
                ("Installment 2", today + timedelta(days=10), Decimal("95000.00")),
                ("Installment 3", today + timedelta(days=40), Decimal("95000.00")),
            ]
            for label, due_date, amount in brian_items:
                InstallmentPlanItem.objects.update_or_create(
                    plan=brian_plan,
                    label=label,
                    defaults={
                        "due_date": due_date,
                        "amount": amount,
                        "amount_paid": Decimal("0.00"),
                        "status": "pending",
                        "notes": "Demo installment schedule line.",
                    },
                )

            esther_items = [
                ("Installment 1", today - timedelta(days=20), Decimal("95000.00")),
                ("Installment 2", today - timedelta(days=5), Decimal("95000.00")),
                ("Installment 3", today + timedelta(days=15), Decimal("95000.00")),
                ("Installment 4", today + timedelta(days=40), Decimal("95000.00")),
            ]
            for label, due_date, amount in esther_items:
                InstallmentPlanItem.objects.update_or_create(
                    plan=esther_plan,
                    label=label,
                    defaults={
                        "due_date": due_date,
                        "amount": amount,
                        "amount_paid": Decimal("0.00"),
                        "status": "pending",
                        "notes": "Demo installment schedule line.",
                    },
                )
            from school.views import _build_cashbook_snapshot, _refresh_finance_commitments

            for invoice in invoices.values():
                self._sync_invoice(invoice)

            _refresh_finance_commitments(students["DEMO-2026-0002"], year, term)
            _refresh_finance_commitments(students["DEMO-2026-0003"], year, term)

            brian_item_3 = InstallmentPlanItem.objects.get(plan=brian_plan, label="Installment 3")
            esther_item_2 = InstallmentPlanItem.objects.get(plan=esther_plan, label="Installment 2")

            brian_promise, _ = FeePromise.objects.update_or_create(
                student=students["DEMO-2026-0002"],
                installment=brian_item_3,
                academic_year=year,
                term_number=term,
                promised_for=today + timedelta(days=7),
                defaults={
                    "promise_date": today,
                    "amount": Decimal("95000.00"),
                    "status": "open",
                    "reminder_count": 1,
                    "last_reminder_at": now - timedelta(days=1),
                    "notes": "Parent promised to clear the final installment next week.",
                    "created_by": bursar_user,
                },
            )
            FeePromise.objects.update_or_create(
                student=students["DEMO-2026-0003"],
                installment=esther_item_2,
                academic_year=year,
                term_number=term,
                promised_for=today - timedelta(days=10),
                defaults={
                    "promise_date": today - timedelta(days=18),
                    "amount": Decimal("50000.00"),
                    "status": "open",
                    "reminder_count": 2,
                    "last_reminder_at": now - timedelta(days=2),
                    "notes": "Promise missed intentionally for overdue testing.",
                    "created_by": bursar_user,
                },
            )

            _refresh_finance_commitments(students["DEMO-2026-0002"], year, term)
            _refresh_finance_commitments(students["DEMO-2026-0003"], year, term)

            FeeReminderLog.objects.update_or_create(
                student=students["DEMO-2026-0003"],
                invoice=invoices["DEMO-2026-0003"],
                channel="sms",
                recipient=students["DEMO-2026-0003"].parent_phone,
                provider="system_sms",
                defaults={
                    "academic_year": year,
                    "term_number": term,
                    "status": "sent",
                    "message": "Demo reminder: Esther still has an outstanding balance.",
                    "created_by": bursar_user,
                    "metadata": {"source": "demo_seed"},
                },
            )
            FeeReminderLog.objects.update_or_create(
                student=students["DEMO-2026-0002"],
                plan=brian_plan,
                installment=brian_item_3,
                channel="email",
                recipient=parent_john.email,
                provider="smtp",
                defaults={
                    "academic_year": year,
                    "term_number": term,
                    "status": "sent",
                    "message": "Demo reminder: Brian's next installment is due soon.",
                    "created_by": bursar_user,
                    "metadata": {"source": "demo_seed"},
                },
            )
            FeeReminderLog.objects.update_or_create(
                student=students["DEMO-2026-0002"],
                promise=brian_promise,
                channel="sms",
                recipient=students["DEMO-2026-0002"].parent_phone,
                provider="system_sms",
                defaults={
                    "academic_year": year,
                    "term_number": term,
                    "status": "sent",
                    "message": "Demo reminder: Brian's fee promise is due in seven days.",
                    "created_by": bursar_user,
                    "metadata": {"source": "demo_seed"},
                },
            )

            blocked_invoice = invoices["DEMO-2026-0003"]
            blocked_invoice.results_blocked = True
            blocked_invoice.results_block_reason = "Outstanding fees - demo hold"
            blocked_invoice.results_blocked_by = bursar_user
            blocked_invoice.results_blocked_at = now - timedelta(days=1)
            blocked_invoice.save(
                update_fields=[
                    "results_blocked",
                    "results_block_reason",
                    "results_blocked_by",
                    "results_blocked_at",
                    "updated_at",
                ]
            )
            hold_log = ResultsHoldLog.objects.filter(invoice=blocked_invoice, action="held", source="demo_seed").first()
            if hold_log:
                hold_log.reason = blocked_invoice.results_block_reason
                hold_log.acted_by = bursar_user  # type: ignore[assignment]
                hold_log.acted_at = blocked_invoice.results_blocked_at
                hold_log.save(update_fields=["reason", "acted_by", "acted_at"])
            else:
                ResultsHoldLog.objects.create(
                    invoice=blocked_invoice,
                    action="held",
                    reason=blocked_invoice.results_block_reason,
                    source="demo_seed",
                    acted_by=bursar_user,
                    acted_at=blocked_invoice.results_blocked_at,
                )

            snapshot = _build_cashbook_snapshot(
                today,
                cashier=bursar_user,
                opening_cash=Decimal("50000.00"),
                counted_cash_on_hand=Decimal("270000.00"),
            )
            CashbookClose.objects.update_or_create(
                close_date=today,
                cashier=bursar_user,
                defaults={
                    "status": "closed",
                    "opening_cash": Decimal("50000.00"),
                    "cash_received_total": Decimal(str(snapshot.get("cash_received_total") or 0)),
                    "non_cash_received_total": Decimal(str(snapshot.get("non_cash_received_total") or 0)),
                    "approved_expense_total": Decimal(str(snapshot.get("approved_expense_total") or 0)),
                    "expected_cash_on_hand": Decimal(str(snapshot.get("expected_cash_on_hand") or 0)),
                    "counted_cash_on_hand": Decimal("270000.00"),
                    "variance_amount": Decimal(str(snapshot.get("variance_amount") or 0)),
                    "deposit_batch_total": Decimal(str(snapshot.get("deposit_batch_total") or 0)),
                    "payment_count": int(snapshot.get("payment_count") or 0),
                    "expense_count": int(snapshot.get("expense_count") or 0),
                    "notes": "[demo-seed] Demo close used for bursar reconciliation walkthrough.",
                    "snapshot": snapshot,
                    "closed_by": bursar_user,
                    "closed_at": now,
                },
            )

        self.stdout.write(self.style.SUCCESS("Demo finance data seeded."))
        self.stdout.write(f"Active term: T{term}/{year}")
        self.stdout.write("Demo accounts:")
        self.stdout.write("  bursar: demo_bursar / DemoBursar@2026")
        self.stdout.write("  parent: demo_parent_mary / DemoParent@2026")
        self.stdout.write("  parent: demo_parent_john / DemoParent@2026")
