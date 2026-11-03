import re
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, help_text="Short description shown on the employee home page")
    sort_order = models.PositiveSmallIntegerField(
        default=100, help_text="Order in the Employee table (small number first). Drivers / housekeeping groups go last.")

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Team(models.Model):
    name = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="teams")

    class Meta:
        ordering = ["name"]
        unique_together = ("name", "department")

    def __str__(self):
        return self.name


class Designation(models.Model):
    """Job title only. Permissions are NOT tied to the designation - Admin gives them to each person (Permissions page)."""

    name = models.CharField(max_length=100, unique=True)
    rank = models.PositiveSmallIntegerField(
        default=50, help_text="Seniority in the Employee table: 1 = Managing Director, 2 = Director, 3 = Associate Director ... "
                              "1 to 3 are listed first (top management), then department by department")
    description = models.CharField(max_length=255, blank=True, help_text="Shown in the employee's personal information")

    class Meta:
        ordering = ["rank", "name"]

    def save(self, *args, **kwargs):
        if self._state.adding and self.rank == 50:      # new designation left at the default: rank it from its name
            from .hierarchy import rank_for
            self.rank = rank_for(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


def next_employee_code(prefix="EMP", width=3):
    """EMP001, EMP002 ... always one more than the highest existing code."""
    highest = 0
    for code in Employee.objects.values_list("employee_id", flat=True):
        m = re.fullmatch(rf"{prefix}(\d+)", code or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}{highest + 1:0{width}d}"


class Employee(models.Model):
    ROLE_EMPLOYEE = "employee"
    ROLE_HR = "hr"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = [
        (ROLE_EMPLOYEE, "Employee"),
        (ROLE_HR, "HR"),
        (ROLE_ADMIN, "Super Admin"),
    ]
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [(STATUS_ACTIVE, "Active"), (STATUS_INACTIVE, "Inactive")]
    BLOOD_GROUPS = [(b, b) for b in ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employee")
    employee_id = models.CharField("Employee ID", max_length=20, unique=True, blank=True,
                                   help_text="Unique ID (also the user ID on the biometric device). Leave blank to auto-generate (EMP001, EMP002 ...)")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    designation = models.ForeignKey(Designation, null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    joining_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_EMPLOYEE)
    display_priority = models.PositiveSmallIntegerField(
        "List priority", default=50, validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Order in the Employee table: 100 = shown first, 1 = shown last. Same number = A to Z by name.")
    # permissions are given to the PERSON (not the designation). Employees and Projects each have View / Create / Edit.
    can_view_employees = models.BooleanField(default=False, help_text="See the employee list and other people's profiles")
    can_create_employees = models.BooleanField(default=False, help_text="Add new employees")
    can_edit_employees = models.BooleanField(default=False, help_text="Edit / delete employees, departments and teams")
    can_view_projects = models.BooleanField(default=False, help_text="See ALL projects (otherwise only the projects the person is assigned to)")
    can_create_projects = models.BooleanField(default=False, help_text="Create new projects and give them their first members")
    can_edit_projects = models.BooleanField(default=False, help_text="Edit / delete projects and change their members")
    can_manage_leave = models.BooleanField(default=False, help_text="Approve / reject leave (people choose who to send their leave request to)")
    can_manage_attendance = models.BooleanField(default=False, help_text="Add / edit attendance records")
    can_manage_groups = models.BooleanField(default=False, help_text="Create / edit / delete chat groups")
    photo_updated = models.DateTimeField(null=True, blank=True, editable=False)   # set when a profile photo exists
    phone = models.CharField("Contact number", max_length=20, blank=True)
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS, blank=True)
    date_of_birth = models.DateField("Date of birth", null=True, blank=True)
    emergency_name = models.CharField("Emergency contact name", max_length=100, blank=True)
    emergency_phone = models.CharField("Emergency contact number", max_length=20, blank=True)
    emergency_relation = models.CharField("Relationship", max_length=50, blank=True)
    emergency_name2 = models.CharField("Emergency contact 2 - name", max_length=100, blank=True)
    emergency_phone2 = models.CharField("Emergency contact 2 - number", max_length=20, blank=True)
    emergency_relation2 = models.CharField("Emergency contact 2 - relationship", max_length=50, blank=True)
    permanent_address = models.TextField("Permanent address", blank=True)
    current_address = models.TextField("Current address", blank=True)
    aadhaar_number = models.CharField("Aadhaar card number", max_length=12, blank=True)
    pan_number = models.CharField("PAN card number", max_length=10, blank=True)
    vehicle_number = models.CharField("Vehicle number", max_length=20, blank=True)
    medical_insurance_number = models.CharField("Medical insurance number", max_length=40, blank=True)
    doctor_name = models.CharField("Doctor name", max_length=100, blank=True)
    doctor_phone = models.CharField("Doctor contact number", max_length=20, blank=True)
    doctor_location = models.CharField("Doctor location", max_length=150, blank=True)
    doctor_location2 = models.CharField("Doctor 2 - location", max_length=150, blank=True)
    doctor_location3 = models.CharField("Doctor 3 - location", max_length=150, blank=True)
    doctor_name2 = models.CharField("Doctor 2 - name", max_length=100, blank=True)
    doctor_phone2 = models.CharField("Doctor 2 - contact number", max_length=20, blank=True)
    doctor_name3 = models.CharField("Doctor 3 - name", max_length=100, blank=True)
    doctor_phone3 = models.CharField("Doctor 3 - contact number", max_length=20, blank=True)
    # Shown to Admin / HR and to the employee himself (requested feature). Kept in plain text on purpose.
    visible_password = models.CharField(max_length=128, blank=True, editable=False)

    class Meta:
        ordering = ["employee_id"]

    @property
    def show_code(self):
        """The Super Admin has no employee code on screen."""
        return self.role != self.ROLE_ADMIN

    @property
    def aadhaar_masked(self):
        a = self.aadhaar_number or ""
        return ("XXXX XXXX " + a[-4:]) if len(a) == 12 else a

    @property
    def aadhaar_display(self):
        a = self.aadhaar_number or ""
        return f"{a[0:4]} {a[4:8]} {a[8:12]}" if len(a) == 12 else a

    @property
    def pan_masked(self):
        p = self.pan_number or ""
        return ("XXXXX" + p[5:]) if len(p) == 10 else p

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def is_manager(self):
        return self.role in (self.ROLE_HR, self.ROLE_ADMIN)

    def save(self, *args, **kwargs):
        if not self.employee_id:
            self.employee_id = next_employee_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee_id} - {self.full_name}"


class EmployeePhoto(models.Model):
    """Profile photo, kept in the database (works with SQLite and Neon / PostgreSQL, no media folder needed).
    A separate table so the photo bytes are only read when the picture itself is shown."""
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="photo")
    data = models.BinaryField()
    content_type = models.CharField(max_length=20, default="image/jpeg")

    def __str__(self):
        return f"Photo of {self.employee_id}"


def location_label(mode, field_type=""):
    """Office -> "Office"; Field -> "Field (On shore)" / "Field (Off shore)" (just "Field" for old rows)."""
    if mode == "field":
        kind = dict(Attendance.FIELD_TYPE_CHOICES).get(field_type)
        return f"Field ({kind})" if kind else "Field"
    return "Office"


class Attendance(models.Model):
    MODE_OFFICE = "office"
    MODE_FIELD = "field"
    MODE_CHOICES = [(MODE_OFFICE, "Office"), (MODE_FIELD, "Field")]
    FIELD_ONSHORE = "onshore"
    FIELD_OFFSHORE = "offshore"
    FIELD_TYPE_CHOICES = [(FIELD_ONSHORE, "On shore"), (FIELD_OFFSHORE, "Off shore")]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    in_time = models.TimeField(null=True, blank=True)
    out_time = models.TimeField(null=True, blank=True)
    work_mode = models.CharField(max_length=6, choices=MODE_CHOICES, default=MODE_OFFICE)
    field_type = models.CharField("Field type", max_length=8, choices=FIELD_TYPE_CHOICES, blank=True, default="")

    class Meta:
        ordering = ["-date"]
        unique_together = ("employee", "date")

    @property
    def location_label(self):
        return location_label(self.work_mode, self.field_type)

    def __str__(self):
        return f"{self.employee.employee_id} {self.date}"


class Project(models.Model):
    STATUS_INPROGRESS = "inprogress"
    STATUS_COMPLETED = "completed"
    STATUS_ONHOLD = "onhold"
    STATUS_CHOICES = [
        (STATUS_INPROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_ONHOLD, "On Hold"),
    ]

    name = models.CharField("Project title", max_length=150)
    client = models.CharField(max_length=150, blank=True)
    location = models.CharField("Project location", max_length=200, blank=True)
    client_location = models.CharField("Client location", max_length=200, blank=True)
    project_code = models.CharField("Project code", max_length=50, blank=True)
    description = models.TextField("Details of work", blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_INPROGRESS)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    completion = models.PositiveSmallIntegerField(
        "Completion %", default=0, validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="0 - 100. Setting 100 marks the project as completed.",
    )
    employees = models.ManyToManyField(Employee, blank=True, related_name="projects")

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.name


class LeaveType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    annual_credit = models.PositiveSmallIntegerField(default=12, help_text="Leave days credited to every employee per year")
    monthly_credit = models.DecimalField(
        max_digits=4, decimal_places=1, default=Decimal("0"),
        help_text="Days credited every month (e.g. 1.5 for Casual Leave). 0 = use the yearly credit instead",
    )
    is_lop = models.BooleanField(
        "Loss of Pay (unlimited)", default=False,
        help_text="Loss of Pay has no credit limit - used when the Casual Leave credit is finished",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_APPROVED, "Approved"), (STATUS_REJECTED, "Rejected")]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leaves")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    start_date = models.DateField()
    end_date = models.DateField()
    half_day = models.BooleanField(default=False, help_text="Half day (single date only)")
    days = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("0"),
                               help_text="Working days (holidays excluded) - calculated automatically")
    reason = models.CharField(max_length=255, blank=True)
    approver = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL, related_name="leave_to_approve",
        verbose_name="Send request to", help_text="The person who approves this leave")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]

    def save(self, *args, **kwargs):
        from .services import leave_days_for

        self.days = leave_days_for(self.start_date, self.end_date, self.half_day)
        super().save(*args, **kwargs)
        # permissions handed over for this leave follow the leave dates (and go away if it is declined)
        if self.status == self.STATUS_REJECTED:
            self.transfers.all().delete()
        else:
            self.transfers.update(start_date=self.start_date, end_date=self.end_date)

    def __str__(self):
        return f"{self.employee.employee_id} {self.leave_type} {self.start_date}..{self.end_date}"


class Holiday(models.Model):
    """Government / company holidays. 2nd Saturdays and Sundays are handled in code (services.off_reason)."""

    KIND_GOVT = "government"
    KIND_COMPANY = "company"
    KIND_CHOICES = [(KIND_GOVT, "Government holiday"), (KIND_COMPANY, "Company holiday")]

    date = models.DateField(unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_GOVT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} {self.name}"


class ProjectAssignment(models.Model):
    """One row per (project, employee): whether the person works in the office or in the field."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="assignments")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="assignments")
    work_mode = models.CharField(max_length=6, choices=Attendance.MODE_CHOICES, default=Attendance.MODE_OFFICE)
    field_type = models.CharField("Field type", max_length=8, choices=Attendance.FIELD_TYPE_CHOICES, blank=True, default="")
    assigned_on = models.DateField(null=True, blank=True)
    work_description = models.TextField("Work assigned", blank=True)
    assigned_days = models.PositiveSmallIntegerField("Days assigned", null=True, blank=True)

    class Meta:
        unique_together = ("project", "employee")

    @property
    def location_label(self):
        return location_label(self.work_mode, self.field_type)

    def __str__(self):
        return f"{self.project} - {self.employee.employee_id} ({self.location_label})"


class ProjectUpdate(models.Model):
    """Daily progress an employee reports for a project (cumulative % of their part)."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="updates")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="project_updates")
    date = models.DateField()
    percent = models.PositiveSmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    note = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        unique_together = ("project", "employee", "date")

    def __str__(self):
        return f"{self.project} {self.employee.employee_id} {self.date} {self.percent}%"


class Notification(models.Model):
    """In-app message + WhatsApp status (link = click-to-chat link, sent = sent by WhatsApp Cloud API)."""

    WA_LINK = "link"
    WA_SENT = "sent"
    WA_FAILED = "failed"
    WA_NOPHONE = "nophone"

    recipient = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="notifications")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=20, default="info")
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    whatsapp = models.CharField(max_length=10, default=WA_LINK)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"to {self.recipient.employee_id}: {self.message[:40]}"


class PermissionTransfer(models.Model):
    """HR / manager is on leave: her permissions are handed to another employee for the same days."""

    from_employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="transfers_out")
    to_employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="transfers_in")
    leave = models.ForeignKey(LeaveRequest, null=True, blank=True, on_delete=models.CASCADE, related_name="transfers")
    start_date = models.DateField()
    end_date = models.DateField()
    perms = models.CharField(max_length=80, blank=True, help_text="comma separated: employees,projects,leave,attendance")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]

    def perm_set(self):
        return {p for p in self.perms.split(",") if p}

    def __str__(self):
        return f"{self.from_employee} -> {self.to_employee} {self.start_date}..{self.end_date}"


class Group(models.Model):
    """A chat group the Admin / HR / Managing Director creates: pick any employees (or a whole department)."""

    name = models.CharField(max_length=100, unique=True)
    members = models.ManyToManyField(Employee, blank=True, related_name="chat_groups")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class GroupMessage(models.Model):
    """A message sent to a group (everybody in it gets it in the portal and on WhatsApp)."""

    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.CASCADE, related_name="messages")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")  # old v8 rows
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.group or self.department}: {self.message[:40]}"


def _new_device_key():
    import secrets
    return secrets.token_urlsafe(24)


class BiometricDevice(models.Model):
    """A fingerprint / face machine. It sends every punch to the portal; the portal turns it into In / Out time.

    Two ways to connect (see CHANGES_v16.md):
      * JSON push  - POST /api/biometric/punch/   with header  X-Device-Key: <api_key>
      * ZKTeco ADMS push - set the machine's cloud server to this portal; the machine's serial number must match `serial`.
    The user ID stored on the machine must be the person's Employee ID (EMP001 ...) or just its number (1 = EMP001).
    """

    name = models.CharField(max_length=100, help_text="e.g. Main gate, Coimbatore office")
    location = models.CharField(max_length=150, blank=True)
    serial = models.CharField("Device serial number", max_length=60, blank=True, db_index=True,
                              help_text="Only for ZKTeco ADMS machines (printed on the machine / shown in its menu)")
    api_key = models.CharField(max_length=64, unique=True, default=_new_device_key, editable=False)
    is_active = models.BooleanField(default=True)
    last_seen = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class BiometricPunch(models.Model):
    """Log of every punch received (kept even when it could not be matched to an employee)."""

    RESULT_IN = "in"
    RESULT_OUT = "out"
    RESULT_SAME = "ignored"
    RESULT_UNKNOWN = "unknown"
    RESULT_LEAVE = "skipped"

    device = models.ForeignKey(BiometricDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name="punches")
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL, related_name="punches")
    device_user_id = models.CharField(max_length=40, blank=True)
    punched_at = models.DateTimeField()
    result = models.CharField(max_length=10, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-punched_at", "-id"]
        indexes = [models.Index(fields=["-punched_at"])]

    def __str__(self):
        return f"{self.device_user_id} {self.punched_at:%Y-%m-%d %H:%M} {self.result}"
