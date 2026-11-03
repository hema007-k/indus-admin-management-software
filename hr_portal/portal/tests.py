from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from .models import Designation, Employee, Project

User = get_user_model()


class PortalSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def login(self, username, password):
        self.assertTrue(self.client.login(username=username, password=password))

    def test_login_page(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_redirect_when_anonymous(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_employee_pages_and_clock(self):
        self.login("arun", "arun123")
        for name in ("dashboard", "project_list"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.post(reverse("clock_in"), follow=True).status_code, 200)
        self.assertEqual(self.client.post(reverse("clock_out"), follow=True).status_code, 200)
        self.assertEqual(self.client.get(reverse("employee_list")).status_code, 403)

    def test_manager_pages(self):
        self.login("admin", "admin123")
        for name in ("dashboard", "employee_list", "employee_create", "project_list", "project_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        emp = Employee.objects.get(user__username="arun")
        self.assertEqual(self.client.get(reverse("employee_edit", args=[emp.pk])).status_code, 200)
        p = Project.objects.first()
        self.assertEqual(self.client.get(reverse("project_edit", args=[p.pk])).status_code, 200)

    def test_employee_detail(self):
        self.login("admin", "admin123")
        emp = Employee.objects.get(user__username="arun")
        for q in ("", "?from=home"):
            r = self.client.get(reverse("employee_detail", args=[emp.pk]) + q)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Arun")
        self.client.logout()
        self.login("priya", "priya123")  # an employee cannot open somebody else's details
        self.assertEqual(self.client.get(reverse("employee_detail", args=[emp.pk])).status_code, 403)
        self.client.logout()
        self.login("arun", "arun123")  # ... but can open their own
        self.assertEqual(self.client.get(reverse("employee_detail", args=[emp.pk])).status_code, 200)

    def test_add_employee(self):
        self.login("hr", "hr12345")
        resp = self.client.post(reverse("employee_create"), {
            "employee_id": "EMP900", "username": "newbie", "first_name": "New", "last_name": "Bie",
            "email": "n@example.com", "password": "pass12345",
            "designation": Designation.objects.create(name="Tester").pk,
            "status": "active", "role": "employee", "blood_group": "O+", "phone": "9876543210", "emergency_name": "Dad", "emergency_phone": "9000000000", "emergency_relation": "Father",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())
        e = Employee.objects.get(user__username="newbie")
        self.assertEqual((e.blood_group, e.emergency_name, e.visible_password), ("O+", "Dad", "pass12345"))

    def test_api_token_flow(self):
        r = self.client.post("/api/auth/login/", {"username": "arun", "password": "arun123"})
        self.assertEqual(r.status_code, 200)
        token = r.json()["token"]
        r = self.client.get("/api/dashboard/", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("month_summary", r.json())
        r = self.client.get("/api/employees/", HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(r.status_code, 403)

    def _token(self, username, password):
        r = self.client.post("/api/auth/login/", {"username": username, "password": password})
        return {"HTTP_AUTHORIZATION": f"Token {r.json()['token']}"}

    def test_api_manager_attendance_endpoints(self):
        emp = Employee.objects.get(user__username="arun")
        mgr = self._token("hr", "hr12345")
        rows = self.client.get("/api/attendance/today/", **mgr).json()
        self.assertTrue(any(r["employee_id"] == emp.employee_id for r in rows))
        detail = self.client.get(f"/api/employees/{emp.pk}/attendance/", **mgr).json()
        self.assertIn("summary", detail)
        self.assertEqual(len(detail["history"]), 30)
        staff = self._token("arun", "arun123")
        self.assertEqual(self.client.get("/api/attendance/today/", **staff).status_code, 403)
        self.assertEqual(self.client.get(f"/api/employees/{emp.pk}/attendance/", **staff).status_code, 403)

    def test_api_employee_crud_for_app(self):
        mgr = self._token("admin", "admin123")
        r = self.client.post("/api/employees/", {
            "employee_id": "EMP901", "username": "appuser", "first_name": "App", "password": "pass12345",
            "role": "employee", "status": "active",
        }, content_type="application/json", **mgr)
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.json()["id"]
        r = self.client.patch(f"/api/employees/{pk}/", {"designation": "QA"}, content_type="application/json", **mgr)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["designation"], "QA")
        self.assertEqual(self.client.delete(f"/api/employees/{pk}/", **mgr).status_code, 204)


class OrganizationTests(TestCase):
    """Department / Team create, edit, delete (HR + Admin only)."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def test_org_page_and_permissions(self):
        self.client.login(username="admin", password="admin123")
        for name in ("organization", "department_create", "team_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.client.logout()
        self.client.login(username="arun", password="arun123")
        for name in ("organization", "department_create", "team_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_create_department_and_team(self):
        from .models import Department, Team
        self.client.login(username="hr", password="hr12345")
        r = self.client.post(reverse("department_create"), {"name": "Legal", "description": "Contracts"})
        self.assertRedirects(r, reverse("organization"))
        dept = Department.objects.get(name="Legal")
        r = self.client.post(reverse("team_create"), {"name": "Compliance", "department": dept.pk})
        self.assertRedirects(r, reverse("organization"))
        self.assertTrue(Team.objects.filter(name="Compliance", department=dept).exists())
        # duplicates are rejected with a friendly message, not a 500
        r = self.client.post(reverse("department_create"), {"name": "Legal"})
        self.assertContains(r, "already exists")
        r = self.client.post(reverse("team_create"), {"name": "Compliance", "department": dept.pk})
        self.assertContains(r, "already exists in the selected department")

    def test_edit_and_delete(self):
        from .models import Department, Team
        self.client.login(username="admin", password="admin123")
        dept = Department.objects.create(name="Temp")
        team = Team.objects.create(name="T1", department=dept)
        self.client.post(reverse("team_edit", args=[team.pk]), {"name": "T1-renamed", "department": dept.pk})
        team.refresh_from_db()
        self.assertEqual(team.name, "T1-renamed")
        self.assertEqual(self.client.get(reverse("department_delete", args=[dept.pk])).status_code, 200)
        self.client.post(reverse("department_delete", args=[dept.pk]))
        self.assertFalse(Department.objects.filter(pk=dept.pk).exists())
        self.assertFalse(Team.objects.filter(pk=team.pk).exists())

    def test_employee_team_must_match_department(self):
        from .models import Department, Team
        self.client.login(username="admin", password="admin123")
        d1, d2 = Department.objects.create(name="D-one"), Department.objects.create(name="D-two")
        t2 = Team.objects.create(name="Only-in-two", department=d2)
        r = self.client.post(reverse("employee_create"), {
            "employee_id": "EMP901", "username": "mismatch", "first_name": "Mis", "password": "pass12345",
            "department": d1.pk, "team": t2.pk, "status": "active", "role": "employee",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "belongs to")


from datetime import date, time, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

from . import services  # noqa: E402
from .models import (  # noqa: E402
    Attendance, Department, Holiday, LeaveRequest, LeaveType, Notification, PermissionTransfer, ProjectAssignment,
    ProjectUpdate, Team,
)


class FeatureTests(TestCase):
    """Employee code, leave credit, working days, project metrics, role / designation permissions."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def login(self, username, password):
        self.assertTrue(self.client.login(username=username, password=password))

    def emp(self, username):
        return Employee.objects.get(user__username=username)

    # ---- employee code
    def test_employee_code_is_compulsory_unique_and_suggested(self):
        self.login("hr", "hr12345")
        page = self.client.get(reverse("employee_create")).content.decode()
        self.assertIn("EMP006", page)                       # next free code is already filled in
        base = {"first_name": "Auto", "password": "pass12345", "status": "active", "role": "employee",
                "blood_group": "O+", "phone": "9876543210", "email": "a@example.com"}
        r = self.client.post(reverse("employee_create"), {**base, "employee_id": "", "username": "blankcode"})
        self.assertContains(r, "Enter the employee ID")
        for i, code in enumerate(("EMP006", "EMP007")):
            r = self.client.post(reverse("employee_create"), {**base, "employee_id": code, "username": f"auto{i}"})
            self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        codes = list(Employee.objects.values_list("employee_id", flat=True))
        self.assertEqual(len(codes), len(set(codes)))
        # a manually typed duplicate is refused
        r = self.client.post(reverse("employee_create"), {**base, "employee_id": "emp003", "username": "dupe"})
        self.assertContains(r, "already used")

    # ---- one login page for everybody
    def test_single_login_page_for_admin_and_employee(self):
        r = self.client.post(reverse("login"), {"username": "admin", "password": "admin123"})
        self.assertEqual(r.status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("login"), {"username": "arun", "password": "arun123"}).status_code, 302)
        self.client.logout()
        # the old Admin address opens the same page
        r = self.client.get(reverse("admin_login"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], reverse("login"))
        page = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("Admin / HR? Sign in here", page)
        self.assertNotIn("Employee? Sign in here", page)
        # a protected page sends people to that one page
        r = self.client.get(reverse("employee_list"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])

    # ---- permissions given to the person (a designation is only a job title)
    def test_designation_permissions(self):
        self.login("arun", "arun123")  # demo: arun was given project permissions only
        self.assertEqual(self.client.get(reverse("project_create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("employee_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("attendance_list")).status_code, 403)
        self.client.logout()
        self.login("priya", "priya123")  # Modeling Specialist: nothing to manage
        self.assertEqual(self.client.get(reverse("project_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("leave_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("my_profile")).status_code, 200)
        # giving the PERSON the permission opens the page
        Employee.objects.filter(user__username="priya").update(can_manage_attendance=True)
        self.assertEqual(self.client.get(reverse("attendance_list")).status_code, 200)

    def test_only_manager_role_can_make_admins(self):
        Employee.objects.filter(user__username="priya").update(can_view_employees=True, can_create_employees=True, can_edit_employees=True)
        self.login("priya", "priya123")
        admin_emp = self.emp("admin")
        self.assertEqual(self.client.get(reverse("employee_edit", args=[admin_emp.pk])).status_code, 403)
        r = self.client.get(reverse("employee_create"))
        self.assertNotContains(r, 'value="admin"')

    # ---- leave credit + validation
    def test_leave_credit_and_validation(self):
        arun = self.emp("arun")
        casual = LeaveType.objects.get(name="Casual Leave")
        seeded = LeaveRequest.objects.get(employee=arun, status="approved")
        bal = services.leave_balances(arun, seeded.start_date.year)
        row = next(r for r in bal["rows"] if r["type"] == casual)
        credit = Decimal("1.5") * services.months_credited(arun, seeded.start_date.year)  # 1.5 days every month
        self.assertEqual((seeded.days, row["credit"], row["used"], row["balance"]), (2, credit, 2, credit - 2))
        self.login("arun", "arun123")
        lop = LeaveType.objects.get(name="Loss of Pay")
        start = date.today() + timedelta(days=30)
        while start.weekday() != 0:
            start += timedelta(days=1)
        end = start + timedelta(days=4)  # Mon-Fri
        r = self.client.post(reverse("leave_create"), {
            "leave_type": lop.pk, "start_date": start, "end_date": end, "reason": "trip",
        })
        self.assertEqual(r.status_code, 302)
        leave = LeaveRequest.objects.get(employee=arun, reason="trip")
        self.assertEqual((leave.days, leave.status), (services.leave_days_for(start, end), "pending"))
        # HR / managers got a notification about the new request
        self.assertTrue(Notification.objects.filter(recipient=self.emp("hr"), kind="leave").exists())
        # overlapping request refused
        r = self.client.post(reverse("leave_create"), {
            "leave_type": lop.pk, "start_date": start, "end_date": start, "reason": "again"})
        self.assertContains(r, "already has leave")
        # more than the Casual Leave credit refused -> must be applied as LOP
        far = start + timedelta(days=60)
        r = self.client.post(reverse("leave_create"), {
            "leave_type": casual.pk, "start_date": far, "end_date": far + timedelta(days=25)})
        if far.year == (far + timedelta(days=25)).year:
            self.assertContains(r, "Loss of Pay")
        # an employee cannot approve; HR can
        self.assertEqual(self.client.post(reverse("leave_decide", args=[leave.pk]), {"action": "approve"}).status_code, 403)
        self.client.logout()
        self.login("hr", "hr12345")
        self.client.post(reverse("leave_decide", args=[leave.pk]), {"action": "approve"})
        leave.refresh_from_db()
        self.assertEqual(leave.status, "approved")

    # ---- working-day maths
    def test_period_summary_office_field_leave(self):
        emp = self.emp("vijay")
        Attendance.objects.filter(employee=emp).delete()
        LeaveRequest.objects.filter(employee=emp).delete()
        mon = date(2026, 3, 2)  # a Monday
        for i, mode in enumerate(["office", "office", "field"]):  # Mon, Tue, Wed present
            Attendance.objects.create(employee=emp, date=mon + timedelta(days=i), in_time=time(9), out_time=time(18), work_mode=mode)
        casual = LeaveType.objects.get(name="Casual Leave")
        LeaveRequest.objects.create(employee=emp, leave_type=casual, start_date=mon + timedelta(days=3),
                                    end_date=mon + timedelta(days=3), status="approved")  # Thu on leave
        s = services.period_summary(emp, mon, mon + timedelta(days=6), today=mon + timedelta(days=7))
        # Mon-Sun: 6 working days; 3 present (2 office, 1 field), 1 leave, Fri + Sat absent
        # (Mon-Sat are working days - Sunday is off; 7-Mar is the 1st Saturday)
        self.assertEqual((s["working_days"], s["present"], s["office"], s["field"]), (6, 3, 2, 1))
        self.assertEqual((s["leave"], s["absent"], s["net_working_days"], s["percent"]), (1, 2, 5, 60))

    def test_project_working_days_consider_leave(self):
        from .models import Project

        a, b, c = self.emp("arun"), self.emp("priya"), self.emp("vijay")
        LeaveRequest.objects.filter(employee__in=[a, b, c]).delete()
        proj = Project.objects.create(name="Maths", start_date=date(2026, 3, 2), end_date=date(2026, 3, 13))
        proj.employees.set([a, b, c])  # three employees on one project
        casual = LeaveType.objects.get(name="Casual Leave")
        LeaveRequest.objects.create(employee=a, leave_type=casual, start_date=date(2026, 3, 4),
                                    end_date=date(2026, 3, 5), status="approved")
        m = services.project_metrics(proj, today=date(2026, 4, 1))
        self.assertEqual(m["span_days"], 11)  # Mon-Sat of week 1 (7-Mar is a working Saturday) + Mon-Fri of week 2
        self.assertEqual(m["leave_days"], 2)
        self.assertEqual(m["man_days"], 11 * 3 - 2)
        self.assertEqual(sorted(r["net_days"] for r in m["rows"]), [9, 11, 11])
        # leave that is only pending or rejected does not reduce working days
        LeaveRequest.objects.create(employee=b, leave_type=casual, start_date=date(2026, 3, 9),
                                    end_date=date(2026, 3, 9), status="pending")
        self.assertEqual(services.project_metrics(proj, today=date(2026, 4, 1))["leave_days"], 2)

    # ---- project form: many employees, completion
    def test_project_many_employees_and_completion(self):
        self.login("admin", "admin123")
        ids = list(Employee.objects.exclude(role="admin").values_list("pk", flat=True))[:4]
        r = self.client.post(reverse("project_create"), {
            "name": "Big team", "description": "Survey the bay", "status": "inprogress", "completion": 100})
        self.assertEqual(r.status_code, 302)
        from .models import Project
        p = Project.objects.get(name="Big team")
        self.assertRedirects(r, reverse("project_assign", args=[p.pk]))      # step 2 opens by itself
        r = self.client.post(reverse("project_assign", args=[p.pk]), {
            "employees": ids, **{f"mode_{i}": "field" for i in ids}, **{f"ftype_{i}": "onshore" for i in ids},
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(p.employees.count(), len(ids))
        self.assertEqual((p.completion, p.status), (100, "completed"))
        self.assertContains(self.client.get(reverse("project_detail", args=[p.pk])), "Big team")

    # ---- every page renders, with monthly + yearly filters
    def test_pages_render_with_period_filters(self):
        for who, pw, names in (
            ("admin", "admin123", ["dashboard", "employee_list", "organization", "project_list", "leave_list",
                                   "attendance_list", "attendance_create", "leave_create", "designation_create",
                                   "leavetype_create"]),
            ("arun", "arun123", ["dashboard", "my_profile", "project_list", "leave_list", "leave_create"]),
        ):
            self.client.logout()
            self.login(who, pw)
            for name in names:
                for q in ("", "?period=month&month=2026-03", "?period=year&year=2026", "?period=all"):
                    r = self.client.get(reverse(name) + q)
                    self.assertEqual(r.status_code, 200, f"{who} {name} {q}")
        emp = self.emp("arun")
        self.client.logout()
        self.login("admin", "admin123")
        for q in ("?period=year&year=2026", "?period=month&month=2026-02"):
            self.assertEqual(self.client.get(reverse("employee_detail", args=[emp.pk]) + q).status_code, 200)

    def test_employee_search(self):
        self.login("hr", "hr12345")
        r = self.client.get(reverse("employee_list") + "?q=priya")
        self.assertContains(r, "Priya")
        self.assertNotContains(r, "Vijay")
        r = self.client.get(reverse("employee_list") + "?q=EMP005")
        self.assertContains(r, "Vijay")

    def test_attendance_edit_by_permission(self):
        self.login("hr", "hr12345")
        emp = self.emp("arun")
        r = self.client.post(reverse("attendance_create"), {
            "employee": emp.pk, "date": "2026-01-05", "in_time": "09:00", "out_time": "17:30", "work_mode": "field",
            "field_type": "offshore"})
        self.assertEqual(r.status_code, 302)
        rec = Attendance.objects.get(employee=emp, date=date(2026, 1, 5))
        self.assertEqual((rec.work_mode, rec.out_time), ("field", time(17, 30)))
        self.assertEqual(rec.location_label, "Field (Off shore)")

    def test_check_db_command(self):
        from io import StringIO
        out = StringIO()
        call_command("check_db", stdout=out)
        self.assertIn("Database OK", out.getvalue())
        self.assertNotIn("FAIL", out.getvalue())

    def test_api_leave_and_clock_mode(self):
        r = self.client.post("/api/auth/login/", {"username": "arun", "password": "arun123"})
        h = {"HTTP_AUTHORIZATION": f"Token {r.json()['token']}"}
        r = self.client.post("/api/attendance/clock-in/", {"work_mode": "field", "field_type": "onshore"},
                             content_type="application/json", **h)
        self.assertEqual(r.json()["attendance"]["work_mode"], "field")
        self.assertEqual(r.json()["attendance"]["field_type"], "onshore")
        self.assertEqual(self.client.get("/api/leave-balance/", **h).json()["totals"]["credit"],
                         services.plain(services.leave_balances(self.emp("arun"), date.today().year)["totals"]["credit"]))
        d = self.client.get("/api/dashboard/", **h).json()
        self.assertEqual(d["designation"], "Survey Supervisor")


class V6FeatureTests(TestCase):
    """Holidays, CL / LOP, project members + daily progress, notifications, date format."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def emp(self, username):
        return Employee.objects.get(user__username=username)

    def login(self, username, password):
        self.assertTrue(self.client.login(username=username, password=password))

    # ---- holidays
    def test_second_saturday_sunday_and_government_holiday_are_off(self):
        self.assertEqual(services.off_reason(date(2026, 3, 14), {}), "2nd Saturday")
        self.assertIsNone(services.off_reason(date(2026, 3, 7), {}))    # 1st Saturday works
        self.assertEqual(services.off_reason(date(2026, 3, 15), {}), "Sunday")
        Holiday.objects.create(date=date(2026, 3, 18), name="Test Day")
        self.assertEqual(services.working_days_between(date(2026, 3, 16), date(2026, 3, 20)), 4)

    def test_only_admin_can_declare_company_holiday(self):
        self.login("arun", "arun123")
        self.assertEqual(self.client.post(reverse("holiday_today"), {"name": "x"}).status_code, 403)
        self.client.logout()
        self.login("admin", "admin123")
        self.client.post(reverse("holiday_today"), {"name": "Cyclone"})
        h = Holiday.objects.get(date=date.today())
        self.assertEqual((h.kind, h.name), ("company", "Cyclone"))
        self.assertEqual(services.today_holiday(), "Cyclone")
        self.client.post(reverse("holiday_today"), {"action": "cancel"})
        self.assertFalse(Holiday.objects.filter(date=date.today(), kind="company").exists())

    # ---- leave: CL 1.5 / month, then LOP
    def test_casual_leave_then_lop(self):
        arun = self.emp("arun")
        casual = LeaveType.objects.get(name="Casual Leave")
        lop = LeaveType.objects.get(name="Loss of Pay")
        LeaveRequest.objects.filter(employee=arun).delete()
        today = date.today()
        months = services.months_credited(arun, today.year)
        bal = services.leave_balances(arun, today.year)
        cl = next(r for r in bal["rows"] if r["type"] == casual)
        self.assertEqual(cl["credit"], Decimal("1.5") * months)
        self.assertTrue(next(r for r in bal["rows"] if r["type"] == lop)["unlimited"])
        # more CL than the credit -> error that points to LOP; LOP itself is never limited
        d = date(today.year, today.month, 1)
        while d.weekday() != 0:
            d += timedelta(days=1)
        end = d + timedelta(days=int(cl["credit"]) * 2 + 10)
        if end.year == d.year:
            msg = services.validate_leave(arun, casual, d, end)
            self.assertIn("Loss of Pay", msg or "")
            self.assertIsNone(services.validate_leave(arun, lop, d, end))
        # half day = 0.5
        half = services.leave_days_for(d, d, True)
        self.assertEqual(half, Decimal("0.5"))

    def test_leave_overview_lists_people_without_leave(self):
        LeaveRequest.objects.all().delete()
        ov = services.leave_overview()
        self.assertEqual(len(ov["no_leave"]), len(ov["rows"]))
        self.login("hr", "hr12345")
        self.assertContains(self.client.get(reverse("leave_list")), "No leave taken")

    # ---- projects: members + office/field, daily progress, automatic %
    def test_project_needs_member_and_work_type(self):
        self.login("admin", "admin123")
        a, b = self.emp("arun"), self.emp("priya")
        # step 1: only the project title and the details of work are compulsory
        r = self.client.post(reverse("project_create"), {"name": "", "description": "", "status": "inprogress", "completion": 0})
        self.assertContains(r, "Enter the project title")
        self.assertContains(r, "Enter the details of work")
        r = self.client.post(reverse("project_create"), {
            "name": "Two", "description": "Survey two bays", "status": "inprogress", "completion": 0,
            "start_date": "2026-03-02", "end_date": "2026-03-13"})
        p = Project.objects.get(name="Two")
        self.assertEqual((p.client, p.project_code), ("", ""))                 # optional
        self.assertRedirects(r, reverse("project_assign", args=[p.pk]))
        # step 2: members + work type
        r = self.client.post(reverse("project_assign", args=[p.pk]), {})
        self.assertContains(r, "at least one member")
        r = self.client.post(reverse("project_assign", args=[p.pk]), {"employees": [a.pk]})
        self.assertContains(r, "choose Office work or Field work")
        r = self.client.post(reverse("project_assign", args=[p.pk]), {
            "employees": [a.pk, b.pk], f"mode_{a.pk}": "field", f"ftype_{a.pk}": "offshore", f"mode_{b.pk}": "office"})
        self.assertRedirects(r, reverse("notifications"))     # link mode -> WhatsApp buttons page
        self.assertEqual(ProjectAssignment.objects.get(project=p, employee=a).work_mode, "field")
        self.assertEqual(Notification.objects.filter(kind="project", recipient__in=[a, b]).count(), 2)

    def test_project_client_code_and_100_word_limit(self):
        self.login("admin", "admin123")
        r = self.client.post(reverse("project_create"), {
            "name": "Coded", "client": "Acme Marine", "project_code": "PRJ-001", "description": "word " * 101,
            "status": "inprogress", "completion": 0})
        self.assertContains(r, "within 100 words")
        r = self.client.post(reverse("project_create"), {
            "name": "Coded", "client": "Acme Marine", "project_code": "PRJ-001", "description": "word " * 100,
            "status": "inprogress", "completion": 0})
        self.assertEqual(r.status_code, 302)
        p = Project.objects.get(name="Coded")
        self.assertEqual((p.client, p.project_code), ("Acme Marine", "PRJ-001"))
        self.assertContains(self.client.get(reverse("project_list")), "PRJ-001")
        # a member's work description is limited too
        a = self.emp("arun")
        r = self.client.post(reverse("project_assign", args=[p.pk]), {
            "employees": [a.pk], f"mode_{a.pk}": "office", f"work_{a.pk}": "word " * 101})
        self.assertContains(r, "keep it within 100")

    def test_daily_update_drives_project_percentage_and_completed_list(self):
        p = Project.objects.create(name="Prog", start_date=date.today() - timedelta(days=3))
        a, b = self.emp("arun"), self.emp("priya")
        p.employees.set([a, b])
        services.sync_assignments(p, [a, b], {a.pk: "office", b.pk: "field"})
        self.login("arun", "arun123")
        self.client.post(reverse("project_update", args=[p.pk]), {"percent": 60, "note": "survey done"})
        p.refresh_from_db()
        self.assertEqual(p.completion, 30)                     # (60 + 0) / 2 members
        self.client.logout()
        self.login("priya", "priya123")
        self.client.post(reverse("project_update", args=[p.pk]), {"percent": 100})
        self.client.logout()
        self.login("arun", "arun123")
        self.client.post(reverse("project_update", args=[p.pk]), {"percent": 100, "note": "survey done"})
        p.refresh_from_db()
        self.assertEqual((p.completion, p.status), (100, "completed"))
        self.assertEqual(ProjectUpdate.objects.filter(project=p).count(), 2)  # one row per person per day
        # completed project is listed under completed on the employee's project page, admin sees the updates
        self.assertContains(self.client.get(reverse("project_list")), "completed projects")
        self.client.logout()
        self.login("admin", "admin123")
        self.assertContains(self.client.get(reverse("project_detail", args=[p.pk])), "survey done")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_leave_inside_assignment_is_not_counted(self):
        a = self.emp("arun")
        LeaveRequest.objects.filter(employee=a).delete()
        p = Project.objects.create(name="Ten", start_date=date(2026, 3, 2), end_date=date(2026, 3, 13))
        p.employees.set([a])
        services.sync_assignments(p, [a], {a.pk: "office"}, is_new=True)
        casual = LeaveType.objects.get(name="Casual Leave")
        LeaveRequest.objects.create(employee=a, leave_type=casual, start_date=date(2026, 3, 6),
                                    end_date=date(2026, 3, 6), status="approved")
        row = services.project_metrics(p, today=date(2026, 4, 1))["rows"][0]
        self.assertEqual((row["span_days"], row["leave_days"], row["net_days"]), (11, 1, 10))

    # ---- notifications / WhatsApp link
    def test_whatsapp_link_and_phone(self):
        from . import notifications
        self.assertEqual(notifications.normalize_phone("98765 43210"), "919876543210")
        self.assertTrue(notifications.wa_link("9876543210", "hi there").startswith("https://wa.me/919876543210?text=hi"))
        self.assertEqual(notifications.normalize_phone(""), "")

    # ---- display rules
    def test_date_format_title_and_code(self):
        self.login("arun", "arun123")
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, "EMP003")
        self.assertContains(r, "Survey Supervisor")
        self.assertNotContains(r, ">Employee<")
        self.assertRegex(r.content.decode(), r"\d{2}-[A-Z][a-z]{2}-\d{4}")
        self.client.logout()
        self.login("hr", "hr12345")
        r = self.client.get(reverse("employee_list"))
        self.assertContains(r, "Attendance")
        for name in ("holiday_list", "notifications", "holiday_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


# ---------------------------------------------------------------- v7: speed, no-reload (Turbo), member search
class V7SpeedAndTurboTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        desig = Designation.objects.first()
        for i in range(25):
            u = User.objects.create_user(f"bulk{i}", password="x", first_name=f"Bulk{i}")
            Employee.objects.create(user=u, designation=desig)

    def queries(self, name, *args):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse(name, args=args))
        self.assertEqual(resp.status_code, 200, name)
        return len(ctx)

    def test_manager_pages_use_a_fixed_number_of_queries(self):
        """With 28+ employees the pages still need only a handful of database round trips.
        (Before v7 the Admin home needed ~150 - one set per employee - which is what made a hosted
        PostgreSQL feel slow.)"""
        self.assertTrue(self.client.login(username="admin", password="admin123"))
        self.assertLess(self.queries("dashboard"), 25)
        self.assertLess(self.queries("attendance_list"), 15)
        self.assertLess(self.queries("leave_list"), 15)
        self.assertLess(self.queries("employee_list"), 12)
        self.assertLess(self.queries("project_list"), 20)

    def test_bulk_summaries_match_single_employee_summaries(self):
        from datetime import date as d

        from . import services

        emps = list(Employee.objects.select_related("user"))
        start, end, today = d(2026, 10, 1), d(2026, 10, 31), d(2026, 10, 27)
        bulk = services.bulk_period_summaries(emps, start, end, today)
        for e in emps:
            self.assertEqual(bulk[e.pk], services.period_summary(e, start, end, today), e.employee_id)

    def test_leave_overview_matches_per_employee_balances(self):
        from . import services

        ov = services.leave_overview(2026)
        for row in ov["rows"]:
            single = services.leave_balances(row["employee"], 2026)["totals"]
            self.assertEqual(row["credit"], single["credit"])
            self.assertEqual(row["balance"], single["balance"])

    def test_turbo_form_errors_come_back_as_422(self):
        """Turbo only re-draws a submitted form when the status is 4xx; plain browsers still get 200."""
        self.assertTrue(self.client.login(username="hr", password="hr12345"))
        url = reverse("employee_create")
        turbo = {"HTTP_ACCEPT": "text/vnd.turbo-stream.html, text/html, application/xhtml+xml"}
        self.assertEqual(self.client.post(url, {}, **turbo).status_code, 422)
        self.assertEqual(self.client.post(url, {}).status_code, 200)

    def test_turbo_wrong_password_shows_the_login_page_again(self):
        turbo = {"HTTP_ACCEPT": "text/vnd.turbo-stream.html, text/html, application/xhtml+xml"}
        r = self.client.post(reverse("login"), {"username": "arun", "password": "nope"}, **turbo)
        self.assertEqual(r.status_code, 422)
        self.assertContains(r, "Sign in", status_code=422)

    def test_pages_load_turbo_and_scripts_once_in_the_head(self):
        self.assertTrue(self.client.login(username="admin", password="admin123"))
        html = self.client.get(reverse("dashboard")).content.decode()
        head = html.split("</head>")[0]
        self.assertIn("@hotwired/turbo", head)
        self.assertIn("js/app.js", head)
        self.assertNotIn("<script", html.split("</head>")[1])  # nothing re-run on every Turbo visit

    def test_project_form_has_member_search(self):
        self.assertTrue(self.client.login(username="admin", password="admin123"))
        p = Project.objects.create(name="Picker test", description="x")
        r = self.client.get(reverse("project_assign", args=[p.pk]))
        self.assertContains(r, "data-member-search")
        self.assertContains(r, "data-member-count")
        self.assertContains(r, 'data-search="EMP')   # every row carries code / name / designation to search on
        self.assertContains(r, "Bulk7")

    def test_next_redirect_never_leaves_the_site(self):
        from .models import LeaveRequest, LeaveType

        self.assertTrue(self.client.login(username="hr", password="hr12345"))
        emp = Employee.objects.get(user__username="arun")
        from datetime import date as d, timedelta

        start = d.today() + timedelta(days=40)
        while start.weekday() >= 5:
            start += timedelta(days=1)
        leave = LeaveRequest.objects.create(employee=emp, leave_type=LeaveType.objects.first(), start_date=start,
                                            end_date=start)
        r = self.client.post(reverse("leave_decide", args=[leave.pk]), {"action": "reject", "next": "https://evil.example/"})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("evil.example", r["Location"])



class V8FeatureTests(TestCase):
    """Permission transfer, department groups, dashboard changes, optional completion."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("seed_demo", verbosity=0)

    def login(self, u, p):
        self.client.login(username=u, password=p)

    def test_transfer_gives_hr_permissions_only_for_leave_days(self):
        from .models import PermissionTransfer
        hr = Employee.objects.get(user__username="hr")
        arun = Employee.objects.get(user__username="arun")
        today = date.today()
        casual = LeaveType.objects.get(name="Casual Leave")
        leave = LeaveRequest.objects.create(employee=hr, leave_type=casual, start_date=today, end_date=today,
                                            status="approved")
        self.assertNotIn("leave", services.get_perms(arun.user))
        self.login("hr", "hr12345")
        r = self.client.post(reverse("leave_transfer", args=[leave.pk]), {"to_employee": arun.pk, "perms": ["leave"]})
        self.assertEqual(r.status_code, 302)
        got = services.get_perms(arun.user)
        self.assertIn("leave", got)                                         # ticked -> handed over
        self.assertNotIn("attendance", got)                                 # not ticked -> not handed over
        leave.end_date = today + timedelta(days=2); leave.save()          # leave dates change -> transfer follows
        self.assertEqual(PermissionTransfer.objects.get().end_date, today + timedelta(days=2))
        PermissionTransfer.objects.update(start_date=today - timedelta(days=3), end_date=today - timedelta(days=2))
        self.assertNotIn("leave", services.get_perms(arun.user))   # expired -> back to normal

    def test_group_create_and_message(self):
        from .models import Group, GroupMessage, Notification
        arun = Employee.objects.get(user__username="arun")
        priya = Employee.objects.get(user__username="priya")
        self.login("admin", "admin123")
        r = self.client.post(reverse("group_create"), {"name": "Field crew", "members": [arun.pk, priya.pk]})
        self.assertEqual(r.status_code, 302)
        g = Group.objects.get(name="Field crew")
        self.assertEqual(g.members.count(), 2)
        r = self.client.post(reverse("group_detail", args=[g.pk]), {"message": "Meeting at 5"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(GroupMessage.objects.filter(group=g).count(), 1)
        self.assertTrue(Notification.objects.filter(recipient=arun, kind="group").exists())
        self.assertTrue(Notification.objects.filter(recipient=priya, kind="group").exists())
        # an ordinary employee can open Chat, sees only the groups they are in and can reply ...
        other = Group.objects.create(name="Private")
        self.login("arun", "arun123")
        page = self.client.get(reverse("group_list"))
        self.assertContains(page, "Field crew")
        self.assertNotContains(page, "Private")
        self.assertNotContains(page, "New Group")
        self.assertEqual(self.client.get(reverse("group_detail", args=[other.pk])).status_code, 404)
        r = self.client.post(reverse("group_detail", args=[g.pk]), {"message": "On my way"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(GroupMessage.objects.filter(group=g).count(), 2)
        # ... but cannot create, edit or delete groups without the permission
        self.assertEqual(self.client.get(reverse("group_create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("group_edit", args=[g.pk]), {"name": "x", "members": [arun.pk]}).status_code, 403)
        self.assertEqual(self.client.get(reverse("group_delete", args=[g.pk])).status_code, 403)
        # give this person the groups permission -> allowed
        arun.can_manage_groups = True
        arun.save()
        self.assertEqual(self.client.get(reverse("group_create")).status_code, 200)
        self.assertContains(self.client.get(reverse("group_list")), "New Group")

    def test_admin_dashboard_texts_and_no_admin_in_employee_list(self):
        self.login("admin", "admin123")
        body = self.client.get("/").content.decode()
        for text in ("Total employees", "Absent today", "Departments", "Employees today status", "Location"):
            self.assertIn(text, body)
        for text in ("Pending leave requests", "Attendance of everyone"):
            self.assertNotIn(text, body)
        self.assertNotIn("EMP001", self.client.get(reverse("employee_list")).content.decode())

    def test_project_completion_is_optional(self):
        arun = Employee.objects.get(user__username="arun")
        self.login("admin", "admin123")
        r = self.client.post(reverse("project_create"), {
            "name": "No percent", "description": "Map it", "status": "inprogress", "completion": ""})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse("project_assign", args=[Project.objects.get(name="No percent").pk]), {
            "employees": [arun.pk], f"mode_{arun.pk}": "office", f"work_{arun.pk}": "Map the bay", f"days_{arun.pk}": "9",
        })
        self.assertEqual(r.status_code, 302)
        from .models import ProjectAssignment
        a = ProjectAssignment.objects.get(project__name="No percent")
        self.assertEqual((a.work_description, a.assigned_days), ("Map the bay", 9))


class V9FeatureTests(TestCase):
    """v9: On shore / Off shore for field work, no holiday card on the admin home, ajax fragments, chat page."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def login(self, u, p):
        self.assertTrue(self.client.login(username=u, password=p))

    def emp(self, username):
        return Employee.objects.get(user__username=username)

    # ---- field work -> On shore / Off shore
    def test_clock_in_field_needs_on_or_off_shore(self):
        self.login("arun", "arun123")
        self.client.post(reverse("clock_in"), {"work_mode": "field"})
        self.assertFalse(Attendance.objects.filter(employee=self.emp("arun"), date=timezone.localdate()).exists())
        self.client.post(reverse("clock_in"), {"work_mode": "field", "field_type": "onshore"})
        rec = Attendance.objects.get(employee=self.emp("arun"), date=timezone.localdate())
        self.assertEqual((rec.work_mode, rec.field_type), ("field", "onshore"))
        self.assertEqual(rec.location_label, "Field (On shore)")
        self.assertContains(self.client.get("/"), "Field (On shore)")

    def test_office_clock_in_ignores_field_type(self):
        self.login("priya", "priya123")
        self.client.post(reverse("clock_in"), {"work_mode": "office", "field_type": "offshore"})
        rec = Attendance.objects.get(employee=self.emp("priya"), date=timezone.localdate())
        self.assertEqual((rec.work_mode, rec.field_type, rec.location_label), ("office", "", "Office"))

    def test_attendance_form_field_work_needs_type(self):
        self.login("admin", "admin123")
        data = {"employee": self.emp("arun").pk, "date": "2026-02-03", "in_time": "09:00", "work_mode": "field"}
        r = self.client.post(reverse("attendance_create"), data)
        self.assertContains(r, "choose On shore or Off shore")
        r = self.client.post(reverse("attendance_create"), {**data, "field_type": "onshore"})
        self.assertEqual(r.status_code, 302)
        page = self.client.get(reverse("attendance_list") + "?period=month&month=2026-02")
        self.assertContains(page, "Field (On shore)")

    def test_project_field_member_needs_type_and_shows_it(self):
        self.login("admin", "admin123")
        a = self.emp("arun")
        self.client.post(reverse("project_create"), {"name": "Shore job", "description": "Dive survey", "status": "inprogress", "completion": 0})
        from .models import Project, ProjectAssignment
        proj = Project.objects.get(name="Shore job")
        url = reverse("project_assign", args=[proj.pk])
        base = {"employees": [a.pk], f"mode_{a.pk}": "field"}
        self.assertContains(self.client.post(url, base), "choose On shore or Off shore")
        r = self.client.post(url, {**base, f"ftype_{a.pk}": "offshore"})
        self.assertEqual(r.status_code, 302)
        asg = ProjectAssignment.objects.get(project=proj)
        self.assertEqual((asg.work_mode, asg.field_type, asg.location_label), ("field", "offshore", "Field (Off shore)"))
        self.assertContains(self.client.get(reverse("project_list")), "Field (Off shore)")
        self.assertContains(self.client.get(reverse("project_detail", args=[proj.pk])), "Field (Off shore)")
        # changing the member to office clears the shore type
        r = self.client.post(url, {**base, f"mode_{a.pk}": "office"})
        self.assertEqual(r.status_code, 302)
        asg.refresh_from_db()
        self.assertEqual((asg.work_mode, asg.field_type), ("office", ""))

    # ---- admin home: the "today company holiday" card is gone
    def test_admin_home_has_no_today_holiday_card(self):
        self.login("admin", "admin123")
        body = self.client.get("/").content.decode()
        for text in ("Today company holiday", "Cancel today's company holiday", "Today is a working day"):
            self.assertNotIn(text, body)
        self.assertIn("Employees today status", body)

    # ---- ajax: only the content comes back
    def test_ajax_fragment_is_small_and_has_region(self):
        self.login("admin", "admin123")
        full = self.client.get(reverse("employee_list") + "?q=a")
        frag = self.client.get(reverse("employee_list") + "?q=a", HTTP_X_REQUESTED_WITH="fetch")
        self.assertContains(full, "app-header")
        self.assertNotContains(frag, "app-header")
        self.assertNotContains(frag, "sidebar")
        self.assertContains(frag, 'id="ajax-region"')
        self.assertEqual(frag["Cache-Control"], "no-store")
        self.assertIn("X-Requested-With", frag["Vary"])
        self.assertLess(len(frag.content), len(full.content))

    def test_ajax_search_returns_only_matching_rows(self):
        self.login("admin", "admin123")
        frag = self.client.get(reverse("employee_list") + "?q=arun", HTTP_X_REQUESTED_WITH="fetch")
        self.assertContains(frag, "Arun")
        self.assertNotContains(frag, "Priya")

    def test_every_list_page_has_ajax_region_and_scroll_table(self):
        self.login("admin", "admin123")
        for name in ("dashboard", "employee_list", "project_list", "attendance_list", "leave_list", "group_list"):
            body = self.client.get(reverse(name)).content.decode()
            self.assertIn('id="ajax-region"', body, name)
            self.assertIn("fancy-table", body) if name != "group_list" else None

    # ---- chat (groups)
    def test_chat_ui_labels_and_message_ajax_post(self):
        from .models import Group, GroupMessage
        self.login("admin", "admin123")
        arun, priya = self.emp("arun"), self.emp("priya")
        g = Group.objects.create(name="Field crew")
        g.members.set([arun, priya])
        body = self.client.get("/").content.decode()
        self.assertIn(">Chat</span>", body)
        self.assertNotIn(">Groups</span>", body)
        r = self.client.post(reverse("group_detail", args=[g.pk]), {"message": "Meeting at 5"}, HTTP_X_REQUESTED_WITH="fetch",
                             follow=True)
        self.assertContains(r, "Meeting at 5")
        self.assertContains(r, "bubble-row me")
        self.assertEqual(GroupMessage.objects.filter(group=g).count(), 1)
        page = self.client.get(reverse("group_detail", args=[g.pk])).content.decode()
        self.assertIn("Open chat", page)
        self.assertNotIn("Open WhatsApp", page)

    # ---- header icons
    def test_header_has_theme_and_logout_icons(self):
        self.login("arun", "arun123")
        body = self.client.get("/").content.decode()
        self.assertIn("data-theme-toggle", body)
        self.assertIn('aria-label="Logout"', body)
        self.assertIn("#i-moon", body)
        self.assertIn("#i-sun", body)

    # ---- v10 -----------------------------------------------------------------------------------------
    def _clean_emp(self):
        from .models import Attendance, LeaveRequest
        emp = Employee.objects.get(user__username="vijay")
        Attendance.objects.filter(employee=emp).delete()
        LeaveRequest.objects.filter(employee=emp).delete()
        return emp

    def test_v10_working_days_add_up_with_today_pending(self):
        from . import services
        emp = self._clean_emp()
        mon = date(2026, 3, 2)
        # Mon..Wed are over, Thursday (3 days later) is "today" and nobody has clocked in
        s_ = services.period_summary(emp, mon, mon + timedelta(days=6), today=mon + timedelta(days=3))
        self.assertEqual(s_["working_days"], 4)
        self.assertEqual(s_["absent"], 3)
        self.assertEqual(s_["pending"], 1)
        self.assertEqual(s_["present"] + s_["leave"] + s_["absent"] + s_["pending"], s_["working_days"])

    def test_v10_field_days_split_on_shore_off_shore(self):
        from . import services
        from .models import Attendance
        emp = self._clean_emp()
        mon = date(2026, 3, 2)
        Attendance.objects.create(employee=emp, date=mon, in_time=time(9), work_mode="field", field_type="onshore")
        Attendance.objects.create(employee=emp, date=mon + timedelta(days=1), in_time=time(9), work_mode="field", field_type="offshore")
        Attendance.objects.create(employee=emp, date=mon + timedelta(days=2), in_time=time(9), work_mode="office")
        s_ = services.period_summary(emp, mon, mon + timedelta(days=6), today=mon + timedelta(days=7))
        self.assertEqual((s_["field"], s_["field_on"], s_["field_off"], s_["office"]), (2, 1, 1, 1))
        self.login("admin", "admin123")
        page = self.client.get(reverse("employee_detail", args=[emp.pk]) + "?tab=attendance&period=month&month=2026-03")
        self.assertContains(page, "On shore 1")
        self.assertContains(page, "Off shore 1")
        self.assertContains(page, "pill-green")            # present days are green

    def test_v10_absent_day_blinks(self):
        emp = self._clean_emp()
        self.login("admin", "admin123")
        page = self.client.get(reverse("employee_detail", args=[emp.pk]) + "?tab=attendance&period=month&month=2026-03")
        self.assertContains(page, "pill-red blink-slow")

    def test_v10_frozen_header_and_notification_wrap_css(self):
        import pathlib
        css = (pathlib.Path(__file__).resolve().parent.parent / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("position: fixed !important; top: 8px", css)
        self.assertIn(".notif-table", css)
        self.assertIn("overflow-wrap: anywhere", css)

    def test_v10_today_company_holiday_bar_is_hidden(self):
        self.login("admin", "admin123")
        body = self.client.get(reverse("holiday_list")).content.decode()
        for text in ("Today company holiday", "Today is a working day", "Cancel today's company holiday"):
            self.assertNotIn(text, body)

    # ---- v11 -----------------------------------------------------------------------------------------
    def _mk(self, username, first, desig, dept=None):
        from django.contrib.auth import get_user_model
        from .models import Department, Designation
        from .hierarchy import rank_for, department_sort_order
        u = get_user_model().objects.create_user(username=username, password="x12345", first_name=first)
        d, _ = Designation.objects.get_or_create(name=desig)
        d.rank = rank_for(desig)
        d.save()
        dp = None
        if dept:
            dp, _ = Department.objects.get_or_create(name=dept, defaults={"sort_order": department_sort_order(dept)})
        return Employee.objects.create(user=u, designation=d, department=dp)

    # (v16: the employee table is grouped by department, best attendance % first - old order test removed)

    def test_v13_bulk_delete(self):
        a, b = self._mk("zz_x", "Xray", "Project Officer"), self._mk("zz_y", "Yankee", "Project Officer")
        admin_emp = Employee.objects.get(user__username="admin")
        self.login("priya", "priya123")
        self.assertEqual(self.client.post(reverse("employee_bulk_delete"), {"ids": [a.pk]}).status_code, 403)
        self.login("admin", "admin123")
        r = self.client.post(reverse("employee_bulk_delete"), {"ids": [a.pk, b.pk, admin_emp.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Employee.objects.filter(pk__in=[a.pk, b.pk]).exists())
        self.assertTrue(Employee.objects.filter(pk=admin_emp.pk).exists())          # never your own account
        page = self.client.get(reverse("employee_list")).content.decode()
        self.assertIn("data-select-all", page)

    def test_v13_permissions_belong_to_the_person_not_the_designation(self):
        from . import services
        a, b = self._mk("zz_p1", "Pone", "Project Officer"), self._mk("zz_p2", "Ptwo", "Project Officer")
        a.can_manage_leave = True
        a.save()
        self.assertEqual(services.perms_of_employee(Employee.objects.get(pk=a.pk)), {"leave"})
        self.assertEqual(services.perms_of_employee(Employee.objects.get(pk=b.pk)), set())     # same designation, no permission
        self.login("admin", "admin123")
        page = self.client.get(reverse("employee_edit", args=[a.pk])).content.decode()
        self.assertIn("can_manage_leave", page)
        self.assertIn("display_priority", page)
        self.assertNotIn("can_manage_leave", self.client.get(reverse("designation_create")).content.decode())

    def test_v13_leave_goes_to_the_chosen_approver_and_applicant_is_told(self):
        from .models import LeaveRequest, LeaveType, Notification
        boss1, boss2 = self._mk("zz_b1", "Bossone", "Director"), self._mk("zz_b2", "Bosstwo", "Director")
        boss1.can_manage_leave = True
        boss1.save()
        boss2.can_manage_leave = True
        boss2.save()
        arun = Employee.objects.get(user__username="arun")
        cl = LeaveType.objects.get(name="Casual Leave")
        self.login("arun", "arun123")
        page = self.client.get(reverse("leave_create")).content.decode()
        self.assertIn("Bossone", page)
        self.assertIn("Bosstwo", page)
        body = {"leave_type": cl.pk, "start_date": "2026-12-14", "end_date": "2026-12-14", "reason": "family"}
        self.assertContains(self.client.post(reverse("leave_create"), body), "Send leave request to")   # must choose
        r = self.client.post(reverse("leave_create"), {**body, "approver": boss1.pk})
        self.assertEqual(r.status_code, 302)
        leave = LeaveRequest.objects.get(employee=arun, approver=boss1)
        self.assertTrue(Notification.objects.filter(recipient=boss1, kind="leave").exists())
        self.assertFalse(Notification.objects.filter(recipient=boss2, kind="leave").exists())      # not asked
        # the other approver cannot decide it, the chosen one can; the applicant is told
        self.login("zz_b2", "x12345")
        self.assertEqual(self.client.post(reverse("leave_decide", args=[leave.pk]), {"action": "approve"}).status_code, 403)
        self.assertNotContains(self.client.get(reverse("leave_list")), "family")
        self.login("zz_b1", "x12345")
        self.assertEqual(self.client.get(reverse("leave_list")).status_code, 200)
        self.assertEqual(self.client.post(reverse("leave_decide", args=[leave.pk]), {"action": "reject"}).status_code, 302)
        leave.refresh_from_db()
        self.assertEqual(leave.status, "rejected")
        self.assertTrue(Notification.objects.filter(recipient=arun, kind="leave", message__contains="declined").exists())

    # ---- v14 -----------------------------------------------------------------------------------------
    def _employee_post(self, **extra):
        data = {"employee_id": "EMP950", "username": "v14user", "first_name": "Vee", "password": "pass12345",
                "status": "active", "role": "employee", "blood_group": "B+", "phone": "9876543210",
                "email": "vee@example.com"}
        data.update(extra)
        return self.client.post(reverse("employee_create"), data)

    def test_v14_only_five_fields_are_compulsory(self):
        self.login("hr", "hr12345")
        r = self.client.post(reverse("employee_create"), {"username": "x", "password": "pass12345", "status": "active", "role": "employee"})
        for msg in ("Enter the employee ID", "Enter the name", "Enter the contact number", "Enter the mail id", "Select the blood group"):
            self.assertContains(r, msg, status_code=200)
        r = self._employee_post()                                  # nothing else is needed
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)

    def test_v14_new_personal_details_are_saved_and_checked(self):
        self.login("hr", "hr12345")
        r = self._employee_post(
            emergency_name="Dad", emergency_relation="Father", emergency_phone="9000000001",
            emergency_name2="Mom", emergency_relation2="Mother", emergency_phone2="9000000002",
            permanent_address="1 Main St\nCoimbatore", current_address="2 Lake Rd", aadhaar_number="1234 5678 9012",
            pan_number="abcde1234f", vehicle_number="tn 38 ab 1234", doctor_name="Dr Ravi", doctor_phone="9444444444")
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        e = Employee.objects.get(user__username="v14user")
        self.assertEqual((e.emergency_name2, e.emergency_relation2, e.emergency_phone2), ("Mom", "Mother", "9000000002"))
        self.assertEqual((e.aadhaar_number, e.pan_number, e.vehicle_number), ("123456789012", "ABCDE1234F", "TN 38 AB 1234"))
        self.assertEqual((e.doctor_name, e.doctor_phone), ("Dr Ravi", "9444444444"))
        self.assertIn("Coimbatore", e.permanent_address)
        # wrong formats are refused
        self.assertContains(self._employee_post(username="b1", employee_id="EMP951", aadhaar_number="123"), "12 digits")
        self.assertContains(self._employee_post(username="b2", employee_id="EMP952", pan_number="12345"), "PAN number")
        self.assertContains(self._employee_post(username="b3", employee_id="EMP953", emergency_phone2="12"), "valid number")
        self.assertContains(self._employee_post(username="b4", employee_id="EMP954", emergency_name2="Only name"), "enter the contact number")

    # (v16: emergency contact 2 is always shown as "Phone number 2" - the old + button test was removed)

    def test_v14_employee_edits_own_details_but_not_code_or_name(self):
        self.login("priya", "priya123")
        me = self.emp("priya")
        page = self.client.get(reverse("my_profile_edit")).content.decode()
        self.assertIn("Edit my details", page)
        self.assertNotIn('name="employee_id"', page)
        self.assertNotIn('name="first_name"', page)
        r = self.client.post(reverse("my_profile_edit"), {
            "email": "priya.new@example.com", "phone": "9123456780", "blood_group": "A+", "current_address": "New flat",
            "vehicle_number": "TN 01 XY 9999", "doctor_name": "Dr S", "doctor_phone": "9333333333",
            # these must be ignored even if somebody posts them
            "employee_id": "HACK1", "first_name": "Hacker", "can_edit_employees": "on", "role": "admin"})
        self.assertRedirects(r, reverse("my_profile"))
        me.refresh_from_db()
        self.assertEqual((me.phone, me.blood_group, me.current_address, me.vehicle_number), ("9123456780", "A+", "New flat", "TN 01 XY 9999"))
        self.assertEqual(me.user.email, "priya.new@example.com")
        self.assertNotEqual(me.employee_id, "HACK1")
        self.assertNotEqual(me.user.first_name, "Hacker")
        self.assertFalse(me.can_edit_employees)
        self.assertEqual(me.role, "employee")

    def test_v14_aadhaar_and_pan_are_hidden_from_people_who_only_view(self):
        viewer, target = self.emp("arun"), self.emp("priya")
        Employee.objects.filter(pk=target.pk).update(aadhaar_number="123456789012", pan_number="ABCDE1234F")
        Employee.objects.filter(pk=viewer.pk).update(can_view_employees=True)
        self.login("arun", "arun123")
        page = self.client.get(reverse("employee_detail", args=[target.pk])).content.decode()
        self.assertIn("XXXX XXXX 9012", page)
        self.assertNotIn("1234 5678 9012", page)
        self.assertNotIn("ABCDE1234F", page)
        self.client.logout()
        self.login("hr", "hr12345")
        page = self.client.get(reverse("employee_detail", args=[target.pk])).content.decode()
        self.assertIn("1234 5678 9012", page)
        self.assertIn("ABCDE1234F", page)

    def test_v14_employee_view_create_edit_are_separate(self):
        p = self.emp("priya")
        self.login("priya", "priya123")
        self.assertEqual(self.client.get(reverse("employee_list")).status_code, 403)
        Employee.objects.filter(pk=p.pk).update(can_view_employees=True)
        self.assertEqual(self.client.get(reverse("employee_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("employee_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("employee_edit", args=[self.emp("arun").pk])).status_code, 403)
        Employee.objects.filter(pk=p.pk).update(can_create_employees=True)
        self.assertEqual(self.client.get(reverse("employee_create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("employee_edit", args=[self.emp("arun").pk])).status_code, 403)
        Employee.objects.filter(pk=p.pk).update(can_view_employees=False, can_create_employees=False, can_edit_employees=True)
        self.assertEqual(self.client.get(reverse("employee_edit", args=[self.emp("arun").pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("employee_list")).status_code, 200)       # edit includes view
        self.assertEqual(self.client.get(reverse("employee_create")).status_code, 403)

    def test_v14_project_create_edit_view_are_separate(self):
        pr = Project.objects.create(name="Alpha", description="x")
        p = self.emp("priya")
        self.login("priya", "priya123")
        self.assertEqual(self.client.get(reverse("project_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("project_edit", args=[pr.pk])).status_code, 403)
        # without View she only sees projects she is assigned to
        self.assertEqual(self.client.get(reverse("project_detail", args=[pr.pk])).status_code, 404)
        Employee.objects.filter(pk=p.pk).update(can_create_projects=True)
        self.assertEqual(self.client.get(reverse("project_create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("project_edit", args=[pr.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("project_delete", args=[pr.pk])).status_code, 403)
        # create: the NEW project can be given its first members, an existing team cannot be changed
        self.assertEqual(self.client.get(reverse("project_assign", args=[pr.pk])).status_code, 200)
        ProjectAssignment.objects.create(project=pr, employee=self.emp("arun"))
        self.assertEqual(self.client.get(reverse("project_assign", args=[pr.pk])).status_code, 403)
        Employee.objects.filter(pk=p.pk).update(can_create_projects=False, can_edit_projects=True)
        self.assertEqual(self.client.get(reverse("project_edit", args=[pr.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("project_assign", args=[pr.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("project_create")).status_code, 403)

    def test_v14_project_view_permission_shows_all_projects_otherwise_only_assigned(self):
        mine, other = Project.objects.create(name="MineProj", description="x"), Project.objects.create(name="OtherProj", description="x")
        ProjectAssignment.objects.create(project=mine, employee=self.emp("priya"))
        mine.employees.add(self.emp("priya"))
        self.login("priya", "priya123")
        body = self.client.get(reverse("project_list")).content.decode()
        self.assertIn("MineProj", body)
        self.assertNotIn("OtherProj", body)
        self.assertEqual(self.client.get(reverse("project_detail", args=[other.pk])).status_code, 404)
        Employee.objects.filter(user__username="priya").update(can_view_projects=True)
        body = self.client.get(reverse("project_list")).content.decode()
        self.assertIn("MineProj", body)
        self.assertIn("OtherProj", body)
        self.assertEqual(self.client.get(reverse("project_detail", args=[other.pk])).status_code, 200)
        self.assertNotIn(reverse("project_create"), body)       # view only: no Add button

    def test_v14_permissions_are_given_while_creating_the_employee(self):
        self.login("hr", "hr12345")
        page = self.client.get(reverse("employee_create")).content.decode()
        for name in ("can_view_employees", "can_create_employees", "can_edit_employees",
                     "can_view_projects", "can_create_projects", "can_edit_projects"):
            self.assertIn(f'name="{name}"', page)
        r = self._employee_post(can_create_projects="on", can_edit_employees="on")
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        e = Employee.objects.get(user__username="v14user")
        self.assertTrue(e.can_create_projects and e.can_view_projects)        # create includes view
        self.assertTrue(e.can_edit_employees and e.can_view_employees)
        self.assertFalse(e.can_edit_projects or e.can_create_employees)

    def test_v14_free_option_is_gone(self):
        self.assertFalse(hasattr(Employee, "attendance_free"))
        self.login("hr", "hr12345")
        self.assertNotContains(self.client.get(reverse("employee_create")), "attendance_free")
        md = self._mk("zz_md2", "Freeman", "Managing Director")
        rec, msg, ok = services.clock_in(md)           # everybody clocks in now
        self.assertTrue(ok)

    def test_v14_working_days_in_the_month_are_shown(self):
        arun = self.emp("arun")
        s = services.period_summary(arun, date(2026, 10, 1), date(2026, 10, 31), today=date(2026, 10, 10))
        hol = services.load_holidays(date(2026, 10, 1), date(2026, 10, 31))
        expected = sum(1 for d in services.daterange(date(2026, 10, 1), date(2026, 10, 31)) if services.off_reason(d, hol) is None)
        self.assertEqual(s["period_working_days"], expected)          # the whole of October, not only up to the 10th
        self.assertGreater(s["period_working_days"], s["working_days"])
        self.login("arun", "arun123")
        self.assertContains(self.client.get(reverse("dashboard") + "?period=month&month=2026-10"), "Working days in October 2026")

    def test_v14_leave_cover_gives_only_the_permissions_the_person_really_has(self):
        boss, deputy = self.emp("priya"), self.emp("vijay")
        Employee.objects.filter(pk=boss.pk).update(can_view_projects=True)       # View only
        lv = LeaveRequest.objects.create(employee=boss, leave_type=LeaveType.objects.get(name="Casual Leave"),
                                         start_date=date.today(), end_date=date.today(), status="approved")
        PermissionTransfer.objects.create(from_employee=boss, to_employee=deputy, leave=lv, start_date=date.today(),
                                          end_date=date.today(), perms="projects")
        perms = services.get_perms(deputy.user)
        self.assertIn("projects_view", perms)
        self.assertNotIn("projects_edit", perms)

    def test_v11_current_project_wording(self):
        self.login("admin", "admin123")
        body = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn("Current projects", body)
        self.assertNotIn("Projects running", body)

    # ---- v12: profile photo ---------------------------------------------------------------------------
    def test_v12_profile_photo_upload_show_remove(self):
        import base64
        from .models import EmployeePhoto
        arun, priya = Employee.objects.get(user__username="arun"), Employee.objects.get(user__username="priya")
        good = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"0" * 40).decode()
        self.login("arun", "arun123")
        url = reverse("employee_photo_save", args=[arun.pk])
        # junk is refused
        self.client.post(url, {"photo_data": "data:image/jpeg;base64," + base64.b64encode(b"not a jpeg").decode()})
        self.assertFalse(EmployeePhoto.objects.filter(employee=arun).exists())
        self.client.post(url, {"photo_data": "hello"})
        self.assertFalse(EmployeePhoto.objects.filter(employee=arun).exists())
        # own photo is saved and shown (profile, sidebar)
        self.assertEqual(self.client.post(url, {"photo_data": good}).status_code, 302)
        arun.refresh_from_db()
        self.assertIsNotNone(arun.photo_updated)
        r = self.client.get(reverse("employee_photo", args=[arun.pk]))
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/jpeg"))
        self.assertContains(self.client.get(reverse("my_profile")), reverse("employee_photo", args=[arun.pk]))
        # an ordinary employee cannot change somebody else's photo
        self.assertEqual(self.client.post(reverse("employee_photo_save", args=[priya.pk]), {"photo_data": good}).status_code, 403)
        self.assertFalse(EmployeePhoto.objects.filter(employee=priya).exists())
        # remove
        self.client.post(url, {"remove": "1"})
        arun.refresh_from_db()
        self.assertIsNone(arun.photo_updated)
        self.assertEqual(self.client.get(reverse("employee_photo", args=[arun.pk])).status_code, 404)
        # Admin can set anybody's photo
        self.login("admin", "admin123")
        self.assertEqual(self.client.post(reverse("employee_photo_save", args=[priya.pk]), {"photo_data": good}).status_code, 302)
        self.assertTrue(EmployeePhoto.objects.filter(employee=priya).exists())
        self.assertContains(self.client.get(reverse("employee_list")), reverse("employee_photo", args=[priya.pk]))


class PermissionsPageTests(TestCase):
    """Admin gives View / Create / Edit (and the other permissions) to each person on one page."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def emp(self, username):
        return Employee.objects.get(user__username=username)

    def test_designation_has_no_permission_fields(self):
        from .models import Designation
        names = {f.name for f in Designation._meta.get_fields()}
        self.assertFalse({n for n in names if n.startswith("can_")})

    def test_only_admin_and_hr_open_the_page(self):
        url = reverse("permissions")
        self.assertEqual(self.client.get(url).status_code, 302)                       # not logged in
        self.client.login(username="priya", password="priya123")
        self.assertEqual(self.client.get(url).status_code, 403)                       # normal employee
        self.client.login(username="arun", password="arun123")
        self.assertEqual(self.client.get(url).status_code, 403)                       # even with project permissions
        self.client.login(username="admin", password="admin123")
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "full access")                                          # Admin / HR rows are locked
        self.assertContains(r, 'name="p_%d_can_view_projects"' % self.emp("priya").pk)

    def test_admin_ticks_permissions_for_one_person(self):
        priya, vijay = self.emp("priya"), self.emp("vijay")
        self.client.login(username="admin", password="admin123")
        data = {"emp_ids": [priya.pk, vijay.pk],
                f"p_{priya.pk}_can_create_employees": "1",       # Create alone must also give View
                f"p_{priya.pk}_can_edit_projects": "1",
                f"p_{priya.pk}_can_manage_attendance": "1"}
        r = self.client.post(reverse("permissions"), data)
        self.assertEqual(r.status_code, 302)
        priya.refresh_from_db(); vijay.refresh_from_db()
        self.assertTrue(priya.can_create_employees and priya.can_view_employees and not priya.can_edit_employees)
        self.assertTrue(priya.can_edit_projects and priya.can_view_projects and not priya.can_create_projects)
        self.assertTrue(priya.can_manage_attendance)
        self.assertFalse(any(getattr(vijay, f) for f in ("can_view_employees", "can_view_projects", "can_manage_leave")))
        # the new permissions really work for Priya
        self.client.login(username="priya", password="priya123")
        self.assertEqual(self.client.get(reverse("employee_create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("employee_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("attendance_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("project_create")).status_code, 403)   # Create was not ticked

    def test_unticking_removes_permissions_and_admin_hr_rows_are_untouched(self):
        arun, hr = self.emp("arun"), self.emp("hr")
        self.assertTrue(arun.can_edit_projects)
        self.client.login(username="admin", password="admin123")
        self.client.post(reverse("permissions"), {"emp_ids": [arun.pk, hr.pk]})            # everything unticked
        arun.refresh_from_db(); hr.refresh_from_db()
        self.assertFalse(arun.can_view_projects or arun.can_create_projects or arun.can_edit_projects)
        self.assertTrue(hr.can_edit_employees)                      # HR is not an editable row: untouched
        self.client.login(username="arun", password="arun123")
        self.assertEqual(self.client.get(reverse("project_create")).status_code, 403)

    def test_employee_cannot_post_to_the_page(self):
        priya = self.emp("priya")
        self.client.login(username="priya", password="priya123")
        r = self.client.post(reverse("permissions"), {"emp_ids": [priya.pk], f"p_{priya.pk}_can_edit_employees": "1"})
        self.assertEqual(r.status_code, 403)
        priya.refresh_from_db()
        self.assertFalse(priya.can_edit_employees)

    def test_admin_and_hr_roles_can_open_every_manager_page(self):
        names = ["dashboard", "employee_list", "employee_create", "project_list", "project_create", "organization",
                 "department_create", "team_create", "designation_create", "leavetype_create", "attendance_list",
                 "attendance_create", "leave_list", "leave_create", "permissions", "group_list", "group_create",
                 "holiday_list", "notifications"]
        for who, pw in (("admin", "admin123"), ("hr", "hr12345")):
            self.client.login(username=who, password=pw)
            for name in names:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, f"{who} {name}")
        # Admin really holds every granular permission, not just the four old areas
        from . import services as sv
        admin_user = self.emp("admin").user
        self.assertTrue({"employees_view", "employees_create", "employees_edit",
                         "projects_view", "projects_create", "projects_edit", "leave", "attendance"} <= sv.get_perms(admin_user))


class V16Tests(TestCase):
    """Project locations, extra doctors, biometric punches, Employee ID wording."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def test_project_locations_are_optional_and_saved(self):
        self.client.login(username="admin", password="admin123")
        r = self.client.post(reverse("project_create"), {
            "name": "P1", "description": "work", "status": "inprogress"})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse("project_create"), {
            "name": "P2", "description": "work", "status": "inprogress",
            "location": "Chennai Port", "client_location": "Mumbai"})
        self.assertEqual(r.status_code, 302)
        p = Project.objects.get(name="P2")
        self.assertEqual((p.location, p.client_location), ("Chennai Port", "Mumbai"))
        self.assertContains(self.client.get(reverse("project_detail", args=[p.pk])), "Chennai Port")

    def test_extra_doctors_saved_and_shown(self):
        e = Employee.objects.get(user__username="priya")
        self.client.login(username="admin", password="admin123")
        r = self.client.get(reverse("employee_edit", args=[e.pk]))
        self.assertContains(r, "data-add-doctor")
        self.assertContains(r, "Employee ID")
        e.doctor_name2, e.doctor_phone2 = "Dr Ravi", "9876500000"
        e.save()
        self.assertContains(self.client.get(reverse("employee_detail", args=[e.pk])), "Dr Ravi")

    def test_biometric_json_punch_in_then_out(self):
        from .models import Attendance, BiometricDevice
        dev = BiometricDevice.objects.create(name="Gate")
        e = Employee.objects.get(user__username="priya")
        url = reverse("biometric_punch")
        day = "2026-03-02"
        h = {"HTTP_X_DEVICE_KEY": dev.api_key}
        self.assertEqual(self.client.post(url, {"employee_id": e.employee_id}, content_type="application/json").status_code, 401)
        r = self.client.post(url, {"employee_id": e.employee_id, "timestamp": f"{day} 09:05:00"}, content_type="application/json", **h)
        self.assertEqual(r.json()["in"], 1)
        r = self.client.post(url, {"employee_id": e.employee_id, "timestamp": f"{day} 09:05:30"}, content_type="application/json", **h)
        self.assertEqual(r.json()["ignored"], 1)                       # double scan
        r = self.client.post(url, {"punches": [{"employee_id": e.employee_id, "timestamp": f"{day} 18:10:00"},
                                               {"employee_id": "NOBODY", "timestamp": f"{day} 18:11:00"}]},
                             content_type="application/json", **h)
        self.assertEqual((r.json()["out"], r.json()["unknown"]), (1, 1))
        a = Attendance.objects.get(employee=e, date=date(2026, 3, 2))
        self.assertEqual((a.in_time, a.out_time), (time(9, 5), time(18, 10)))

    def test_biometric_numeric_id_and_late_backlog(self):
        from .models import Attendance, BiometricDevice
        dev = BiometricDevice.objects.create(name="Gate")
        e = Employee.objects.get(user__username="priya")
        n = int(e.employee_id.replace("EMP", ""))
        h = {"HTTP_X_DEVICE_KEY": dev.api_key}
        url = reverse("biometric_punch")
        # evening punch arrives first, morning punch (backlog) arrives later -> morning is still the In time
        self.client.post(url, {"employee_id": str(n), "timestamp": "2026-03-03 17:30:00"}, content_type="application/json", **h)
        self.client.post(url, {"employee_id": str(n), "timestamp": "2026-03-03 09:00:00"}, content_type="application/json", **h)
        a = Attendance.objects.get(employee=e, date=date(2026, 3, 3))
        self.assertEqual((a.in_time, a.out_time), (time(9, 0), time(17, 30)))

    def test_zkteco_adms_push(self):
        from .models import Attendance, BiometricDevice
        BiometricDevice.objects.create(name="ZK", serial="ABC123")
        e = Employee.objects.get(user__username="priya")
        self.assertEqual(self.client.get("/iclock/cdata?SN=WRONG").status_code, 403)
        self.assertEqual(self.client.get("/iclock/cdata?SN=ABC123&options=all").status_code, 200)
        body = f"{e.employee_id}\t2026-03-04 09:10:00\t0\t1\n{e.employee_id}\t2026-03-04 18:00:00\t1\t1\n"
        r = self.client.post("/iclock/cdata?SN=ABC123&table=ATTLOG", body, content_type="text/plain")
        self.assertEqual(r.status_code, 200)
        a = Attendance.objects.get(employee=e, date=date(2026, 3, 4))
        self.assertEqual((a.in_time, a.out_time), (time(9, 10), time(18, 0)))

    def test_biometric_page_is_for_admin_and_hr_only(self):
        url = reverse("biometric_list")
        self.client.login(username="priya", password="priya123")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.login(username="admin", password="admin123")
        r = self.client.post(url, {"name": "Main gate", "location": "HQ"}, follow=True)
        self.assertContains(r, "Main gate")
        self.assertContains(r, "X-Device-Key")

    def test_dob_emergency_and_doctor_details(self):
        e = Employee.objects.get(user__username="priya")
        self.client.login(username="admin", password="admin123")
        r = self.client.get(reverse("employee_edit", args=[e.pk]))
        for text in ("Date of birth", "Emergency contacts", "Phone number 1", "Phone number 2", "Doctor details"):
            self.assertContains(r, text)
        self.assertNotContains(r, "data-add-contact")
        e.date_of_birth, e.doctor_name, e.doctor_location = date(1995, 5, 4), "Dr A", "Coimbatore"
        e.save()
        r = self.client.get(reverse("employee_detail", args=[e.pk]))
        self.assertContains(r, "04-May-1995")
        self.assertContains(r, "Coimbatore")

    def test_medical_insurance_number(self):
        e = Employee.objects.get(user__username="priya")
        self.client.login(username="admin", password="admin123")
        self.assertContains(self.client.get(reverse("employee_edit", args=[e.pk])), "Medical insurance number")
        e.medical_insurance_number = "MI-12345"
        e.save()
        self.assertContains(self.client.get(reverse("employee_detail", args=[e.pk])), "MI-12345")

    def test_employee_list_grouped_by_department_best_first(self):
        from .models import Department, Attendance
        self.client.login(username="admin", password="admin123")
        r = self.client.get(reverse("employee_list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "dept-row")
        groups = r.context["dept_groups"]
        pcts = [g["percent"] for g in groups if g["name"] != "No department"]
        self.assertEqual(pcts, sorted(pcts, reverse=True))
