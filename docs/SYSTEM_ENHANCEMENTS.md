# School Management System - Enhancements & Implementation Guide

**Date:** May 22, 2026  
**Status:** Phase 1 - Core Models & ViewSets Complete  
**Next Steps:** URL Registration, Migrations, UI Components

---

## Overview

This document outlines comprehensive enhancements to the school management system, addressing:
1. **Grading Scale Redesign** - Less congested UI with template support
2. **Exam Type Management** - Flexible exam scheduling (Midterm, End of Term, etc.)
3. **Academic Calendar** - Important dates and events tracking
4. **Financial Enhancements** - Debt tracking, installment management
5. **Salary & Payroll Management** - Teachers and non-portal staff
6. **User Role Enhancement** - Added Director role
7. **Communication Improvements** - Better group chat and notifications

---

## 1. GRADING SCALE ENHANCEMENTS

### What's Changed

The `GradingScale` model has been significantly enhanced:

```python
class GradingScale(models.Model):
    TEMPLATE_CHOICES = [
        ('5grade', '5-Grade System'),
        ('13grade', '13-Grade System'),
        ('7point', '7-Point Scale'),
        ('custom', 'Custom'),
    ]
    
    name: CharField(unique)
    template_type: CharField(choices=TEMPLATE_CHOICES)
    description: TextField
    scale_data: JSONField (grade bands with GPA points)
    is_default: BooleanField
    is_template: BooleanField (for reusable templates)
    school_class: ForeignKey (for class-specific scales)
    created_by: ForeignKey(User)
    created_at, updated_at: DateTimeField
```

### Standard Grading Scales Included

These templates should be pre-loaded:

**5-Grade System:**
```json
[
  {"grade": "A", "min_score": 90, "max_score": 100, "gpa_points": 4.0, "status": "Pass", "implication": "Excellent"},
  {"grade": "B", "min_score": 80, "max_score": 89, "gpa_points": 3.0, "status": "Pass", "implication": "Good"},
  {"grade": "C", "min_score": 70, "max_score": 79, "gpa_points": 2.0, "status": "Pass", "implication": "Satisfactory"},
  {"grade": "D", "min_score": 60, "max_score": 69, "gpa_points": 1.0, "status": "Pass", "implication": "Needs Improvement"},
  {"grade": "F", "min_score": 0, "max_score": 59, "gpa_points": 0.0, "status": "Fail", "implication": "Repeat"}
]
```

**13-Grade System (US Standard):**
```json
[
  {"grade": "A+", "min_score": 97, "max_score": 100, "gpa_points": 4.0},
  {"grade": "A", "min_score": 93, "max_score": 96, "gpa_points": 3.9},
  {"grade": "A-", "min_score": 90, "max_score": 92, "gpa_points": 3.7},
  {"grade": "B+", "min_score": 87, "max_score": 89, "gpa_points": 3.3},
  {"grade": "B", "min_score": 83, "max_score": 86, "gpa_points": 3.0},
  {"grade": "B-", "min_score": 80, "max_score": 82, "gpa_points": 2.7},
  {"grade": "C+", "min_score": 77, "max_score": 79, "gpa_points": 2.3},
  {"grade": "C", "min_score": 73, "max_score": 76, "gpa_points": 2.0},
  {"grade": "C-", "min_score": 70, "max_score": 72, "gpa_points": 1.7},
  {"grade": "D+", "min_score": 67, "max_score": 69, "gpa_points": 1.3},
  {"grade": "D", "min_score": 63, "max_score": 66, "gpa_points": 1.0},
  {"grade": "D-", "min_score": 60, "max_score": 62, "gpa_points": 0.7},
  {"grade": "F", "min_score": 0, "max_score": 59, "gpa_points": 0.0}
]
```

### UI/UX Improvements

Create a new, cleaner grading scale management interface:
- **Separate tabs**: View templates, Create custom scale, Apply to class
- **Visual preview**: Show grade bands as a horizontal bar chart
- **Bulk import**: Load predefined templates with one click
- **Grade band management**: Add/edit/delete individual grades in a clean table
- **Validation**: Ensure min/max scores don't overlap
- **GPA calculation**: Auto-calculate GPA points if needed

---

## 2. EXAM TYPE MANAGEMENT

### New Model: ExamType

```python
class ExamType(models.Model):
    EXAM_TYPE_CHOICES = [
        ('beginning', 'Beginning of Term'),
        ('midterm', 'Midterm'),
        ('endterm', 'End of Term'),
        ('other', 'Other'),
    ]
    
    name: CharField
    exam_type: CharField(choices=EXAM_TYPE_CHOICES)
    description: TextField
    is_active: BooleanField
```

### Usage

Allows schools to:
- Define which exam types they use (e.g., only midterm + endterm)
- Mark exams with their type when entering marks
- Average multiple exam scores to get final term grade

---

## 3. ACADEMIC CALENDAR EVENTS

### New Model: AcademicCalendarEvent

```python
class AcademicCalendarEvent(models.Model):
    EVENT_TYPE_CHOICES = [
        ('exam', 'Exam'),
        ('visitation_day', 'Visitation Day (VD)'),
        ('payment_deadline', 'Payment Deadline'),
        ('holiday', 'Holiday'),
        ('school_closure', 'School Closure'),
        ('event', 'Event'),
        ('other', 'Other'),
    ]
    
    academic_term: ForeignKey(AcademicTerm)
    event_type: CharField
    exam_type: ForeignKey(ExamType, nullable)
    title: CharField
    description: TextField
    event_date: DateField
    start_time, end_time: TimeField
    notify_parents, notify_teachers, notify_staff: BooleanField
    created_by: ForeignKey(User)
```

### Features

- Mark important dates in the academic calendar
- Support for Visitation Days (VD) - reminders to parents for fee payment
- Auto-notify relevant parties (parents, teachers, staff)
- Link to specific exam types
- Multiple events can be scheduled for different purposes

---

## 4. INSTALLMENT PLAN MANAGEMENT

### New Model: TermInstallmentPlan

```python
class TermInstallmentPlan(models.Model):
    academic_term: OneToOneField(AcademicTerm)
    number_of_installments: IntegerField (2 or 3)
    installments: JSONField
    # Example: [
    #   {"number": 1, "due_date": "2026-03-15", "percentage": 50},
    #   {"number": 2, "due_date": "2026-05-15", "percentage": 50}
    # ]
```

### Features

- Admins specify number of installments (2 or 3) per term
- System auto-calculates due dates based on term dates
- Auto-splits amounts by percentage
- Reminders sent on payment deadlines
- Visitation Day marked after midterm for parent-teacher meetings

---

## 5. STUDENT DEBT TRACKING

### New Model: StudentDebtRecord

```python
class StudentDebtRecord(models.Model):
    student: ForeignKey(Student)
    academic_term: ForeignKey(AcademicTerm)
    original_amount: DecimalField
    outstanding_amount: DecimalField
    is_settled: BooleanField
    settled_date: DateTimeField
    settled_by: ForeignKey(User)
```

### Features

- Tracks unpaid fees from previous terms separately
- Parents/admins see clear distinction: new term fees vs old debt
- Debt carries forward until settled
- Auto-calculated when parent views account/portal
- Prevents promotion if debt unsettled (configurable)

---

## 6. TEACHER SALARY & ALLOWANCES

### New Models

#### TeacherSalary

```python
class TeacherSalary(models.Model):
    teacher: ForeignKey(Teacher)
    academic_term: ForeignKey(AcademicTerm)
    base_salary: DecimalField
    payment_status: CharField (pending|approved|paid|partial)
    approved_by: ForeignKey(User)
    paid_by: ForeignKey(User)
    amount_paid: DecimalField
    paid_date: DateTimeField
```

#### TeacherAllowance

```python
class TeacherAllowance(models.Model):
    ALLOWANCE_TYPE_CHOICES = [
        ('transport', 'Transport Allowance'),
        ('housing', 'Housing Allowance'),
        ('meal', 'Meal Allowance'),
        ('performance', 'Performance Bonus'),
        ('other', 'Other'),
    ]
    
    teacher: ForeignKey(Teacher)
    academic_term: ForeignKey(AcademicTerm)
    allowance_type: CharField
    amount: DecimalField
    is_paid: BooleanField
```

### Features

- Track individual salary records per teacher per term
- Separate allowances tracking (transport, housing, meal, bonus)
- Approval workflow: pending → approved → paid
- Payment notifications to teachers
- Financial dashboard shows total salary costs

---

## 7. NON-PORTAL STAFF MANAGEMENT

### New Model: OtherStaff

```python
class OtherStaff(models.Model):
    STAFF_ROLE_CHOICES = [
        ('cook', 'Cook'),
        ('cleaner', 'Cleaner'),
        ('guard', 'Guard'),
        ('driver', 'Driver'),
        ('laborer', 'Laborer'),
        ('maintenance', 'Maintenance'),
        ('other', 'Other'),
    ]
    
    first_name, last_name: CharField
    role: CharField
    phone_number, email: CharField
    base_salary: DecimalField
    start_date, end_date: DateField
    is_active: BooleanField
```

### Features

- Register non-portal workers (cooks, guards, cleaners, etc.)
- Track their salaries for accurate profit calculations
- Can be included in payroll reports
- Helps school see true operational costs

---

## 8. UNIFIED PAYROLL MANAGEMENT

### New Model: StaffPayroll

```python
class StaffPayroll(models.Model):
    academic_term: ForeignKey(AcademicTerm)
    teacher: ForeignKey(Teacher, nullable)
    other_staff: ForeignKey(OtherStaff, nullable)
    gross_amount: DecimalField
    deductions: DecimalField
    net_amount: DecimalField
    payment_method: CharField (cash|bank_transfer|mobile_money|check)
    payment_status: CharField (pending|approved|paid)
    approved_by: ForeignKey(User)
    paid_by: ForeignKey(User)
    paid_date: DateTimeField
```

### Features

- Unified payroll for all staff (teachers + non-portal)
- Workflow: pending → approved → paid
- Supports multiple payment methods
- Audit trail (who approved, who paid, when)
- Auto-deduct from school profits in financial dashboard

---

## 9. USER ROLES & PERMISSIONS

### New Role: Director / Head Director

Added to `UserProfile` role choices:
```python
('director', 'Director/Head Director'),
```

### Permission Matrix

| Feature | Super Admin | Director | Head Teacher | Bursar | DOS |
|---------|-----------|----------|-------------|--------|-----|
| Manage API Keys | ✓ | ✗ | ✗ | ✗ | ✗ |
| Issue Payments | ✓ | ✓ | ✓ | ✓ | ✗ |
| View All Financials | ✓ | ✓ | ✓ | ✓ | ✗ |
| Approve Salaries | ✓ | ✓ | ✓ | ✓ | ✗ |
| Set Grading Scales | ✓ | ✓ | ✗ | ✗ | ✓ |
| Manage Terms | ✓ | ✓ | ✗ | ✗ | ✓ |

---

## 10. API ENDPOINTS

### New ViewSets (to be registered in urls.py)

```python
# Academic Management
router.register(r'exam-types', ExamTypeViewSet)
router.register(r'academic-calendar-events', AcademicCalendarEventViewSet)
router.register(r'term-installment-plans', TermInstallmentPlanViewSet)

# Financial Management
router.register(r'student-debts', StudentDebtRecordViewSet)

# Salary & Payroll
router.register(r'teacher-salaries', TeacherSalaryViewSet)
router.register(r'teacher-allowances', TeacherAllowanceViewSet)
router.register(r'other-staff', OtherStaffViewSet)
router.register(r'staff-payroll', StaffPayrollViewSet)
```

---

## 11. COMMUNICATION IMPROVEMENTS

### Enhanced Features to Add

1. **Group Chat**
   - Create groups by class, department, custom
   - Parents can view class announcements
   - Teachers can group message parents

2. **Teacher Contact Info**
   - Add WhatsApp number to Teacher model
   - Display on parent portal
   - Direct link to teacher's WhatsApp

3. **Admin Contact Directory**
   - List of key admin contacts on parent portal
   - Email, phone, WhatsApp for school office
   - Opens in default app (email, phone, WhatsApp)

4. **Improved Notifications**
   - Send payment reminders (VD + installment due dates)
   - Exam schedule notifications
   - Staff payment notifications
   - Promotion/demotion announcements

---

## 12. MIGRATION & DEPLOYMENT STEPS

### 1. Generate Migrations

```bash
python manage.py makemigrations school
```

This will create migration files for:
- Enhanced GradingScale model
- ExamType
- AcademicCalendarEvent
- TermInstallmentPlan
- StudentDebtRecord
- TeacherSalary
- TeacherAllowance
- OtherStaff
- StaffPayroll
- New UserProfile role choice

### 2. Apply Migrations

```bash
python manage.py migrate school
```

### 3. Create Superuser (if needed)

```bash
python manage.py createsuperuser
```

### 4. Load Initial Data

Create a data migration or Django fixture for standard grading scales:

```bash
python manage.py loaddata standard_grading_scales.json
```

**File:** `school/fixtures/standard_grading_scales.json`

```json
[
  {
    "model": "school.gradingscale",
    "pk": 1,
    "fields": {
      "name": "Standard 5-Grade (A-F)",
      "template_type": "5grade",
      "description": "Standard American grading: A (90-100), B (80-89), C (70-79), D (60-69), F (0-59)",
      "scale_data": [...],
      "is_default": true,
      "is_template": true,
      "school_class": null,
      "created_by": null
    }
  },
  // Add more templates...
]
```

### 5. Update settings.py (if needed)

No changes needed to settings, but ensure:
- `django_filters` is installed (for filtering in viewsets)
- Django REST Framework is configured properly

### 6. Test Endpoints

After deploying, test each new endpoint:

```bash
# Get all exam types
curl -X GET http://localhost:8000/api/exam-types/ \
  -H "Authorization: Bearer <token>"

# Create a new exam type
curl -X POST http://localhost:8000/api/exam-types/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Midterm Exam",
    "exam_type": "midterm",
    "is_active": true
  }'
```

---

## 13. KNOWN API ISSUE TO FIX

### Error: "Request failed" in API Credential Verification

**Location:** `APICredential` model verification method  
**Symptoms:** When verifying API credentials, system returns "Request failed"  
**Root Cause:** To be diagnosed - likely network issue or missing error handling  

**Investigation Steps:**
1. Check `APICredentialHealthLog` for error details
2. Look for `last_verify_detail` field
3. Check network connectivity to API endpoints
4. Verify API credentials are correct
5. Add better error messages

**Fix Location:** `school/views.py` - `APICredentialViewSet.verify()` method

---

## 14. FINANCIAL DASHBOARD ENHANCEMENTS

### To be implemented:

1. **Profit/Loss Calculation**
   - Total fees collected (paid invoices)
   - Minus: Total salaries paid
   - Minus: Total expenses approved
   - Equals: Net Profit/Loss

2. **Per-Class Breakdown**
   - Fees collected by class
   - Salaries allocated to class teachers
   - Expenses by class (if possible)

3. **Financial Trends**
   - Monthly revenue trend
   - Monthly expense trend
   - Student payment patterns
   - Debt collection trends

4. **Reports**
   - Monthly financial summary
   - Annual financial summary
   - Debt aging report
   - Staff payment history

---

## 15. VALIDATION & CONSTRAINTS

### Grading Scale Validation

- Ensure grade ranges don't overlap
- Ensure all scores 0-100 are covered
- GPA points should match grade importance

### Installment Plan Validation

- Percentages must total 100%
- Due dates must be within term period
- At least 2, maximum 3 installments

### Salary Processing Validation

- Base salary must be positive
- Amount paid ≤ base salary + allowances
- Approval required before payment

---

## 16. NEXT TASKS

- [ ] Create data migration for standard grading scales
- [ ] Implement grading scale UI component  
- [ ] Add exam type selection to Mark entry form
- [ ] Create academic calendar events UI
- [ ] Implement payment deadline reminders
- [ ] Create financial dashboard
- [ ] Add staff payroll report
- [ ] Test all permission checks
- [ ] Fix API credential error
- [ ] Create user documentation
- [ ] Train admins on new features

---

## 17. TESTING CHECKLIST

- [ ] Create ExamType and filter by is_active
- [ ] Create AcademicCalendarEvent and link to exam
- [ ] Create TermInstallmentPlan with 2 and 3 installments
- [ ] Create StudentDebtRecord and settle it
- [ ] Create TeacherSalary workflow (pending → approved → paid)
- [ ] Create TeacherAllowance for different types
- [ ] Create OtherStaff and include in payroll
- [ ] Create StaffPayroll entry and process payment
- [ ] Test Director role permissions
- [ ] Test all filtered endpoints
- [ ] Verify audit logs created for key actions

---

**Prepared by:** System Enhancement Team  
**Date:** May 22, 2026  
**Status:** Ready for Phase 2 (UI & Integration)
