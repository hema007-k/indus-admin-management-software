from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
import base64
import re as _re
from django.http import Http404, HttpResponse

from . import notifications, services
from .forms import (
    AttendanceForm, DepartmentForm, DesignationForm, EmployeeForm, SelfProfileForm,
    GroupForm, HolidayForm, LeaveForm, LeaveTypeForm, PermissionTransferForm, PortalLoginForm, ProjectForm,
    ProjectMembersForm, TeamForm,
)
from .models import (
    Attendance, Department, Designation, Employee, EmployeePhoto, GroupMessage, Holiday, LeaveRequest, LeaveType, Notification,
    PermissionTransfer, Project, ProjectUpdate, Team, Group, BiometricDevice, BiometricPunch,
)


# ---------------------------------------------------------------- access control
def _deny(request):
    return render(request, "portal/forbidden.html", status=403)


def perm_required(*perms):
    """Person / role based access. Give one or more of: employees_view, employees_create, employees_edit,
    projects_view, projects_create, projects_edit, leave, attendance (any one of them is enough)."""

    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{reverse('login')}?next={request.get_full_path()}")
            if not any(services.can(request.user, p) for p in perms):
                return _deny(request)
            return view(request, *args, **kwargs)

        return wrapper

    return deco


def manager_required(view):
    """Admin / HR role only (used for things that hand out permissions)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.get_full_path()}")
        if not services.is_manager(request.user):
            return _deny(request)
        return view(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------- login pages
class PortalLoginView(auth_views.LoginView):
    """One login page for everybody: Admin, HR and employees."""
    template_name = "portal/login.html"
    redirect_authenticated_user = True


employee_login = PortalLoginView.as_view(authentication_form=PortalLoginForm)
admin_login = employee_login          # the old /admin-login/ address now simply opens the same page


# ---------------------------------------------------------------- helpers
def _safe_next(request, default):
    """Where to go after a button press: a page name or a path on this site, never another website."""
    nxt = request.POST.get("next") or ""
    if nxt and (nxt in {"dashboard", "leave_list", "holiday_list", "project_list", "notifications"}):
        return nxt
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return default


def paginate(request, items, per=15, param="page"):
    """Page of `items` + the query string (without the page number) for the Previous / Next links.

    Every long list is paged so a page only builds and sends the rows you can see."""
    page = Paginator(items, per).get_page(request.GET.get(param))
    q = request.GET.copy()
    q.pop(param, None)
    return page, q.urlencode()


def _period(request):
    return services.parse_period(request.GET)


def _employee_overview(emp, period):
    """Everything the personal pages show: attendance summary, daily/monthly rows, leave credit, projects."""
    today = timezone.localdate()
    # load the attendance / leave / holidays of the chosen period ONCE and share it
    loaded = services.load_period(emp, period["start"], period["end"])
    record = loaded[0].get(today) if period["start"] <= today <= period["end"] else services.today_record(emp)
    ctx = {"period": period, "emp": emp, "employee": emp, "today": today, "record": record}
    if period["mode"] == "year":
        ctx["breakdown"], ctx["summary"] = services.yearly_breakdown(emp, period["year"], today, loaded)
    else:
        ctx["summary"] = services.period_summary(emp, period["start"], period["end"], today, loaded)
        ctx["history"] = services.attendance_rows(emp, period["start"], period["end"], today, loaded)
    pv = services.employee_project_view(emp, today)
    ctx["projects"] = pv["current"] + pv["completed"]
    ctx["projects_current"] = pv["current"]
    ctx["projects_completed"] = pv["completed"]
    ctx["projects_active"] = pv["current"]
    ctx["project_office_days"] = pv["office_days"]
    ctx["project_field_days"] = pv["field_days"]
    ctx["holiday_today"] = services.today_holiday(today)
    return ctx


# ---------------------------------------------------------------- dashboards
@login_required
def dashboard(request):
    if services.has_manager_view(request.user):
        return admin_dashboard(request)
    return employee_dashboard(request)


def employee_dashboard(request):
    emp = services.get_employee(request.user)
    period = _period(request)
    if not emp:
        return render(request, "portal/dashboard_employee.html", {"employee": None, "period": period})
    return render(request, "portal/dashboard_employee.html", _employee_overview(emp, period))


ST_FILTERS = [("", "All"), ("present", "Present"), ("notin", "Not in"), ("leave", "On leave")]


def admin_dashboard(request):
    today = timezone.localdate()
    employees = list(services.order_staff(
        services.staff_qs(Employee.objects.select_related("user", "department", "designation"))))
    today_map = {a.employee_id: a for a in Attendance.objects.filter(date=today)}
    holiday_name = services.today_holiday(today)

    # approved leave covering today (leave type needed: Loss of Pay is shown differently)
    leave_today = {}
    for lv in LeaveRequest.objects.select_related("leave_type").filter(
            status=LeaveRequest.STATUS_APPROVED, start_date__lte=today, end_date__gte=today):
        leave_today[lv.employee_id] = lv

    present_today = absent_today = 0
    for e in employees:
        e.today = today_map.get(e.id)
        lv = leave_today.get(e.pk)
        e.leave_today = lv if (lv and not e.today and not holiday_name) else None
        e.state, e.blink, e.group = "", "", ""
        if e.status != Employee.STATUS_ACTIVE:
            e.state = "inactive"
            continue
        if e.today:
            e.state, e.group = "present", "present"
            present_today += 1
        elif holiday_name:
            e.state = "holiday"
        else:
            absent_today += 1
            if e.leave_today and e.leave_today.leave_type.is_lop:
                # not in because of Loss of Pay: red blink, faster when the leave is longer than 3 days
                e.state, e.group = "lop", "notin"
                e.blink = "blink-fast" if e.leave_today.days > 3 else "blink-slow"
            elif e.leave_today:
                e.state, e.group = "leave", "leave"
            else:
                e.state, e.group = "notin", "notin"
                e.blink = "blink-slow"                  # did not come: red blinking "Not in"

    st = request.GET.get("st", "")
    rows = [e for e in employees if not st or e.group == st]
    page, qs = paginate(request, rows, per=50)
    projects = list(Project.objects.filter(status=Project.STATUS_INPROGRESS).prefetch_related("employees")[:6])
    ctx = {
        "employees": page, "page_obj": page, "pager_qs": qs, "today": today,
        "st": st, "st_filters": ST_FILTERS,
        "total_employees": sum(1 for e in employees if e.status == Employee.STATUS_ACTIVE),
        "present_today": present_today, "absent_today": absent_today,
        "department_count": Department.objects.count(),
        "projects_in_progress": Project.objects.filter(status=Project.STATUS_INPROGRESS).count(),
        "project_list": projects,
        "holiday_today": holiday_name,
        "today_company_holiday": Holiday.objects.filter(date=today, kind=Holiday.KIND_COMPANY).first(),
        "today_updates": ProjectUpdate.objects.select_related("project", "employee__user").filter(date=today)[:10],
    }
    return render(request, "portal/dashboard_admin.html", ctx)


@login_required
@require_POST
def clock_in(request):
    emp = services.get_employee(request.user)
    if not emp:
        messages.error(request, "No employee profile is linked to this account.")
    else:
        _, msg, ok = services.clock_in(emp, request.POST.get("work_mode", Attendance.MODE_OFFICE),
                                       request.POST.get("field_type", ""))
        (messages.success if ok else messages.warning)(request, msg)
    return redirect("dashboard")


@login_required
@require_POST
def clock_out(request):
    emp = services.get_employee(request.user)
    if not emp:
        messages.error(request, "No employee profile is linked to this account.")
    else:
        _, msg, ok = services.clock_out(emp)
        (messages.success if ok else messages.warning)(request, msg)
    return redirect("dashboard")


# ---------------------------------------------------------------- permissions (Admin / HR)
PERM_COLUMNS = (
    ("employees", "Employees", (("can_view_employees", "View"), ("can_create_employees", "Create"), ("can_edit_employees", "Edit"))),
    ("projects", "Projects", (("can_view_projects", "View"), ("can_create_projects", "Create"), ("can_edit_projects", "Edit"))),
    ("other", "Other", (("can_manage_leave", "Approve leave"), ("can_manage_attendance", "Attendance"), ("can_manage_groups", "Chat groups"))),
)
PERM_FLAGS = [f for _k, _t, cols in PERM_COLUMNS for f, _l in cols]


@manager_required
def permissions_manage(request):
    """One table: every person, one tick box per permission. Admin / HR roles always have everything (locked)."""
    people = list(services.order_staff(
        Employee.objects.select_related("user", "designation", "department")))
    # Super Admin first, then HR, then everybody else in the usual list order
    people.sort(key=lambda e: {Employee.ROLE_ADMIN: 0, Employee.ROLE_HR: 1}.get(e.role, 2))
    editable = [e for e in people if e.role == Employee.ROLE_EMPLOYEE]
    if request.method == "POST":
        sent = {int(x) for x in request.POST.getlist("emp_ids") if x.isdigit()}
        changed = 0
        for e in editable:
            if e.pk not in sent:
                continue
            new = {f: request.POST.get(f"p_{e.pk}_{f}") == "1" for f in PERM_FLAGS}
            for area in ("employees", "projects"):          # Create / Edit always include View
                if new[f"can_create_{area}"] or new[f"can_edit_{area}"]:
                    new[f"can_view_{area}"] = True
            if any(getattr(e, f) != v for f, v in new.items()):
                for f, v in new.items():
                    setattr(e, f, v)
                e.save(update_fields=list(new))
                changed += 1
        if changed:
            messages.success(request, f"Permissions saved for {changed} {'person' if changed == 1 else 'people'}.")
        else:
            messages.info(request, "No permission was changed.")
        return redirect("permissions")
    for e in people:
        e.full_access = e.role != Employee.ROLE_EMPLOYEE
        e.flags = [(f, label, getattr(e, f)) for _k, _t, cols in PERM_COLUMNS for f, label in cols]
    return render(request, "portal/permissions.html", {
        "people": people, "columns": PERM_COLUMNS, "editable_count": len(editable),
    })


# ---------------------------------------------------------------- employees
@perm_required("employees_view")
def employee_list(request):
    q = request.GET.get("q", "").strip()
    employees = services.staff_qs(Employee.objects.select_related("user", "department", "team", "designation"))
    if q:
        employees = employees.filter(
            Q(employee_id__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__username__icontains=q)
            | Q(designation__name__icontains=q)
            | Q(department__name__icontains=q)
            | Q(team__name__icontains=q)
        )
    employees = list(services.order_staff(employees))          # List priority, then A-Z (used to break ties)
    percents = services.month_percent_map(employees)
    groups = {}
    for e in employees:
        e.month_percent = percents.get(e.pk, 0)
        groups.setdefault(e.department_id, {"name": e.department.name if e.department_id else "No department", "rows": []})["rows"].append(e)
    dept_rows = []
    for g in groups.values():
        g["rows"].sort(key=lambda e: -e.month_percent)          # stable: ties keep the priority / A-Z order
        active = [e for e in g["rows"] if e.status == Employee.STATUS_ACTIVE] or g["rows"]
        g["percent"] = round(sum(e.month_percent for e in active) / len(active)) if active else 0
        g["count"] = len(g["rows"])
        dept_rows.append(g)
    # best department first (Software 100% on top, Directors 8% at the bottom); "No department" always last
    dept_rows.sort(key=lambda g: (g["name"] == "No department", -g["percent"], g["name"].lower()))
    return render(request, "portal/employee_list.html", {
        "dept_groups": dept_rows, "total": len(employees), "q": q,
        "month_label": timezone.localdate().strftime("%B %Y"),
    })


TABS = [("profile", "Profile"), ("attendance", "Attendance"), ("projects", "Projects")]


def _tab_ctx(request):
    tab = request.GET.get("tab", "profile")
    if tab not in dict(TABS):
        tab = "profile"
    return {"tab": tab, "tabs": TABS}


@login_required
def my_profile(request):
    emp = services.get_employee(request.user)
    if not emp:
        messages.error(request, "No employee profile is linked to this account.")
        return redirect("dashboard")
    ctx = _employee_overview(emp, _period(request))
    ctx.update(back="dashboard", is_self=True, show_password=True, can_edit_photo=True, show_ids=True, **_tab_ctx(request))
    return render(request, "portal/employee_detail.html", ctx)


@login_required
def employee_detail(request, pk):
    me = services.get_employee(request.user)
    emp = get_object_or_404(Employee.objects.select_related("user", "department", "team", "designation"), pk=pk)
    is_self = bool(me and me.pk == emp.pk)
    if not (is_self or services.can(request.user, "employees_view")):
        return _deny(request)
    ctx = _employee_overview(emp, _period(request))
    ctx.update(back="dashboard" if (is_self or request.GET.get("from") == "home") else "employee_list",
               is_self=is_self, **_tab_ctx(request))
    # the password is shown to Admin / HR and to the employee himself (the Super Admin's only to the Super Admin)
    ctx["can_edit_photo"] = is_self or (services.can(request.user, "employees_edit") and _may_touch(request, emp))
    ctx["show_password"] = is_self or (services.is_manager(request.user)
                                       and (emp.role != Employee.ROLE_ADMIN or request.user.is_superuser))
    # Aadhaar / PAN in full only for the person himself and Admin / HR; everybody else with View sees them hidden
    ctx["show_ids"] = is_self or services.is_manager(request.user)
    return render(request, "portal/employee_detail.html", ctx)


@login_required
def employee_photo(request, pk):
    """The profile picture itself (any signed-in user may see it, e.g. in lists and chat)."""
    ph = EmployeePhoto.objects.filter(employee_id=pk).first()
    if not ph:
        raise Http404("No photo")
    resp = HttpResponse(bytes(ph.data), content_type=ph.content_type)
    resp["Cache-Control"] = "private, max-age=86400"     # the page adds ?v=<time>, so a new photo shows at once
    return resp


_MAGIC = {"jpeg": (b"\xff\xd8\xff",), "png": (b"\x89PNG",), "webp": (b"RIFF",)}


@login_required
@require_POST
def employee_photo_save(request, pk):
    """Set / remove a profile photo. The browser already shrinks it to 256 x 256 (see app.js); checked again here."""
    emp = get_object_or_404(Employee, pk=pk)
    me = services.get_employee(request.user)
    is_self = bool(me and me.pk == emp.pk)
    if not (is_self or (services.can(request.user, "employees_edit") and _may_touch(request, emp))):
        return _deny(request)
    back = redirect("my_profile") if is_self else redirect("employee_detail", pk=emp.pk)
    if request.POST.get("remove"):
        EmployeePhoto.objects.filter(employee=emp).delete()
        Employee.objects.filter(pk=emp.pk).update(photo_updated=None)
        messages.success(request, "Photo removed.")
        return back
    raw = request.POST.get("photo_data", "")
    m = _re.fullmatch(r"data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)", raw) if len(raw) < 450_000 else None
    try:
        data = base64.b64decode(m.group(2), validate=True) if m else b""
    except ValueError:
        data = b""
    if not data or len(data) > 300_000 or not data.startswith(_MAGIC[m.group(1)]):
        messages.error(request, "Please choose a JPG, PNG or WEBP picture.")
        return back
    EmployeePhoto.objects.update_or_create(employee=emp, defaults={"data": data, "content_type": f"image/{m.group(1)}"})
    Employee.objects.filter(pk=emp.pk).update(photo_updated=timezone.now())
    messages.success(request, "Photo saved.")
    return back


def _may_touch(request, emp):
    """Only Admin / HR may change Admin / HR accounts."""
    return emp.role == Employee.ROLE_EMPLOYEE or services.is_manager(request.user)


@perm_required("employees_create")
def employee_create(request):
    form = EmployeeForm(request.POST or None, can_set_role=services.is_manager(request.user))
    if request.method == "POST" and form.is_valid():
        emp = form.save()
        messages.success(request, f"Employee {emp.full_name} added with code {emp.employee_id}.")
        return redirect("employee_list")
    return render(request, "portal/employee_form.html", {"form": form, "title": "Add Employee", "back": "employee_list"})


@perm_required("employees_edit")
def employee_edit(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    if not _may_touch(request, emp):
        return _deny(request)
    form = EmployeeForm(request.POST or None, instance=emp, can_set_role=services.is_manager(request.user))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Employee updated.")
        return redirect("employee_list")
    return render(request, "portal/employee_form.html", {"form": form, "title": f"Edit Employee - {emp.full_name}", "back": "employee_list", "emp": emp})


@login_required
def my_profile_edit(request):
    """'Edit my details': everything except the employee code and the name (HR changes those)."""
    emp = services.get_employee(request.user)
    if not emp:
        messages.error(request, "No employee profile is linked to this account.")
        return redirect("dashboard")
    form = SelfProfileForm(request.POST or None, instance=emp)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your details are saved.")
        return redirect("my_profile")
    return render(request, "portal/employee_form.html", {
        "form": form, "title": "Edit my details", "back": "my_profile", "emp": emp, "self_edit": True})


@perm_required("employees_edit")
def employee_delete(request, pk):
    emp = get_object_or_404(Employee, pk=pk)
    if not _may_touch(request, emp):
        return _deny(request)
    if emp.user_id == request.user.pk:
        messages.error(request, "You cannot delete your own account.")
        return redirect("employee_list")
    if request.method == "POST":
        name = emp.full_name
        emp.user.delete()  # cascades to Employee
        messages.success(request, f"Employee {name} deleted.")
        return redirect("employee_list")
    return render(request, "portal/confirm_delete.html", {"object": emp, "back": "employee_list", "what": "employee"})


@perm_required("employees_edit")
@require_POST
def employee_bulk_delete(request):
    """Delete the ticked employees in one go (never your own account, a super admin or an Admin / HR you may not touch)."""
    ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
    deleted, skipped = 0, 0
    for emp in Employee.objects.select_related("user").filter(pk__in=ids):
        if emp.user_id == request.user.pk or emp.user.is_superuser or not _may_touch(request, emp):
            skipped += 1
            continue
        emp.user.delete()        # cascades to the Employee
        deleted += 1
    if deleted:
        messages.success(request, f"{deleted} employee(s) deleted.")
    if skipped:
        messages.warning(request, f"{skipped} not deleted (your own account or an Admin / HR account).")
    if not deleted and not skipped:
        messages.info(request, "Tick the employees you want to delete first.")
    return redirect("employee_list")


# ---------------------------------------------------------------- generic add / edit / delete
def _save_form(request, form_class, title, back, instance=None, ok_msg="Saved.", **form_kwargs):
    form = form_class(request.POST or None, instance=instance, **form_kwargs)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, ok_msg)
        return obj, None
    return None, render(request, "portal/form.html", {"form": form, "title": title, "back": back})


def _delete(request, obj, back, what, ok_msg, warning=""):
    if request.method == "POST":
        try:
            obj.delete()
        except ProtectedError:
            messages.error(request, f"This {what} is still in use and cannot be deleted.")
            return redirect(back)
        messages.success(request, ok_msg)
        return redirect(back)
    return render(request, "portal/confirm_delete.html", {"object": obj, "back": back, "what": what, "warning": warning})


# ---------------------------------------------------------------- organization (departments, teams, designations, leave types)
@perm_required("employees")
def organization(request):
    departments = Department.objects.annotate(
        emp_count=Count("employees", distinct=True), team_count=Count("teams", distinct=True)
    )
    teams = Team.objects.select_related("department").annotate(member_count=Count("employees", distinct=True))
    designations = Designation.objects.annotate(emp_count=Count("employees", distinct=True))
    return render(request, "portal/organization.html", {
        "departments": departments, "teams": teams, "designations": designations,
        "leave_types": LeaveType.objects.all(),
    })


@perm_required("employees_edit")
def department_create(request):
    obj, resp = _save_form(request, DepartmentForm, "Add Department", "organization", ok_msg="Department created.")
    return redirect("organization") if obj else resp


@perm_required("employees_edit")
def department_edit(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    obj, resp = _save_form(request, DepartmentForm, f"Edit Department - {dept.name}", "organization", dept, "Department updated.")
    return redirect("organization") if obj else resp


@perm_required("employees_edit")
def department_delete(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    warning = (
        f"{dept.teams.count()} team(s) in this department will be deleted too, and "
        f"{dept.employees.count()} employee(s) will be left without a department/team. Employees themselves are not deleted."
    )
    return _delete(request, dept, "organization", "department", f"Department {dept.name} deleted.", warning)


@perm_required("employees_edit")
def team_create(request):
    initial = {}
    if request.GET.get("department", "").isdigit():
        initial["department"] = int(request.GET["department"])
    form = TeamForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        team = form.save()
        messages.success(request, f"Team {team.name} created in {team.department.name}.")
        return redirect("organization")
    return render(request, "portal/form.html", {"form": form, "title": "Add Team", "back": "organization"})


@perm_required("employees_edit")
def team_edit(request, pk):
    team = get_object_or_404(Team, pk=pk)
    obj, resp = _save_form(request, TeamForm, f"Edit Team - {team.name}", "organization", team, "Team updated.")
    return redirect("organization") if obj else resp


@perm_required("employees_edit")
def team_delete(request, pk):
    team = get_object_or_404(Team, pk=pk)
    warning = f"{team.employees.count()} employee(s) will be left without a team. Employees themselves are not deleted."
    return _delete(request, team, "organization", "team", f"Team {team.name} deleted.", warning)


@manager_required
def designation_create(request):
    obj, resp = _save_form(request, DesignationForm, "Add Designation", "organization", ok_msg="Designation created.")
    return redirect("organization") if obj else resp


@manager_required
def designation_edit(request, pk):
    d = get_object_or_404(Designation, pk=pk)
    obj, resp = _save_form(request, DesignationForm, f"Edit Designation - {d.name}", "organization", d, "Designation updated.")
    return redirect("organization") if obj else resp


@manager_required
def designation_delete(request, pk):
    d = get_object_or_404(Designation, pk=pk)
    warning = f"{d.employees.count()} employee(s) have this designation; they will be left without one."
    return _delete(request, d, "organization", "designation", f"Designation {d.name} deleted.", warning)


@manager_required
def leavetype_create(request):
    obj, resp = _save_form(request, LeaveTypeForm, "Add Leave Type", "organization", ok_msg="Leave type created.")
    return redirect("organization") if obj else resp


@manager_required
def leavetype_edit(request, pk):
    t = get_object_or_404(LeaveType, pk=pk)
    obj, resp = _save_form(request, LeaveTypeForm, f"Edit Leave Type - {t.name}", "organization", t, "Leave type updated.")
    return redirect("organization") if obj else resp


@manager_required
def leavetype_delete(request, pk):
    t = get_object_or_404(LeaveType, pk=pk)
    return _delete(request, t, "organization", "leave type", f"Leave type {t.name} deleted.",
                   "Leave types that already have leave requests cannot be deleted.")


# ---------------------------------------------------------------- projects
def _project_scope(request):
    if services.can(request.user, "projects_view"):
        return Project.objects.all()
    emp = services.get_employee(request.user)
    return Project.objects.filter(employees=emp) if emp else Project.objects.none()


@login_required
def project_list(request):
    me = services.get_employee(request.user)
    manage = services.can(request.user, "projects_view")      # sees ALL projects (View permission)
    mine = services.employee_project_view(me) if me else None
    if mine and not (mine["current"] or mine["completed"]):
        mine = None if manage else mine
    projects, q, status = [], "", ""
    page, pqs = None, ""
    period = _period(request)
    filtered = False
    if manage:
        projects = _project_scope(request).prefetch_related("employees__user", "assignments", "updates")
        q = request.GET.get("q", "").strip()
        if q:
            projects = projects.filter(Q(name__icontains=q) | Q(employees__user__first_name__icontains=q)
                                       | Q(employees__employee_id__icontains=q)).distinct()
        status = request.GET.get("status", "")
        if status in dict(Project.STATUS_CHOICES):
            projects = projects.filter(status=status)
        filtered = request.GET.get("period") in ("month", "year")
        period["sel"] = period["mode"] if filtered else "all"
        if filtered:  # projects that were running at some point inside the chosen month / year
            projects = projects.filter(Q(start_date__isnull=True) | Q(start_date__lte=period["end"])).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=period["start"])
            )
        page, pqs = paginate(request, projects, per=30)
        projects = list(page)
        leave_map = services.load_leave_ranges({e.pk for p in projects for e in p.employees.all()})
        for p in projects:
            p.metrics = services.project_metrics(p, leave_map)
    return render(request, "portal/project_list.html", {
        "projects": projects, "status": status, "q": q, "status_choices": Project.STATUS_CHOICES,
        "period": period, "period_on": filtered, "manage": manage, "mine": mine,
        "can_create_project": services.can(request.user, "projects_create"),
        "can_edit_project": services.can(request.user, "projects_edit"),
        "today": timezone.localdate(), "page_obj": page, "pager_qs": pqs,
    })


@login_required
def project_detail(request, pk):
    project = get_object_or_404(
        _project_scope(request).prefetch_related("employees__user", "assignments", "updates__employee__user"), pk=pk)
    me = services.get_employee(request.user)
    today = timezone.localdate()
    mine = project.assignments.filter(employee=me).first() if me else None
    my_today = project.updates.filter(employee=me, date=today).first() if me else None
    my_latest = project.updates.filter(employee=me).first() if me else None
    return render(request, "portal/project_detail.html", {
        "project": project, "m": services.project_metrics(project),
        "updates": project.updates.select_related("employee__user")[:60],
        "can_update": bool(mine) and project.status != Project.STATUS_COMPLETED,
        "my_today": my_today, "my_latest": my_latest, "today": today,
    })


@login_required
@require_POST
def project_update(request, pk):
    """Employee's daily progress: how much of the project is finished."""
    project = get_object_or_404(Project, pk=pk)
    emp = services.get_employee(request.user)
    if not emp:
        return _deny(request)
    _, msg, ok = services.submit_project_update(emp, project, request.POST.get("percent"), request.POST.get("note", ""))
    (messages.success if ok else messages.error)(request, msg)
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt in ("dashboard", "project_list") else reverse("project_detail", args=[project.pk]))


def _project_form(request, instance=None):
    """Step 1: the project itself (title, client, code, details of work, dates). A NEW project goes straight to step 2."""
    form = ProjectForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        was_new = instance is None
        project = form.save()
        if was_new:
            messages.success(request, f"Project {project.name} created. Now assign the members.")
            return redirect("project_assign", pk=project.pk)
        messages.success(request, "Project saved.")
        return redirect("project_list")
    title = f"Edit Project - {instance.name}" if instance else "Add Project"
    return render(request, "portal/project_form.html", {
        "form": form, "title": title, "back": "project_list", "project": instance})


@perm_required("projects_create")
def project_create(request):
    return _project_form(request)


@perm_required("projects_edit")
def project_edit(request, pk):
    return _project_form(request, get_object_or_404(Project, pk=pk))


@login_required
def project_assign(request, pk):
    """Step 2: assign the members (Office / Field - On shore / Off shore, work given, days) to the project.

    Edit permission can always change the members; Create permission can give a NEW project its first members."""
    project = get_object_or_404(Project, pk=pk)
    first_time = not project.assignments.exists()
    if not (services.can(request.user, "projects_edit") or (first_time and services.can(request.user, "projects_create"))):
        return _deny(request)
    form = ProjectMembersForm(request.POST or None, project=project)
    if request.method == "POST" and form.is_valid():
        form.save(was_new=first_time)
        added = getattr(form, "added", [])
        if added:
            notifications.notify_project_assigned(project, added, form.modes, request.user, form.field_types)
            if notifications.cloud_enabled():
                messages.success(request, f"Members saved. {len(added)} employee(s) notified on WhatsApp.")
            else:
                messages.success(request, f"Members saved. Tap 'Open WhatsApp' below to message the "
                                          f"{len(added)} assigned employee(s).")
                return redirect("notifications")
        else:
            messages.success(request, "Members saved.")
        return redirect("project_list")
    return render(request, "portal/project_assign.html", {
        "form": form, "project": project, "title": f"Assign members - {project.name}",
        "back": "project_list", "first_time": first_time})


@perm_required("projects_edit")
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk)
    return _delete(request, project, "project_list", "project", "Project deleted.")


# ---------------------------------------------------------------- leave
@login_required
def leave_list(request):
    me = services.get_employee(request.user)
    manage = services.can(request.user, "leave")
    period = _period(request)
    qs = LeaveRequest.objects.select_related("employee__user", "employee__designation", "leave_type", "decided_by",
                                             "approver__user")
    if not manage:
        qs = qs.filter(employee=me) if me else qs.none()
    elif not services.is_manager(request.user):
        # an approver sees the requests people sent to HER (and old requests nobody was chosen for), plus her own
        qs = qs.filter(Q(approver=me) | Q(approver__isnull=True) | Q(employee=me)) if me else qs.none()
    q = request.GET.get("q", "").strip()
    if manage and q:
        qs = qs.filter(Q(employee__employee_id__icontains=q) | Q(employee__user__first_name__icontains=q)
                       | Q(employee__user__last_name__icontains=q))
    status = request.GET.get("status", "")
    if status in dict(LeaveRequest.STATUS_CHOICES):
        qs = qs.filter(status=status)
    qs = qs.filter(start_date__lte=period["end"], end_date__gte=period["start"])
    page, pqs = paginate(request, qs, per=50)
    leaves = list(page)
    transfers = {t.leave_id: t for t in PermissionTransfer.objects.select_related("to_employee__user").filter(
        leave__in=[l.pk for l in leaves])}
    for l in leaves:
        l.transfer = transfers.get(l.pk)
        l.can_decide = services.is_manager(request.user) or not l.approver_id or bool(me and l.approver_id == me.pk)
        # "Transfer to": HR / manager, or the person on leave herself - only for people who have permissions to hand over
        l.can_transfer = (bool(services.perms_of_employee(l.employee)) and l.status != LeaveRequest.STATUS_REJECTED
                          and l.end_date >= timezone.localdate() and (manage or bool(me and l.employee_id == me.pk)))
    overview = services.leave_overview(period["year"]) if manage else None
    opage = None
    if overview:
        opage, oqs = paginate(request, overview["rows"], per=50, param="opage")
        overview = dict(overview, rows=list(opage))
    return render(request, "portal/leave_list.html", {
        "leaves": leaves, "page_obj": page, "pager_qs": pqs, "manage": manage, "period": period, "status": status, "q": q,
        "status_choices": LeaveRequest.STATUS_CHOICES, "me": me,
        "balance": services.leave_balances(me, period["year"]) if (me and not manage) else None,
        "overview": overview, "opage_obj": opage, "opager_qs": oqs if overview else "",
    })


@login_required
def leave_create(request):
    me = services.get_employee(request.user)
    manage = services.can(request.user, "leave")
    if not me and not manage:
        messages.error(request, "No employee profile is linked to this account.")
        return redirect("dashboard")
    form = LeaveForm(request.POST or None, employee=me, pick_employee=manage)
    if request.method == "POST" and form.is_valid():
        leave = form.save(commit=False)
        if manage:  # HR records leave for someone: it is approved straight away
            leave.status = LeaveRequest.STATUS_APPROVED
            leave.decided_by = request.user
        else:
            leave.employee = me
        leave.save()
        if manage:
            notifications.notify_leave_decided(leave, request.user)
            messages.success(request, f"Leave saved ({services.plain(leave.days)} working day(s)).")
        else:
            notifications.notify_leave_applied(leave, request.user)
            to = leave.approver.full_name if leave.approver_id else "HR / managers"
            messages.success(request, f"Leave request sent to {to} ({services.plain(leave.days)} day(s)). "
                                      "They have been notified.")
        return redirect("leave_list")
    return render(request, "portal/form.html", {
        "form": form, "title": "Apply Leave", "back": "leave_list",
        "leave_balance": services.leave_balances(me) if me else None,
        "leave_note": "Casual Leave: 1.5 days are credited every month. When the CL credit is finished, "
                      "choose Loss of Pay (LOP). Sundays, 2nd Saturdays and holidays are not counted.",
    })


def _leave_editable(request, leave):
    me = services.get_employee(request.user)
    if services.can(request.user, "leave"):
        return True
    return bool(me and leave.employee_id == me.pk and leave.status == LeaveRequest.STATUS_PENDING)


@login_required
def leave_edit(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if not _leave_editable(request, leave):
        return _deny(request)
    manage = services.can(request.user, "leave")
    form = LeaveForm(request.POST or None, instance=leave, employee=leave.employee, pick_employee=manage)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Leave updated.")
        return redirect("leave_list")
    return render(request, "portal/form.html", {
        "form": form, "title": "Edit Leave", "back": "leave_list",
        "leave_balance": services.leave_balances(leave.employee),
    })


@login_required
def leave_delete(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if not _leave_editable(request, leave):
        return _deny(request)
    return _delete(request, leave, "leave_list", "leave request", "Leave deleted.")


@perm_required("leave")
@require_POST
def leave_decide(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    me = services.get_employee(request.user)
    if not services.is_manager(request.user):
        if (me and leave.employee_id == me.pk) or (leave.approver_id and (not me or leave.approver_id != me.pk)):
            return _deny(request)       # not your own leave, and not a request somebody sent to another person
    action = request.POST.get("action")
    if action == "approve":
        msg = services.validate_leave(leave.employee, leave.leave_type, leave.start_date, leave.end_date,
                                      exclude_pk=leave.pk, half_day=leave.half_day)
        if msg and "credit" in msg:
            messages.error(request, msg)
            return redirect("leave_list")
        leave.status = LeaveRequest.STATUS_APPROVED
    elif action == "reject":
        leave.status = LeaveRequest.STATUS_REJECTED
    else:
        return redirect("leave_list")
    leave.decided_by = request.user
    leave.save()
    notifications.notify_leave_decided(leave, request.user)
    messages.success(request, "Leave approved." if leave.status == LeaveRequest.STATUS_APPROVED else "Leave declined.")
    return redirect(_safe_next(request, "leave_list"))


# ---------------------------------------------------------------- permission transfer (HR on leave)
@login_required
def leave_transfer(request, pk):
    """"Transfer to": while HR is on leave, her permissions go to another employee for the same days."""
    from .forms import PERM_LABELS
    leave = get_object_or_404(LeaveRequest.objects.select_related("employee__user", "employee__designation", "leave_type"), pk=pk)
    me = services.get_employee(request.user)
    allowed_user = services.can(request.user, "leave") or bool(me and me.pk == leave.employee_id)
    allowed = services.transfer_perm_choices(leave.employee)
    if not allowed_user or not allowed or leave.status == LeaveRequest.STATUS_REJECTED:
        return _deny(request)
    existing = PermissionTransfer.objects.filter(leave=leave).first()
    initial = {"to_employee": existing.to_employee_id, "perms": sorted(existing.perm_set())} if existing else None
    form = PermissionTransferForm(request.POST or None, leave=leave, allowed=allowed, initial=initial)
    if request.method == "POST" and form.is_valid():
        to, perms = form.cleaned_data["to_employee"], [p for p in allowed if p in form.cleaned_data["perms"]]
        PermissionTransfer.objects.filter(leave=leave).delete()
        PermissionTransfer.objects.create(
            from_employee=leave.employee, to_employee=to, leave=leave, start_date=leave.start_date,
            end_date=leave.end_date, perms=",".join(perms), created_by=request.user)
        names = ", ".join(PERM_LABELS[p] for p in perms)
        notifications.notify(
            [to], f"{leave.employee.full_name} is on leave from {services.fmt_date(leave.start_date)} to "
                  f"{services.fmt_date(leave.end_date)}. You can manage: {names} for these day(s).",
            kind="permission", sender=request.user)
        messages.success(request, f"{names} transferred to {to.full_name} for {services.plain(leave.days)} day(s) "
                                  f"({services.fmt_date(leave.start_date)} to {services.fmt_date(leave.end_date)}).")
        return redirect("leave_list")
    return render(request, "portal/form.html", {
        "form": form, "title": f"Transfer permissions - {leave.employee.full_name}", "back": "leave_list",
        "form_note": f"{leave.employee.full_name} is on leave from {services.fmt_date(leave.start_date)} to "
                     f"{services.fmt_date(leave.end_date)} ({services.plain(leave.days)} day(s)). The person you choose "
                     f"gets the ticked permissions only for these days - 1 day leave = 1 day, 2 days leave = 2 days - "
                     f"then they go back automatically. If the leave dates change, the transfer changes with it.",
    })


@login_required
@require_POST
def leave_transfer_cancel(request, pk):
    t = get_object_or_404(PermissionTransfer.objects.select_related("leave"), pk=pk)
    me = services.get_employee(request.user)
    if not (services.can(request.user, "leave") or (me and me.pk == t.from_employee_id)):
        return _deny(request)
    t.delete()
    messages.success(request, "Permission transfer cancelled.")
    return redirect("leave_list")


# ---------------------------------------------------------------- department groups (message + WhatsApp)
def _group_required(view):
    """Chat: everybody who is signed in may open it (they only see the groups they are in)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.get_full_path()}")
        if not services.can_use_chat(request.user):
            return _deny(request)
        return view(request, *args, **kwargs)

    return wrapper


def _group_manage_required(view):
    """Create / edit / delete a group: only Admin / HR and designations that have the groups permission."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.get_full_path()}")
        if not services.can_manage_groups(request.user):
            return _deny(request)
        return view(request, *args, **kwargs)

    return wrapper


def _my_groups(request):
    """Groups this person may open: all of them for people who manage groups, otherwise only the ones they belong to."""
    qs = Group.objects.all()
    if services.can_manage_groups(request.user):
        return qs
    me = services.get_employee(request.user)
    return qs.filter(pk__in=me.chat_groups.values("pk")) if me else qs.none()


@_group_required
def group_list(request):
    groups = _my_groups(request).annotate(member_count=Count("members", distinct=True)).order_by("name")
    page, qs = paginate(request, groups, per=12)
    return render(request, "portal/group_list.html", {"groups": page, "page_obj": page, "pager_qs": qs})


def _group_form(request, instance=None):
    form = GroupForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        g = form.save(commit=False)
        if not g.pk:
            g.created_by = request.user
        g.save()
        form.save_m2m()
        messages.success(request, f"Group {g.name} saved ({g.members.count()} members).")
        return redirect("group_detail", pk=g.pk)
    return render(request, "portal/group_form.html", {
        "form": form, "title": f"Edit group - {instance.name}" if instance else "Create group",
        "departments": Department.objects.all(),
    })


@_group_manage_required
def group_create(request):
    return _group_form(request)


@_group_manage_required
def group_edit(request, pk):
    return _group_form(request, get_object_or_404(Group, pk=pk))


@_group_manage_required
def group_delete(request, pk):
    g = get_object_or_404(Group, pk=pk)
    return _delete(request, g, "group_list", "group", f"Group {g.name} deleted.", "All messages of this group are deleted too.")


@_group_required
def group_detail(request, pk):
    group = get_object_or_404(_my_groups(request), pk=pk)
    members = list(services.staff_qs(group.members.select_related("user", "designation")).filter(
        status=Employee.STATUS_ACTIVE))
    me = services.get_employee(request.user)
    prefix = f"[{group.name} group]"
    if request.method == "POST":
        text = (request.POST.get("message") or "").strip()
        if not text:
            messages.error(request, "Type a message first.")
            return redirect("group_detail", pk=group.pk)
        GroupMessage.objects.create(group=group, sender=request.user, message=text)
        by = request.user.get_full_name() or request.user.username
        recipients = [m for m in members if not (me and m.pk == me.pk)]
        notifications.notify(recipients, f"{prefix} {by}: {text}", kind="group", sender=request.user)
        if notifications.cloud_enabled():
            messages.success(request, f"Message sent to {len(recipients)} member(s) in the app and on WhatsApp.")
        else:
            messages.success(request, f"Message sent to {len(recipients)} member(s) in the app. "
                                      "Use the WhatsApp buttons below to send it on WhatsApp too.")
        return redirect("group_detail", pk=group.pk)

    hpage, hqs = paginate(request, GroupMessage.objects.select_related("sender").filter(group=group), per=30, param="hpage")
    chat_messages = list(hpage)[::-1]          # oldest first, newest at the bottom (like a chat)
    for m in chat_messages:
        m.mine = m.sender_id == request.user.pk
    outbox = list(Notification.objects.select_related("recipient").filter(
        sender=request.user, kind="group", recipient__in=[m.pk for m in members], message__startswith=prefix,
    ).exclude(whatsapp=Notification.WA_SENT)[:60])
    for n in outbox:
        n.link = notifications.wa_link(n.recipient.phone, n.message)
        n.number = notifications.normalize_phone(n.recipient.phone)
    return render(request, "portal/group_detail.html", {
        "group": group, "members": members, "history": hpage, "chat_messages": chat_messages, "page_obj": hpage, "pager_qs": hqs,
        "outbox": outbox, "cloud": notifications.cloud_enabled(),
    })


# ---------------------------------------------------------------- attendance (HR / designation based)
@perm_required("attendance")
def attendance_list(request):
    today = timezone.localdate()
    period = _period(request)
    q = request.GET.get("q", "").strip()
    emps = services.staff_qs(Employee.objects.select_related("user", "designation")).filter(
        status=Employee.STATUS_ACTIVE)
    if q:
        emps = emps.filter(Q(employee_id__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q))
    emps = emps.order_by("employee_id")
    page, qs = paginate(request, emps, per=50)
    people = list(page)
    summaries = services.bulk_period_summaries(people, period["start"], period["end"], today)   # this page only
    summary_rows = []
    for e in people:
        s_ = dict(summaries[e.pk])
        s_["employee"] = e
        summary_rows.append(s_)
    records = Attendance.objects.select_related("employee__user").filter(
        date__range=(period["start"], period["end"]), employee_id__in=emps.values("pk"))
    rpage, rqs = paginate(request, records, per=50, param="rpage")
    return render(request, "portal/attendance_list.html", {
        "period": period, "q": q, "summary_rows": summary_rows, "records": rpage, "rpage_obj": rpage, "rpager_qs": rqs,
        "page_obj": page, "pager_qs": qs,
    })


@perm_required("attendance")
def attendance_create(request):
    obj, resp = _save_form(request, AttendanceForm, "Add Attendance", "attendance_list", ok_msg="Attendance saved.")
    return redirect("attendance_list") if obj else resp


@perm_required("attendance")
def attendance_edit(request, pk):
    rec = get_object_or_404(Attendance, pk=pk)
    obj, resp = _save_form(request, AttendanceForm, f"Edit Attendance - {rec.employee.employee_id} {rec.date:%d-%b-%Y}",
                           "attendance_list", rec, "Attendance updated.")
    return redirect("attendance_list") if obj else resp


@perm_required("attendance")
def attendance_delete(request, pk):
    rec = get_object_or_404(Attendance, pk=pk)
    return _delete(request, rec, "attendance_list", "attendance record", "Attendance record deleted.")


# ---------------------------------------------------------------- holidays
@login_required
def holiday_list(request):
    today = timezone.localdate()
    year = int(request.GET["year"]) if request.GET.get("year", "").isdigit() else today.year
    holidays = list(Holiday.objects.filter(date__year=year))
    second_saturdays = [
        d for d in services.daterange(date(year, 1, 1), date(year, 12, 31)) if services.is_second_saturday(d)
    ]
    return render(request, "portal/holiday_list.html", {
        "holidays": holidays, "year": year, "years": list(range(today.year + 1, today.year - 3, -1)),
        "second_saturdays": second_saturdays, "today": today,
        "today_holiday": services.today_holiday(today),
        "today_company_holiday": Holiday.objects.filter(date=today, kind=Holiday.KIND_COMPANY).first(),
    })


@manager_required
def holiday_create(request):
    form = HolidayForm(request.POST or None, initial={"kind": Holiday.KIND_GOVT})
    if request.method == "POST" and form.is_valid():
        h = form.save(commit=False)
        h.created_by = request.user
        h.save()
        messages.success(request, f"Holiday added: {h.name} ({services.fmt_date(h.date)}).")
        return redirect("holiday_list")
    return render(request, "portal/form.html", {"form": form, "title": "Add Holiday", "back": "holiday_list"})


@manager_required
def holiday_delete(request, pk):
    h = get_object_or_404(Holiday, pk=pk)
    return _delete(request, h, "holiday_list", "holiday", "Holiday removed.")


@manager_required
@require_POST
def holiday_today(request):
    """Admin / HR: declare today as a company holiday (or cancel it)."""
    today = timezone.localdate()
    if request.POST.get("action") == "cancel":
        Holiday.objects.filter(date=today, kind=Holiday.KIND_COMPANY).delete()
        messages.success(request, "Today's company holiday was cancelled.")
    else:
        name = (request.POST.get("name") or "").strip()[:120] or "Company holiday"
        Holiday.objects.update_or_create(
            date=today, defaults={"name": name, "kind": Holiday.KIND_COMPANY, "created_by": request.user})
        messages.success(request, f"Today ({services.fmt_date(today)}) is now a company holiday: {name}.")
    return redirect(_safe_next(request, "dashboard"))


# ---------------------------------------------------------------- notifications (in-app + WhatsApp)
@login_required
def notification_list(request):
    me = services.get_employee(request.user)
    mine_page, mqs = paginate(request, Notification.objects.filter(recipient=me), per=15) if me else (None, "")
    mine = list(mine_page) if me else []
    outbox = list(
        Notification.objects.select_related("recipient__user").filter(sender=request.user)
        .exclude(whatsapp=Notification.WA_SENT)[:50]
    )
    for n in outbox:
        n.link = notifications.wa_link(n.recipient.phone, n.message)
    if me:
        Notification.objects.filter(recipient=me, is_read=False).update(is_read=True)
    return render(request, "portal/notifications.html", {
        "mine": mine, "outbox": outbox, "cloud": notifications.cloud_enabled(),
        "page_obj": mine_page, "pager_qs": mqs,
    })


@login_required
@require_POST
def notification_sent(request, pk):
    n = get_object_or_404(Notification, pk=pk, sender=request.user)
    n.whatsapp = Notification.WA_SENT
    n.save(update_fields=["whatsapp"])
    return redirect(_safe_next(request, "notifications"))


# ---------------------------------------------------------------- biometric machines (Admin / HR)
@manager_required
def biometric_list(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()[:100]
        if not name:
            messages.error(request, "Enter a name for the machine (e.g. Main gate).")
        else:
            d = BiometricDevice.objects.create(
                name=name, location=(request.POST.get("location") or "").strip()[:150],
                serial=(request.POST.get("serial") or "").strip()[:60])
            messages.success(request, f"Machine added: {d.name}. Now connect it using the details below.")
        return redirect("biometric_list")
    devices = list(BiometricDevice.objects.all())
    base = request.build_absolute_uri("/").rstrip("/")
    punches = list(BiometricPunch.objects.select_related("employee__user", "device")[:40])
    return render(request, "portal/biometric.html", {
        "devices": devices, "base_url": base, "punches": punches,
        "unknown_count": BiometricPunch.objects.filter(result="unknown").count(),
    })


@manager_required
@require_POST
def biometric_action(request, pk):
    d = get_object_or_404(BiometricDevice, pk=pk)
    action = request.POST.get("action")
    if action == "delete":
        d.delete()
        messages.success(request, "Machine removed.")
    elif action == "toggle":
        d.is_active = not d.is_active
        d.save(update_fields=["is_active"])
        messages.success(request, f"{d.name} is now {'ON' if d.is_active else 'OFF'}.")
    elif action == "newkey":
        from .models import _new_device_key
        d.api_key = _new_device_key()
        d.save(update_fields=["api_key"])
        messages.success(request, "New key created - update it on the machine / software.")
    return redirect("biometric_list")
