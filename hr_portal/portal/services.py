"""Business logic shared by the website views and the REST API."""
import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .middleware import memo as request_memo
from django.db import models
from .models import (
    Attendance, Employee, Holiday, LeaveRequest, LeaveType, PermissionTransfer, Project, ProjectAssignment,
    ProjectUpdate,
)

PERMS = ("employees", "projects", "leave", "attendance")      # the areas that can be handed over while somebody is on leave
# Employees and Projects each have View / Create / Edit. "employees" / "projects" alone = has at least one of the three.
GRANULAR = ("employees_view", "employees_create", "employees_edit", "projects_view", "projects_create", "projects_edit")


def get_employee(user):
    """Return the Employee profile for a user or None (e.g. a bare superuser)."""
    try:
        return user.employee
    except Employee.DoesNotExist:
        return None


def is_manager(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    emp = get_employee(user)
    return bool(emp and emp.is_manager)


def role_label(user):
    emp = get_employee(user)
    if emp:
        return emp.get_role_display()
    return "Super Admin" if user.is_superuser else "Employee"


def perms_of_employee(emp):
    """What an employee can manage because of the role / the permissions ticked for the PERSON (no transfers).

    employees_view / _create / _edit and projects_view / _create / _edit are separate. Create or Edit always
    includes View (you cannot create or edit what you cannot see). "employees" / "projects" = any of the three."""
    if not emp:
        return set()
    if emp.is_manager:
        return set(PERMS) | set(GRANULAR)
    flags = {
        "employees_view": emp.can_view_employees, "employees_create": emp.can_create_employees,
        "employees_edit": emp.can_edit_employees,
        "projects_view": emp.can_view_projects, "projects_create": emp.can_create_projects,
        "projects_edit": emp.can_edit_projects,
        "leave": emp.can_manage_leave, "attendance": emp.can_manage_attendance,
    }
    out = {k for k, v in flags.items() if v}
    for area in ("employees", "projects"):
        if f"{area}_create" in out or f"{area}_edit" in out:
            out.add(f"{area}_view")
        if any(f"{area}_{a}" in out for a in ("view", "create", "edit")):
            out.add(area)
    return out


def _base_perms(user):
    """Permissions from the account itself (superuser / role / designation), without any transfer."""
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(PERMS) | set(GRANULAR)       # Admin: every permission (view / create / edit too)
    return perms_of_employee(get_employee(user))


def active_transfers(employee, today=None):
    """Permission transfers handed TO this employee that are valid today (cached for one request)."""
    if not employee:
        return []
    today = today or timezone.localdate()
    m = request_memo()
    key = ("transfers", employee.pk, today)
    if m is not None and key in m:
        return m[key]
    rows = list(PermissionTransfer.objects.select_related("from_employee__user").filter(
        to_employee=employee, start_date__lte=today, end_date__gte=today))
    if m is not None:
        m[key] = rows
    return rows


def get_perms(user):
    """Set of areas the user may manage: employees / projects / leave / attendance.

    Super user + role Admin/HR get everything. A normal employee gets what their *designation* allows,
    plus whatever HR handed over with "Transfer to" while she is on leave (only for the leave days).
    """
    perms = set(_base_perms(user))
    if user.is_authenticated and not user.is_superuser:
        for t in active_transfers(get_employee(user)):
            # hand over only what the person on leave really has (e.g. View only stays View only)
            theirs = perms_of_employee(t.from_employee)
            for p in t.perm_set():
                perms |= {k for k in theirs if k == p or k.startswith(p + "_")}
    return perms


def acting_for(user):
    """[(PermissionTransfer)] the user is currently covering for somebody else."""
    if not user.is_authenticated:
        return []
    return active_transfers(get_employee(user))


def has_manager_view(user):
    """Admin / HR, or somebody covering for them today -> sees the manager dashboard."""
    return is_manager(user) or bool(acting_for(user))


def can_use_chat(user):
    """Everybody with a portal account can open Chat, read the groups they are in and reply."""
    return bool(user.is_authenticated and (is_manager(user) or get_employee(user)))


def can_manage_groups(user):
    """Create / edit / delete groups: Admin / HR, or an employee whose designation has the groups permission."""
    if not user.is_authenticated:
        return False
    if is_manager(user):
        return True
    emp = get_employee(user)
    return bool(emp and emp.can_manage_groups)


def can_message_groups(user):  # old name, kept so nothing else breaks
    return can_use_chat(user)


def staff_qs(qs=None):
    """Employees shown in lists / counts: the Super Admin is not an 'employee'."""
    qs = Employee.objects.all() if qs is None else qs
    return qs.exclude(role=Employee.ROLE_ADMIN)


def order_staff(qs):
    """Employee table order: the List priority of each person (100 = first ... 1 = last); people with the same
    number come one by one in A to Z order of their name."""
    from django.db.models.functions import Lower
    return qs.order_by("-display_priority", Lower("user__first_name"), Lower("user__last_name"), Lower("user__username"))


def transfer_perm_choices(employee):
    """What can be handed over for this person's leave: everything she can manage herself (in a fixed order)."""
    have = perms_of_employee(employee)
    return [p for p in PERMS if p in have]


def can(user, perm):
    return perm in get_perms(user)


# ---------------------------------------------------------------- dates
def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def fmt_date(d):
    """12-Oct-2026 - the one date format used everywhere in the portal."""
    return d.strftime("%d-%b-%Y") if d else "-"


def plain(n):
    """Decimal -> int / float for JSON and messages (1.0 -> 1, 1.5 -> 1.5)."""
    if n is None:
        return None
    f = float(n)
    return int(f) if f == int(f) else f


# ---------------------------------------------------------------- holidays / working days
# Off days: Sundays, every 2nd Saturday, government holidays and company holidays (Holiday table).
# Other Saturdays are working days.  Change with WEEKLY_OFF_DAYS in settings (Mon=0 ... Sun=6).
def weekly_off_days():
    return tuple(getattr(settings, "WEEKLY_OFF_DAYS", (6,)))


def is_second_saturday(d):
    return d.weekday() == 5 and 8 <= d.day <= 14


def _year_holidays(year):
    """{date: Holiday} for a whole year. Remembered for the length of one request, so a page that needs
    the holidays ten times (every project, every employee) still asks the database only once."""
    m = request_memo()
    key = ("holidays", year)
    if m is not None and key in m:
        return m[key]
    data = {h.date: h for h in Holiday.objects.filter(date__year=year)}
    if m is not None:
        m[key] = data
    return data


def load_holidays(start, end):
    """{date: Holiday} for start..end."""
    out = {}
    for year in range(start.year, end.year + 1):
        for d, h in _year_holidays(year).items():
            if start <= d <= end:
                out[d] = h
    return out


def off_reason(d, hol):
    """None for a working day, otherwise why it is a holiday ('Pongal', '2nd Saturday', 'Sunday')."""
    h = hol.get(d)
    if h:
        return h.name
    if is_second_saturday(d):
        return "2nd Saturday"
    if d.weekday() in weekly_off_days():
        return "Sunday" if d.weekday() == 6 else d.strftime("%A")
    return None


def is_working_day(d, hol=None):
    if hol is None:
        hol = load_holidays(d, d)
    return off_reason(d, hol) is None


def today_holiday(today=None):
    """Name of today's holiday or None (used for the banner on the home page)."""
    today = today or timezone.localdate()
    return off_reason(today, load_holidays(today, today))


def working_days_between(start, end, hol=None):
    """Working days from start to end, both included (holidays, Sundays, 2nd Saturdays left out)."""
    if not start or not end or end < start:
        return 0
    if hol is None:
        hol = load_holidays(start, end)
    return sum(1 for d in daterange(start, end) if off_reason(d, hol) is None)


weekdays_between = working_days_between  # old name, kept so nothing else breaks


def leave_days_for(start, end, half_day=False):
    """Days a leave request counts for (Decimal). A half day is 0.5 on a single working date."""
    if not start or not end:
        return Decimal("0")
    days = working_days_between(start, end)
    if half_day and start == end and days == 1:
        return Decimal("0.5")
    return Decimal(days)


def parse_period(params, today=None):
    """Monthly / yearly filter used on every page.  ?period=month&month=2026-10  or  ?period=year&year=2026"""
    today = today or timezone.localdate()
    mode = "year" if params.get("period") == "year" else "month"
    year, month = today.year, today.month
    raw_month = (params.get("month") or "").strip()
    if raw_month:
        try:
            y, m = raw_month.split("-")
            y, m = int(y), int(m)
            if 2000 <= y <= 2100 and 1 <= m <= 12:
                year, month = y, m
        except (ValueError, TypeError):
            pass
    raw_year = (params.get("year") or "").strip()
    if mode == "year":
        year = today.year
        if raw_year.isdigit() and 2000 <= int(raw_year) <= 2100:
            year = int(raw_year)
        start, end, label = date(year, 1, 1), date(year, 12, 31), str(year)
    else:
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        label = start.strftime("%B %Y")
    first_year = min(today.year - 3, year)
    return {
        "mode": mode, "sel": mode, "start": start, "end": end, "label": label, "year": year,
        "month_value": f"{year}-{month:02d}",
        "years": list(range(today.year + 1, first_year - 1, -1)),
    }


# ---------------------------------------------------------------- attendance
def today_record(employee):
    return Attendance.objects.filter(employee=employee, date=timezone.localdate()).first()


def clock_in(employee, work_mode=Attendance.MODE_OFFICE, field_type=""):
    """Returns (record, message, ok).  Field work must say On shore or Off shore."""
    if work_mode not in dict(Attendance.MODE_CHOICES):
        work_mode = Attendance.MODE_OFFICE
    if work_mode == Attendance.MODE_FIELD:
        if field_type not in dict(Attendance.FIELD_TYPE_CHOICES):
            return None, "Field work: please choose On shore or Off shore.", False
    else:
        field_type = ""
    now = timezone.localtime()
    record, created = Attendance.objects.get_or_create(
        employee=employee, date=now.date(),
        defaults={"in_time": now.time().replace(microsecond=0), "work_mode": work_mode, "field_type": field_type},
    )
    if not created:
        return record, "You have already clocked in today.", False
    return record, f"Clocked in successfully ({record.location_label}).", True


def clock_out(employee):
    now = timezone.localtime()
    record = today_record(employee)
    if not record or not record.in_time:
        return None, "Please clock in first.", False
    if record.out_time:
        return record, "You have already clocked out today.", False
    record.out_time = now.time().replace(microsecond=0)
    record.save()
    return record, "Clocked out successfully.", True


# ---------------------------------------------------------------- biometric device punches
MIN_PUNCH_GAP_SECONDS = 120   # a second punch within 2 minutes is the same touch (double scan) - ignored


def find_employee_by_device_id(user_id):
    """The machine's user ID is the Employee ID (EMP001). A plain number (1, 01, 001) means EMP001 as well."""
    uid = (user_id or "").strip()
    if not uid:
        return None
    emp = Employee.objects.filter(employee_id__iexact=uid).select_related("user").first()
    if emp or not uid.isdigit():
        return emp
    n = int(uid)
    for width in (3, 4, 2):
        emp = Employee.objects.filter(employee_id__iexact=f"EMP{n:0{width}d}").select_related("user").first()
        if emp:
            return emp
    return None


def record_punch(employee, when):
    """One fingerprint / face punch. First punch of the day = In time, later punches = Out time (the last one wins).
    Returns \"in\", \"out\" or \"ignored\".  `when` is an aware datetime."""
    when = timezone.localtime(when)
    day, t = when.date(), when.time().replace(microsecond=0)
    rec, created = Attendance.objects.get_or_create(
        employee=employee, date=day, defaults={"in_time": t, "work_mode": Attendance.MODE_OFFICE})
    if created:
        return "in"
    if rec.in_time is None:
        rec.in_time = t
        rec.save(update_fields=["in_time"])
        return "in"
    base = timezone.make_aware(datetime.combine(day, rec.in_time))
    last = timezone.make_aware(datetime.combine(day, rec.out_time or rec.in_time))
    if t < rec.in_time:                      # an older punch arrived late (device sent its backlog): earlier = In time
        old_in = rec.in_time
        rec.in_time = t
        if rec.out_time is None:
            rec.out_time = old_in
        rec.save(update_fields=["in_time", "out_time"])
        return "in"
    if (when - last).total_seconds() < MIN_PUNCH_GAP_SECONDS or (when - base).total_seconds() < MIN_PUNCH_GAP_SECONDS:
        return "ignored"
    if rec.out_time is None or t > rec.out_time:
        rec.out_time = t
        rec.save(update_fields=["out_time"])
        return "out"
    return "ignored"


def process_device_punches(device, items):
    """items = [(device_user_id, aware datetime), ...]. Saves the log and updates attendance. Returns a summary dict."""
    from .models import BiometricPunch
    summary = {"received": 0, "in": 0, "out": 0, "ignored": 0, "unknown": 0}
    for uid, when in sorted(items, key=lambda x: x[1]):
        emp = find_employee_by_device_id(uid)
        if emp is None or emp.status != Employee.STATUS_ACTIVE:
            result = BiometricPunch.RESULT_UNKNOWN
        else:
            result = record_punch(emp, when)
        BiometricPunch.objects.create(device=device, employee=emp, device_user_id=str(uid)[:40], punched_at=when, result=result)
        summary["received"] += 1
        summary["unknown" if result == "unknown" else result] += 1
    if device is not None:
        device.last_seen = timezone.now()
        device.save(update_fields=["last_seen"])
    return summary


# ---------------------------------------------------------------- leave
def load_leave_ranges(employee_ids):
    """{employee_id: [(start, end), ...]} of APPROVED leave."""
    ids = sorted(set(employee_ids))
    m = request_memo()
    key = ("leave_ranges", tuple(ids))
    if m is not None and key in m:
        return m[key]
    out = {}
    qs = LeaveRequest.objects.filter(employee_id__in=ids, status=LeaveRequest.STATUS_APPROVED)
    for emp_id, s, e in qs.values_list("employee_id", "start_date", "end_date"):
        out.setdefault(emp_id, []).append((s, e))
    if m is not None:
        m[key] = out
    return out


def leave_dates(ranges, start, end, hol=None):
    """Working days inside start..end that are covered by approved leave."""
    if hol is None:
        hol = load_holidays(start, end) if start <= end else {}
    days = set()
    for s, e in ranges or []:
        lo, hi = max(s, start), min(e, end)
        for d in daterange(lo, hi):
            if off_reason(d, hol) is None:
                days.add(d)
    return days


def months_credited(employee, year, today=None):
    """How many months of monthly credit the employee has earned in `year` (joining month counts)."""
    today = today or timezone.localdate()
    if year > today.year:
        return 0
    last = 12 if year < today.year else today.month
    first = 1
    jd = getattr(employee, "joining_date", None)
    if jd:
        if jd.year > year:
            return 0
        if jd.year == year:
            first = jd.month
    return max(last - first + 1, 0)


def _request_days(r, lo, hi, hol):
    if lo == r.start_date and hi == r.end_date:
        return Decimal(r.days)
    return Decimal(working_days_between(lo, hi, hol))


def _leave_types():
    m = request_memo()
    if m is not None and "leave_types" in m:
        return m["leave_types"]
    types = list(LeaveType.objects.all())
    if m is not None:
        m["leave_types"] = types
    return types


def leave_balances(employee, year=None, today=None, reqs=None, hol=None):
    """Leave credit details for one year, per leave type.

    Casual Leave (monthly_credit 1.5) earns 1.5 days every month. Loss of Pay is unlimited.
    credit - used (approved) = balance;  pending = waiting for HR / manager / admin.
    `reqs` / `hol` let leave_overview() hand in data it already loaded for many employees at once.
    """
    today = today or timezone.localdate()
    year = year or today.year
    y0, y1 = date(year, 1, 1), date(year, 12, 31)
    if hol is None:
        hol = load_holidays(y0, y1)
    if reqs is None:
        reqs = LeaveRequest.objects.filter(employee=employee, start_date__lte=y1, end_date__gte=y0).exclude(
            status=LeaveRequest.STATUS_REJECTED
        )
    used, pending = {}, {}
    for r in reqs:
        days = _request_days(r, max(r.start_date, y0), min(r.end_date, y1), hol)
        bucket = used if r.status == LeaveRequest.STATUS_APPROVED else pending
        bucket[r.leave_type_id] = bucket.get(r.leave_type_id, Decimal("0")) + days
    months = months_credited(employee, year, today)
    rows = []
    for t in _leave_types():
        u, p = used.get(t.id, Decimal("0")), pending.get(t.id, Decimal("0"))
        if t.is_lop:
            rows.append({"type": t, "unlimited": True, "credit": None, "used": u, "pending": p, "balance": None})
            continue
        credit = Decimal(t.monthly_credit) * months if t.monthly_credit and t.monthly_credit > 0 else Decimal(t.annual_credit)
        rows.append({"type": t, "unlimited": False, "credit": credit, "used": u, "pending": p, "balance": credit - u})
    limited = [r for r in rows if not r["unlimited"]]
    totals = {k: sum((r[k] for r in limited), Decimal("0")) for k in ("credit", "used", "pending", "balance")}
    totals["lop_used"] = sum((r["used"] for r in rows if r["unlimited"]), Decimal("0"))
    totals["taken"] = totals["used"] + totals["lop_used"]
    return {"year": year, "rows": rows, "totals": totals, "months": months}


def leave_overview(year=None):
    """HR view: credit / taken / balance of every active employee + who has not taken any leave.

    Loads everything with 3 queries in total (employees, leave requests, holidays) - however many
    employees there are.
    """
    year = year or timezone.localdate().year
    y0, y1 = date(year, 1, 1), date(year, 12, 31)
    employees = list(staff_qs(Employee.objects.select_related("user", "department", "designation").filter(
        status=Employee.STATUS_ACTIVE)))
    by_emp = defaultdict(list)
    for r in LeaveRequest.objects.filter(
            employee_id__in=[e.pk for e in employees], start_date__lte=y1, end_date__gte=y0
    ).exclude(status=LeaveRequest.STATUS_REJECTED):
        by_emp[r.employee_id].append(r)
    hol = load_holidays(y0, y1)
    rows = []
    for e in employees:
        t = leave_balances(e, year, reqs=by_emp.get(e.pk, []), hol=hol)["totals"]
        rows.append({
            "employee": e, "credit": t["credit"], "used": t["used"], "pending": t["pending"],
            "balance": t["balance"], "lop": t["lop_used"], "taken": t["taken"], "no_leave": t["taken"] == 0,
        })
    return {"year": year, "rows": rows, "no_leave": [r["employee"] for r in rows if r["no_leave"]]}


def validate_leave(employee, leave_type, start, end, exclude_pk=None, half_day=False):
    """Returns an error string, or None when the leave request is fine."""
    if not (employee and leave_type and start and end):
        return None
    if end < start:
        return "End date cannot be before the start date."
    if half_day and start != end:
        return "Half day is only possible for a single date."
    days = leave_days_for(start, end, half_day)
    if days == 0:
        return "The selected dates have no working days (Sundays, 2nd Saturdays and holidays are not counted)."
    clash = LeaveRequest.objects.filter(
        employee=employee, start_date__lte=end, end_date__gte=start
    ).exclude(status=LeaveRequest.STATUS_REJECTED)
    if exclude_pk:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        return "This employee already has leave in the selected dates."
    if leave_type.is_lop:
        return None
    if start.year == end.year:
        # credit counts up to the month the leave starts (CL is earned 1.5 days every month)
        as_of = max(start, timezone.localdate())
        bal = next((r for r in leave_balances(employee, start.year, today=as_of)["rows"]
                    if r["type"].pk == leave_type.pk), None)
        own = Decimal("0")
        if exclude_pk:
            old = LeaveRequest.objects.filter(pk=exclude_pk, leave_type=leave_type).exclude(
                status=LeaveRequest.STATUS_REJECTED).first()
            own = Decimal(old.days) if old else Decimal("0")
        if bal and days > bal["balance"] - bal["pending"] + own:
            left = max(bal["balance"] - bal["pending"] + own, Decimal("0"))
            return (f"Not enough {leave_type.name} credit: {plain(left)} day(s) left, {plain(days)} requested. "
                    "Please apply the extra days as Loss of Pay (LOP).")
    return None


# ---------------------------------------------------------------- attendance summaries
def _summarize(records, leave_set, start, end, today, hol):
    """Core of the automatic attendance + working-day calculation.

    working_days = working days up to today (Sundays, 2nd Saturdays, government / company holidays left out)
    leave = approved leave days with no attendance
    absent = working days with neither attendance nor leave (today is not counted until the day ends)
    pending = 1 when today is a working day and the person has not clocked in yet (so working = present + leave + absent + pending)
    net_working_days = working_days - leave    |  office / field = present days by work mode
    """
    last = min(end, today)
    out = dict(working_days=0, present=0, leave=0, absent=0, office=0, field=0, net_working_days=0, percent=0,
               holidays=0, pending=0, field_on=0, field_off=0, field_unset=0)
    # working days in the WHOLE month / year (e.g. "Working days in October"), not only up to today
    out["period_working_days"] = working_days_between(start, end, hol)
    if last < start:
        return out
    present_working = 0
    for d in daterange(start, last):
        working = off_reason(d, hol) is None
        rec = records.get(d)
        if working:
            out["working_days"] += 1
        else:
            out["holidays"] += 1
        if rec:
            out["present"] += 1
            if rec.work_mode == Attendance.MODE_FIELD:
                out["field"] += 1
                if rec.field_type == Attendance.FIELD_ONSHORE:
                    out["field_on"] += 1
                elif rec.field_type == Attendance.FIELD_OFFSHORE:
                    out["field_off"] += 1
                else:
                    out["field_unset"] += 1
            else:
                out["office"] += 1
            if working:
                present_working += 1
        elif working and d in leave_set:
            out["leave"] += 1
        elif working and d < today:
            out["absent"] += 1
        elif working and d == today:
            out["pending"] += 1      # today is not over yet: not present, not absent - shown as "Today (pending)"
    out["net_working_days"] = out["working_days"] - out["leave"]
    net = out["net_working_days"]
    out["percent"] = min(round(present_working / net * 100), 100) if net > 0 else 0
    return out


def _load(employee, start, end):
    records = {a.date: a for a in Attendance.objects.filter(employee=employee, date__range=(start, end))}
    hol = load_holidays(start, end)
    leave_set = leave_dates(load_leave_ranges([employee.pk]).get(employee.pk), start, end, hol)
    return records, leave_set, hol


def load_period(employee, start, end):
    """Attendance records, leave days and holidays of one employee for start..end, loaded once so the
    summary and the daily list on the same page can share it."""
    return _load(employee, start, end)


def period_summary(employee, start, end, today=None, loaded=None):
    today = today or timezone.localdate()
    records, leave_set, hol = loaded or _load(employee, start, end)
    return _summarize(records, leave_set, start, end, today, hol)


def month_summary(employee, today=None):
    today = today or timezone.localdate()
    start = date(today.year, today.month, 1)
    end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    s = period_summary(employee, start, end, today)
    s["month"] = today.strftime("%B %Y")
    return s


def bulk_period_summaries(employees, start, end, today=None, leave_map=None):
    """{employee.pk: summary} for MANY employees with only 3 queries (attendance, holidays, leave).

    Same numbers as period_summary(), but without one round trip per employee - this is what keeps
    the Admin home, Attendance and Employee pages quick even with a hosted database.
    """
    today = today or timezone.localdate()
    ids = [e.pk for e in employees]
    recs = defaultdict(dict)
    if ids and start <= min(end, today):
        for a in Attendance.objects.filter(employee_id__in=ids, date__range=(start, min(end, today))):
            recs[a.employee_id][a.date] = a
    hol = load_holidays(start, end)
    if leave_map is None:
        leave_map = load_leave_ranges(ids)
    return {
        e.pk: _summarize(recs[e.pk], leave_dates(leave_map.get(e.pk), start, end, hol), start, end, today, hol)
        for e in employees
    }


def month_percent_map(employees, today=None):
    """{employee.pk: this month's attendance %} for many employees with only 3 queries."""
    today = today or timezone.localdate()
    start = date(today.year, today.month, 1)
    end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return {pk: s["percent"] for pk, s in bulk_period_summaries(employees, start, end, today).items()}


def yearly_breakdown(employee, year, today=None, loaded=None):
    """12 monthly summaries + a yearly total (one DB round-trip for the whole year)."""
    today = today or timezone.localdate()
    y0, y1 = date(year, 1, 1), date(year, 12, 31)
    records, leave_set, hol = loaded or _load(employee, y0, y1)
    rows = []
    for m in range(1, 13):
        start = date(year, m, 1)
        if start > today:
            break
        end = date(year, m, calendar.monthrange(year, m)[1])
        r = _summarize(records, leave_set, start, end, today, hol)
        r["month"] = start.strftime("%B")
        rows.append(r)
    total = _summarize(records, leave_set, y0, y1, today, hol)
    return rows, total


def attendance_rows(employee, start, end, today=None, loaded=None):
    """Daily in/out list for start..end (newest first), up to today."""
    today = today or timezone.localdate()
    last = min(end, today)
    if last < start:
        return []
    records, leave_set, hol = loaded or _load(employee, start, last)
    rows = []
    for d in reversed(list(daterange(start, last))):
        rec = records.get(d)
        hours = None
        if rec and rec.in_time and rec.out_time:
            secs = (datetime.combine(d, rec.out_time) - datetime.combine(d, rec.in_time)).total_seconds()
            hours = f"{int(secs // 3600)}h {int(secs % 3600 // 60):02d}m"
        reason = off_reason(d, hol)
        if rec:
            status = "Present"
        elif reason:
            status = "Holiday"
        elif d in leave_set:
            status = "Leave"
        elif d == today:
            status = "Not yet"
        else:
            status = "Absent"
        label = "Today" if d == today else "Yesterday" if d == today - timedelta(days=1) else ""
        rows.append({
            "date": d, "label": label, "in_time": rec.in_time if rec else None,
            "out_time": rec.out_time if rec else None, "hours": hours, "status": status,
            "work_mode": rec.location_label if rec else "", "is_field": bool(rec and rec.work_mode == Attendance.MODE_FIELD),
            "holiday_name": reason or "",
        })
    return rows


def attendance_history(employee, days=30):
    """Daily in/out list, newest first (today, yesterday, ...)."""
    today = timezone.localdate()
    return attendance_rows(employee, today - timedelta(days=days - 1), today, today)


# ---------------------------------------------------------------- projects
def sync_assignments(project, employees, modes=None, is_new=False, today=None, details=None, field_types=None):
    """Keep ProjectAssignment rows equal to the project's members.

    `modes` = {employee.pk: "office" | "field"}, `field_types` = {employee.pk: "onshore" | "offshore"} (field work only).
    Returns the employees that were newly added.
    """
    today = today or timezone.localdate()
    modes = modes or {}
    field_types = field_types or {}
    details = details or {}   # {employee.pk: (work description, days assigned or None)}
    existing = {a.employee_id: a for a in project.assignments.all()}
    wanted = {e.pk: e for e in employees}
    added = []
    for pk, e in wanted.items():
        mode = modes.get(pk) or Attendance.MODE_OFFICE
        ftype = (field_types.get(pk) or "") if mode == Attendance.MODE_FIELD else ""
        a = existing.get(pk)
        work, days = details.get(pk, ("", None))
        if a:
            changed = []
            if pk in modes and (a.work_mode != mode or a.field_type != ftype):
                a.work_mode, a.field_type = mode, ftype
                changed += ["work_mode", "field_type"]
            if pk in details and (a.work_description != work or a.assigned_days != days):
                a.work_description, a.assigned_days = work, days
                changed += ["work_description", "assigned_days"]
            if changed:
                a.save(update_fields=changed)
        else:
            start = project.start_date if (is_new and project.start_date) else today
            ProjectAssignment.objects.create(project=project, employee=e, work_mode=mode, field_type=ftype, assigned_on=start,
                                             work_description=work, assigned_days=days)
            added.append(e)
    for pk, a in existing.items():
        if pk not in wanted:
            a.delete()
    return added


def latest_percent_map(project):
    """{employee_id: (percent, date)} - the most recent daily update of every member."""
    out = {}
    for u in project.updates.all():  # ordered newest first
        out.setdefault(u.employee_id, (u.percent, u.date))
    return out


def recompute_completion(project):
    """Project % = average of every member's latest reported % (members with no update count as 0)."""
    member_ids = list(project.assignments.values_list("employee_id", flat=True))
    if not member_ids:
        return project.completion
    latest = latest_percent_map(project)
    if not latest:
        return project.completion
    pct = round(sum(latest.get(i, (0, None))[0] for i in member_ids) / len(member_ids))
    project.completion = max(0, min(100, pct))
    if project.completion == 100:
        project.status = Project.STATUS_COMPLETED
    elif project.status == Project.STATUS_COMPLETED:
        project.status = Project.STATUS_INPROGRESS
    project.save(update_fields=["completion", "status"])
    return project.completion


def submit_project_update(employee, project, percent, note="", today=None):
    """Daily progress from an employee. Returns (update, message, ok)."""
    today = today or timezone.localdate()
    if not project.assignments.filter(employee=employee).exists():
        return None, "You are not assigned to this project.", False
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return None, "Enter the completion percentage as a number (0-100).", False
    if not 0 <= percent <= 100:
        return None, "Completion must be between 0 and 100.", False
    upd, _ = ProjectUpdate.objects.update_or_create(
        project=project, employee=employee, date=today,
        defaults={"percent": percent, "note": (note or "").strip()[:255]},
    )
    recompute_completion(project)
    return upd, f"Update saved for {project.name}: {percent}% done.", True


def project_metrics(project, leave_map=None, today=None):
    """Project working days that take every assigned employee's approved leave into account.

    For each employee, from the day they were assigned:
      span_days   = working days (Sundays / 2nd Saturdays / holidays left out) up to today or the end date
      leave_days  = that employee's approved leave inside the span
      net_days    = span_days - leave_days            <- real days worked on the project
      planned_net = planned working days of the project - approved leave in that plan (future leave too)
    man_days = sum of every employee's net_days.
    """
    today = today or timezone.localdate()
    assignments = {a.employee_id: a for a in project.assignments.all()}
    employees = list(project.employees.all())
    if leave_map is None:
        leave_map = load_leave_ranges([e.pk for e in employees])
    last = min(project.end_date or today, today)

    def start_for(a):
        # an employee counts from the day they were assigned, but never before the project start date
        s0 = a.assigned_on if a and a.assigned_on else None
        if s0 and project.start_date:
            return max(s0, project.start_date)
        return s0 or project.start_date

    starts = [start_for(a) for a in assignments.values()] + [project.start_date]
    lo_all = min([d for d in starts if d] or [today])
    hi_all = max(project.end_date or today, today)
    hol = load_holidays(min(lo_all, today), hi_all)
    latest = latest_percent_map(project)
    rows, span = [], 0
    if project.start_date and last >= project.start_date:
        span = working_days_between(project.start_date, last, hol)
    for e in employees:
        a = assignments.get(e.pk)
        start = start_for(a)
        mode = a.work_mode if a else Attendance.MODE_OFFICE
        label = a.location_label if a else "Office"
        e_span = lv = 0
        if start and last >= start:
            e_span = working_days_between(start, last, hol)
            lv = len(leave_dates(leave_map.get(e.pk), start, last, hol))
        planned = planned_net = None
        if start and project.end_date and project.end_date >= start:
            planned = working_days_between(start, project.end_date, hol)
            planned_net = planned - len(leave_dates(leave_map.get(e.pk), start, project.end_date, hol))
        pct, pct_date = latest.get(e.pk, (0, None))
        rows.append({
            "employee": e, "assignment": a, "work_description": a.work_description if a else "",
            "assigned_days": (a.assigned_days if a and a.assigned_days else planned), "work_mode": mode,
            "work_mode_display": label,
            "start": start, "span_days": e_span, "leave_days": lv, "net_days": e_span - lv,
            "planned_days": planned, "planned_net_days": planned_net,
            "percent": pct, "percent_date": pct_date,
        })
    planned_total = working_days_between(project.start_date, project.end_date, hol) \
        if project.start_date and project.end_date else None
    remaining = None
    if project.end_date and project.end_date > today:
        remaining = working_days_between(today + timedelta(days=1), project.end_date, hol)
    return {
        "span_days": span,
        "leave_days": sum(r["leave_days"] for r in rows),
        "man_days": sum(r["net_days"] for r in rows),
        "planned_days": planned_total,
        "remaining_days": remaining,
        "rows": rows,
    }


def employee_project_view(employee, today=None):
    """Projects of one employee split into current / completed, with work mode and own net days."""
    today = today or timezone.localdate()
    leave_map = load_leave_ranges([employee.pk])
    projects = list(Project.objects.filter(employees=employee).prefetch_related(
        "employees__user", "assignments", "updates").distinct())
    today_updates = {u.project_id: u for u in ProjectUpdate.objects.filter(employee=employee, date=today)}
    out = {"current": [], "completed": [], "office_days": 0, "field_days": 0}
    for p in projects:
        m = project_metrics(p, leave_map, today)
        mine = next((r for r in m["rows"] if r["employee"].pk == employee.pk), None) or {
            "leave_days": 0, "net_days": 0, "work_mode": Attendance.MODE_OFFICE, "work_mode_display": "Office",
            "percent": 0, "percent_date": None, "planned_days": None, "planned_net_days": None, "start": None}
        p.metrics = m
        p.mine = mine
        p.my_leave_days, p.my_net_days = mine["leave_days"], mine["net_days"]
        p.my_mode, p.my_mode_display = mine["work_mode"], mine["work_mode_display"]
        p.my_percent = mine["percent"]
        p.today_update = today_updates.get(p.pk)
        key = "completed" if p.status == Project.STATUS_COMPLETED else "current"
        out[key].append(p)
        if mine["work_mode"] == Attendance.MODE_FIELD:
            out["field_days"] += mine["net_days"]
        else:
            out["office_days"] += mine["net_days"]
    return out
