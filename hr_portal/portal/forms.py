import re

from django.utils import timezone

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q as models_q

from . import services
from .models import (
    Attendance, Department, Designation, Employee, Group, Holiday, LeaveRequest, LeaveType, PermissionTransfer, Project, Team,
    next_employee_code,
)

User = get_user_model()


class BootstrapMixin:
    def _style(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = "form-select"
            else:
                widget.attrs["class"] = "form-control"


PERM_FIELDS = (
    "can_view_employees", "can_create_employees", "can_edit_employees",
    "can_view_projects", "can_create_projects", "can_edit_projects",
    "can_manage_leave", "can_manage_attendance", "can_manage_groups",
)

PERSONAL_FIELDS = (
    "phone", "blood_group", "date_of_birth",
    "emergency_name", "emergency_phone", "emergency_relation",
    "emergency_name2", "emergency_phone2", "emergency_relation2",
    "permanent_address", "current_address", "aadhaar_number", "pan_number", "vehicle_number", "medical_insurance_number",
    "doctor_name", "doctor_phone", "doctor_name2", "doctor_phone2", "doctor_name3", "doctor_phone3",
    "doctor_location", "doctor_location2", "doctor_location3",
)


def _clean_phone(value, label):
    """Keeps + and digits only; 10 to 13 digits. Empty stays empty."""
    v = re.sub(r"[\s\-()]", "", (value or "").strip())
    if not v:
        return ""
    digits = v[1:] if v.startswith("+") else v
    if not digits.isdigit() or not 10 <= len(digits) <= 13:
        raise forms.ValidationError(f"{label}: enter a valid number, e.g. 9876543210.")
    return v


class PersonalDetailsMixin:
    """Checks shared by the Add / Edit Employee form and the 'edit my details' form."""

    def _setup_personal(self):
        f = self.fields
        f["phone"].label = "Contact number (WhatsApp)"
        f["phone"].widget.attrs["placeholder"] = "10 digit number, e.g. 9876543210"
        f["phone"].required = True
        f["blood_group"].choices = [("", "Select blood group")] + list(Employee.BLOOD_GROUPS)
        f["blood_group"].required = True
        f["phone"].error_messages["required"] = "Enter the contact number."
        f["blood_group"].error_messages["required"] = "Select the blood group."
        f["date_of_birth"] = forms.DateField(
            label="Date of birth", required=False,
            widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off", "placeholder": "dd-mm-yyyy"}, format="%Y-%m-%d"))
        for n in ("", "2"):
            f[f"emergency_name{n}"].label = "Name"
            f[f"emergency_phone{n}"].label = "Contact number"
            f[f"emergency_relation{n}"].label = "Relationship (e.g. Father, Spouse)"
            f[f"emergency_phone{n}"].widget.attrs["placeholder"] = "10 digit number"
            f[f"emergency_name{n}"].required = f[f"emergency_phone{n}"].required = f[f"emergency_relation{n}"].required = False
        for name in ("permanent_address", "current_address"):
            f[name].widget = forms.Textarea(attrs={"rows": 3})
            f[name].required = False
        # people type "1234 5678 9012" (14 characters); clean_aadhaar_number() strips the spaces before the model sees it
        f["aadhaar_number"] = forms.CharField(label="Aadhaar card number", max_length=14, required=False)
        f["aadhaar_number"].widget.attrs.update({"placeholder": "12 digit Aadhaar number", "inputmode": "numeric", "maxlength": 14})
        f["pan_number"].widget.attrs.update({"placeholder": "e.g. ABCDE1234F", "maxlength": 10, "style": "text-transform:uppercase"})
        f["vehicle_number"].widget.attrs.update({"placeholder": "e.g. TN 38 AB 1234", "style": "text-transform:uppercase"})
        for n in ("", "2", "3"):
            f[f"doctor_name{n}"].label = "Doctor name"
            f[f"doctor_phone{n}"].label = "Doctor contact number"
            f[f"doctor_phone{n}"].widget.attrs["placeholder"] = "10 digit number"
            f[f"doctor_location{n}"].label = "Location"
            f[f"doctor_location{n}"].widget.attrs["placeholder"] = "Hospital / clinic / place"
            f[f"doctor_name{n}"].required = f[f"doctor_phone{n}"].required = f[f"doctor_location{n}"].required = False
        f["medical_insurance_number"].widget.attrs["placeholder"] = "Policy / card number"
        for name in ("aadhaar_number", "pan_number", "vehicle_number", "medical_insurance_number"):
            f[name].required = False

    def clean_date_of_birth(self):
        d = self.cleaned_data.get("date_of_birth")
        if d and d >= timezone.localdate():
            raise forms.ValidationError("Date of birth must be in the past.")
        return d

    def clean_phone(self):
        return _clean_phone(self.cleaned_data.get("phone"), "Contact number")

    def clean_emergency_phone(self):
        return _clean_phone(self.cleaned_data.get("emergency_phone"), "Emergency contact number")

    def clean_emergency_phone2(self):
        return _clean_phone(self.cleaned_data.get("emergency_phone2"), "Emergency contact 2 number")

    def clean_doctor_phone(self):
        return _clean_phone(self.cleaned_data.get("doctor_phone"), "Doctor contact number")

    def clean_doctor_phone2(self):
        return _clean_phone(self.cleaned_data.get("doctor_phone2"), "Doctor 2 contact number")

    def clean_doctor_phone3(self):
        return _clean_phone(self.cleaned_data.get("doctor_phone3"), "Doctor 3 contact number")

    def clean_aadhaar_number(self):
        v = re.sub(r"[\s-]", "", (self.cleaned_data.get("aadhaar_number") or ""))
        if v and not (v.isdigit() and len(v) == 12):
            raise forms.ValidationError("Aadhaar number must be exactly 12 digits.")
        return v

    def clean_pan_number(self):
        v = (self.cleaned_data.get("pan_number") or "").strip().upper().replace(" ", "")
        if v and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", v):
            raise forms.ValidationError("PAN number looks like ABCDE1234F (5 letters, 4 digits, 1 letter).")
        return v

    def clean_medical_insurance_number(self):
        return re.sub(r"\s+", " ", (self.cleaned_data.get("medical_insurance_number") or "").strip())

    def clean_vehicle_number(self):
        return re.sub(r"\s+", " ", (self.cleaned_data.get("vehicle_number") or "").strip().upper())

    def _check_contacts(self, data):
        """An emergency contact needs at least a name and a number once any part of it is filled in."""
        for n, label in (("", "Emergency contact 1"), ("2", "Emergency contact 2")):
            parts = [data.get(f"emergency_name{n}"), data.get(f"emergency_phone{n}"), data.get(f"emergency_relation{n}")]
            if any(parts):
                if not data.get(f"emergency_name{n}"):
                    self.add_error(f"emergency_name{n}", f"{label}: enter the name.")
                if not data.get(f"emergency_phone{n}") and f"emergency_phone{n}" not in self.errors:
                    self.add_error(f"emergency_phone{n}", f"{label}: enter the contact number.")
        for n in ("", "2", "3"):
            if data.get(f"doctor_phone{n}") and not data.get(f"doctor_name{n}"):
                self.add_error(f"doctor_name{n}", "Enter the doctor's name too.")

    def show_contact2(self):
        """The second emergency contact is hidden behind the + button unless it already has something."""
        d = getattr(self, "cleaned_data", None) or {}
        if self.is_bound:
            return bool(any(self.data.get(k) for k in ("emergency_name2", "emergency_phone2", "emergency_relation2")))
        inst = self.instance
        return bool(inst and inst.pk and (inst.emergency_name2 or inst.emergency_phone2 or inst.emergency_relation2))


    def show_doctor(self, n):
        """Doctor 2 / 3 are hidden behind the + button unless they already have something (n = 2 or 3)."""
        keys = (f"doctor_name{n}", f"doctor_phone{n}", f"doctor_location{n}")
        if self.is_bound:
            return bool(any(self.data.get(k) for k in keys))
        inst = self.instance
        return bool(inst and inst.pk and any(getattr(inst, k) for k in keys))

    @property
    def show_doctor2(self):
        return self.show_doctor(2)

    @property
    def show_doctor3(self):
        return self.show_doctor(3)

    @property
    def can_add_doctor(self):
        return not (self.show_doctor(2) and self.show_doctor(3))


class EmployeeForm(PersonalDetailsMixin, BootstrapMixin, forms.ModelForm):
    """Add / edit an employee (Admin / HR / people with the Employees create / edit permission).

    Compulsory: employee code, name, contact number, mail id, blood group. Everything else is optional."""

    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150, label="Name")
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=True, label="Mail id")
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Required for a new employee. Leave blank on edit to keep the current password.",
    )
    joining_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))

    class Meta:
        model = Employee
        fields = [
            "employee_id", "department", "team", "designation", "joining_date", "status", "role",
            *PERSONAL_FIELDS, "display_priority", *PERM_FIELDS,
        ]

    def __init__(self, *args, can_set_role=True, **kwargs):
        super().__init__(*args, **kwargs)
        is_edit = bool(self.instance and self.instance.pk)
        self.fields["designation"].empty_label = "Select designation"
        self.fields["employee_id"].required = True
        self.fields["employee_id"].label = "Employee ID"
        self.fields["employee_id"].error_messages["required"] = "Enter the employee ID."
        self.fields["employee_id"].widget.attrs["placeholder"] = "e.g. EMP001"
        if not is_edit:
            self.fields["employee_id"].initial = next_employee_code()      # suggested - can be changed
        self.fields["first_name"].error_messages["required"] = "Enter the name."
        self.fields["email"].error_messages["required"] = "Enter the mail id."
        self.fields["email"].widget.attrs["placeholder"] = "name@company.com"
        self._setup_personal()
        self.fields["display_priority"].widget.attrs.update({"min": 1, "max": 100})
        self.fields["display_priority"].label = "List priority (1 - 100)"
        self.fields["display_priority"].required = False                  # left empty -> 50 (new) / unchanged (edit)
        if not is_edit:
            self.fields["display_priority"].initial = 50                  # normal people start in the middle
        if not can_set_role:  # only Admin / HR may hand out the Admin / HR role and the permissions
            self.fields["role"].choices = [c for c in Employee.ROLE_CHOICES if c[0] == Employee.ROLE_EMPLOYEE]
            for f in PERM_FIELDS:
                del self.fields[f]
        if is_edit:
            u = self.instance.user
            self.fields["username"].initial = u.username
            self.fields["first_name"].initial = u.first_name
            self.fields["last_name"].initial = u.last_name
            self.fields["email"].initial = u.email
        self.fields["team"].label_from_instance = lambda t: f"{t.name} ({t.department.name})"
        self.fields["team"].queryset = Team.objects.select_related("department")
        self._style()

    def has_permission_fields(self):
        return "can_view_employees" in self.fields

    def permission_rows(self):
        """Rows of the permission table in the form: (label, [bound checkboxes])."""
        def row(label, names):
            return label, [self[n] for n in names if n in self.fields]
        return [
            row("Employees", ["can_view_employees", "can_create_employees", "can_edit_employees"]),
            row("Projects", ["can_view_projects", "can_create_projects", "can_edit_projects"]),
        ]

    def other_permission_fields(self):
        return [self[n] for n in ("can_manage_leave", "can_manage_attendance", "can_manage_groups") if n in self.fields]

    def clean_display_priority(self):
        v = self.cleaned_data.get("display_priority")
        if v is None:
            return self.instance.display_priority if self.instance and self.instance.pk else 50
        return v

    def clean_employee_id(self):
        code = (self.cleaned_data.get("employee_id") or "").strip().upper()
        if not code and self.instance and self.instance.pk:
            return self.instance.employee_id  # never blank out an existing code
        if code and Employee.objects.filter(employee_id__iexact=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This employee ID is already used by another employee.")
        return code

    def clean_username(self):
        username = self.cleaned_data["username"]
        qs = User.objects.filter(username__iexact=username)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean(self):
        data = super().clean()
        if not (self.instance and self.instance.pk) and not data.get("password"):
            self.add_error("password", "Password is required for a new employee.")
        dept, team = data.get("department"), data.get("team")
        if dept and team and team.department_id != dept.pk:
            self.add_error("team", f"Team '{team.name}' belongs to {team.department.name}, not {dept.name}.")
        self._check_contacts(data)
        # Create / Edit include View: you cannot add or change what you cannot see
        for area in ("employees", "projects"):
            if (data.get(f"can_create_{area}") or data.get(f"can_edit_{area}")) and f"can_view_{area}" in self.fields:
                data[f"can_view_{area}"] = True
        return data

    def save(self, commit=True):
        emp = super().save(commit=False)
        d = self.cleaned_data
        for f in PERM_FIELDS:                       # the "View included" rule from clean()
            if f in d:
                setattr(emp, f, bool(d[f]))
        user = emp.user if emp.pk else User()
        user.username = d["username"]
        user.first_name = d["first_name"]
        user.last_name = d.get("last_name", "")
        user.email = d.get("email", "")
        user.is_active = d["status"] == Employee.STATUS_ACTIVE
        if d.get("password"):
            user.set_password(d["password"])
            emp.visible_password = d["password"]   # shown to Admin / HR and to the employee (requested)
        user.save()
        emp.user = user
        if commit:
            emp.save()
        return emp


class SelfProfileForm(PersonalDetailsMixin, BootstrapMixin, forms.ModelForm):
    """'Edit my details': an employee changes everything about himself except the employee code and the name
    (those, and the department / designation / permissions, are changed by HR)."""

    email = forms.EmailField(required=True, label="Mail id")

    class Meta:
        model = Employee
        fields = list(PERSONAL_FIELDS)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].error_messages["required"] = "Enter your mail id."
        self.fields["email"].initial = self.instance.user.email
        self._setup_personal()
        self._style()

    def clean(self):
        data = super().clean()
        self._check_contacts(data)
        return data

    def save(self, commit=True):
        emp = super().save(commit=False)
        emp.user.email = self.cleaned_data["email"]
        emp.user.save(update_fields=["email"])
        if commit:
            emp.save()
        return emp


WORD_LIMIT = 100


def _check_words(text, label, limit=WORD_LIMIT):
    """Keep long text short: at most `limit` words."""
    words = len((text or "").split())
    if words > limit:
        raise forms.ValidationError(f"{label}: {words} words - please keep it within {limit} words.")
    return text


class ProjectForm(BootstrapMixin, forms.ModelForm):
    """Step 1 - create / edit the project itself.

    Project title and Details of work are compulsory. Client, Project code, dates, status and completion are optional.
    Members are NOT asked here: after saving a new project the portal opens the "Assign members" page (step 2).
    """

    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))

    class Meta:
        model = Project
        fields = ["name", "client", "location", "client_location", "project_code", "description", "status", "completion", "start_date", "end_date"]
        labels = {"name": "Project title", "client": "Client", "project_code": "Project code",
                  "location": "Project location", "client_location": "Client location",
                  "description": "Details of work", "completion": "Completion % (optional)"}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4, "data-word-limit": WORD_LIMIT,
                                                 "placeholder": "What is the work? (max 100 words)"}),
            "completion": forms.NumberInput(attrs={"min": 0, "max": 100}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = True
        self.fields["description"].required = True
        self.fields["client"].required = False
        self.fields["project_code"].required = False
        self.fields["completion"].required = False          # optional: members report it daily
        self.fields["completion"].widget.attrs["placeholder"] = "Optional"
        self.fields["client"].widget.attrs["placeholder"] = "Optional"
        for k in ("location", "client_location"):
            self.fields[k].required = False
            self.fields[k].widget.attrs["placeholder"] = "Optional"
        self.fields["project_code"].widget.attrs["placeholder"] = "Optional"
        self.fields["name"].error_messages["required"] = "Enter the project title."
        self.fields["description"].error_messages["required"] = "Enter the details of work."
        self._style()

    def clean_description(self):
        return _check_words(self.cleaned_data.get("description", "").strip(), "Details of work")

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date cannot be before the start date.")
        status, pct = data.get("status"), data.get("completion")
        if pct is None:   # left empty -> keep what the project already has (0 for a new project)
            pct = data["completion"] = self.instance.completion if self.instance.pk else 0
        if pct == 100:
            data["status"] = Project.STATUS_COMPLETED
        elif status == Project.STATUS_COMPLETED:
            data["completion"] = 100
        return data


class ProjectMembersForm(BootstrapMixin, forms.Form):
    """Step 2 - assign members to an existing project: Office / Field (On shore / Off shore), work given and days."""

    employees = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.none(), required=False, widget=forms.CheckboxSelectMultiple,
        label="Members", help_text="Tick one or more employees and choose Office or Field work for each.",
    )

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        related = ("user", "designation", "department", "team")
        qs = services.staff_qs(Employee.objects.select_related(*related).filter(status=Employee.STATUS_ACTIVE))
        if project is not None and project.pk:  # keep already-assigned (even inactive) people visible
            qs = services.staff_qs(Employee.objects.select_related(*related).filter(
                models_q(status=Employee.STATUS_ACTIVE) | models_q(projects=project))).distinct()
        self.fields["employees"].queryset = qs
        self.fields["employees"].label_from_instance = lambda e: f"{e.employee_id} - {e.full_name}"
        current, current_work, current_days, current_ftype = {}, {}, {}, {}
        if project is not None and project.pk:
            for a in project.assignments.all():
                current[a.employee_id] = a.work_mode
                current_ftype[a.employee_id] = a.field_type
                current_work[a.employee_id] = a.work_description
                current_days[a.employee_id] = a.assigned_days
            self.initial["employees"] = list(current)
        self._members = list(qs)   # evaluated once; the form, the picker and clean() all reuse it
        for e in self._members:
            self.fields[f"mode_{e.pk}"] = forms.ChoiceField(
                required=False, label="Work type",
                choices=[("", "-- choose --")] + list(Attendance.MODE_CHOICES), initial=current.get(e.pk, ""),
                widget=forms.Select(attrs={"data-loc-mode": "1"}),
            )
            self.fields[f"ftype_{e.pk}"] = forms.ChoiceField(
                required=False, label="Field type",
                choices=[("", "-- On shore / Off shore --")] + list(Attendance.FIELD_TYPE_CHOICES),
                initial=current_ftype.get(e.pk, ""), widget=forms.Select(attrs={"data-loc-type": "1"}),
            )
            self.fields[f"work_{e.pk}"] = forms.CharField(
                required=False, label="Work assigned", initial=current_work.get(e.pk, ""),
                widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Work given (max 100 words)", "data-word-limit": WORD_LIMIT}),
            )
            self.fields[f"days_{e.pk}"] = forms.IntegerField(
                required=False, min_value=1, max_value=3650, label="No. of days", initial=current_days.get(e.pk),
                widget=forms.NumberInput(attrs={"placeholder": "Days", "min": 1}),
            )
        self._style()

    def members(self):
        """Rows for the member table: checkbox + Office/Field select for each employee."""
        boxes = {str(b.data["value"]): b for b in self["employees"]}
        for e in self._members:
            search = " ".join(filter(None, [
                e.employee_id, e.full_name, e.user.username,
                e.designation.name if e.designation else "", e.department.name if e.department else "",
                e.team.name if e.team else "",
            ]))
            yield {"employee": e, "checkbox": boxes.get(str(e.pk)), "mode": self[f"mode_{e.pk}"], "ftype": self[f"ftype_{e.pk}"], "search": search,
                   "work": self[f"work_{e.pk}"], "days": self[f"days_{e.pk}"]}

    def clean(self):
        data = super().clean()
        members = data.get("employees")
        if not members:
            self.add_error("employees", "Add at least one member to the project.")
        else:
            for e in members:
                if not data.get(f"mode_{e.pk}"):
                    self.add_error(f"mode_{e.pk}", f"{e.full_name}: choose Office work or Field work.")
                elif data.get(f"mode_{e.pk}") == Attendance.MODE_FIELD and not data.get(f"ftype_{e.pk}"):
                    self.add_error(f"ftype_{e.pk}", f"{e.full_name}: Field work - choose On shore or Off shore.")
                words = len((data.get(f"work_{e.pk}") or "").split())
                if words > WORD_LIMIT:
                    self.add_error(f"work_{e.pk}", f"{e.full_name}: work description is {words} words - keep it within {WORD_LIMIT}.")
        return data

    def save(self, was_new=False):
        project = self.project
        members = list(self.cleaned_data["employees"])
        modes = {e.pk: self.cleaned_data.get(f"mode_{e.pk}") for e in members}
        field_types = {e.pk: self.cleaned_data.get(f"ftype_{e.pk}") or "" for e in members}
        details = {e.pk: ((self.cleaned_data.get(f"work_{e.pk}") or "").strip(),
                          self.cleaned_data.get(f"days_{e.pk}") or None) for e in members}
        self.added = services.sync_assignments(project, members, modes, is_new=was_new, details=details,
                                               field_types=field_types)
        self.modes = modes
        self.field_types = field_types
        return project


class LeaveForm(BootstrapMixin, forms.ModelForm):
    start_date = forms.DateField(widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))
    end_date = forms.DateField(widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))

    class Meta:
        model = LeaveRequest
        fields = ["employee", "leave_type", "start_date", "end_date", "half_day", "reason", "approver"]

    def __init__(self, *args, employee=None, pick_employee=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.own_employee = employee
        if pick_employee:
            self.fields["employee"].queryset = services.staff_qs(
                Employee.objects.select_related("user").filter(status=Employee.STATUS_ACTIVE))
            self.fields["employee"].label_from_instance = lambda e: f"{e.employee_id} - {e.full_name}"
        else:
            del self.fields["employee"]
        if pick_employee:                       # HR records leave herself: nobody to ask
            del self.fields["approver"]
        else:                                   # the employee chooses who approves: people who have the leave permission
            qs = services.order_staff(Employee.objects.select_related("user", "designation").filter(
                status=Employee.STATUS_ACTIVE).filter(
                models_q(role__in=(Employee.ROLE_ADMIN, Employee.ROLE_HR)) | models_q(can_manage_leave=True)))
            if employee is not None:
                qs = qs.exclude(pk=employee.pk)
            self.fields["approver"].queryset = qs
            self.fields["approver"].required = qs.exists()
            self.fields["approver"].empty_label = "Select who approves your leave"
            self.fields["approver"].label = "Send leave request to"
            self.fields["approver"].label_from_instance = lambda e: (
                f"{e.full_name} - {e.designation.name}" if e.designation else e.full_name)
        self.fields["leave_type"].label_from_instance = lambda t: (
            f"{t.name} (unlimited - use after CL is over)" if t.is_lop else t.name)
        self._style()

    def clean(self):
        data = super().clean()
        emp = data.get("employee") if "employee" in self.fields else self.own_employee
        msg = services.validate_leave(
            emp, data.get("leave_type"), data.get("start_date"), data.get("end_date"),
            exclude_pk=self.instance.pk, half_day=bool(data.get("half_day")),
        )
        if msg:
            raise forms.ValidationError(msg)
        return data


class AttendanceForm(BootstrapMixin, forms.ModelForm):
    date = forms.DateField(widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))
    in_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    out_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    class Meta:
        model = Attendance
        fields = ["employee", "date", "in_time", "out_time", "work_mode", "field_type"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = services.staff_qs(Employee.objects.select_related("user"))
        self.fields["employee"].label_from_instance = lambda e: f"{e.employee_id} - {e.full_name}"
        self.fields["in_time"].label = "In Time"
        self.fields["out_time"].label = "Out Time"
        self.fields["work_mode"].label = "Location"
        self.fields["work_mode"].widget.attrs["data-loc-mode"] = "1"
        self.fields["field_type"].label = "Field type"
        self.fields["field_type"].choices = [("", "Select On shore / Off shore")] + list(Attendance.FIELD_TYPE_CHOICES)
        self.fields["field_type"].widget.attrs["data-loc-type"] = "1"
        self._style()

    def clean(self):
        data = super().clean()
        if data.get("in_time") and data.get("out_time") and data["out_time"] <= data["in_time"]:
            self.add_error("out_time", "Out time must be after in time.")
        if data.get("work_mode") == Attendance.MODE_FIELD:
            if not data.get("field_type"):
                self.add_error("field_type", "Field work: choose On shore or Off shore.")
        else:
            data["field_type"] = ""
        return data


class DesignationForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Designation
        fields = [
            "name", "description",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class LeaveTypeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ["name", "monthly_credit", "annual_credit", "is_lop"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


# ---------------- one login page for Admin / HR and employees ----------------
class PortalLoginForm(AuthenticationForm):
    """Everybody (Admin, HR, employees) signs in on the same page. What they see afterwards depends on their role."""


EmployeeLoginForm = AdminLoginForm = PortalLoginForm   # old names, kept so nothing else breaks


class DepartmentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "sort_order", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].error_messages["unique"] = "A department with this name already exists."
        self._style()


class TeamForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "department"]
        error_messages = {
            NON_FIELD_ERRORS: {"unique_together": "This team already exists in the selected department."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].empty_label = "Select department"
        self._style()


class HolidayForm(BootstrapMixin, forms.ModelForm):
    date = forms.DateField(widget=forms.DateInput(attrs={"data-date": "1", "autocomplete": "off"}, format="%Y-%m-%d"))

    class Meta:
        model = Holiday
        fields = ["date", "name", "kind"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].error_messages["unique"] = "A holiday is already added for this date."
        self._style()


PERM_LABELS = {
    "employees": "Employees, departments & teams", "projects": "Projects", "leave": "Leave approval",
    "attendance": "Attendance",
}


class PermissionTransferForm(BootstrapMixin, forms.Form):
    """HR on leave -> pick who looks after her permissions (and which ones) for the leave days."""

    to_employee = forms.ModelChoiceField(queryset=Employee.objects.none(), label="Transfer to")
    perms = forms.MultipleChoiceField(
        choices=[], widget=forms.CheckboxSelectMultiple, label="Permissions to hand over",
        help_text="Only what the person on leave can do herself is listed.",
    )

    def __init__(self, *args, leave=None, allowed=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.leave = leave
        from_employee = leave.employee if leave else None
        qs = Employee.objects.select_related("user", "designation").filter(status=Employee.STATUS_ACTIVE)
        if from_employee:
            qs = qs.exclude(pk=from_employee.pk)
        self.fields["to_employee"].queryset = services.staff_qs(qs)
        self.fields["to_employee"].label_from_instance = lambda e: (
            f"{e.employee_id} - {e.full_name}" + (f" ({e.designation.name})" if e.designation else ""))
        self.fields["perms"].choices = [(p, PERM_LABELS[p]) for p in allowed]
        self.fields["perms"].initial = list(allowed)
        self._style()

    def clean_to_employee(self):
        to = self.cleaned_data["to_employee"]
        if self.leave:
            clash = LeaveRequest.objects.filter(
                employee=to, status=LeaveRequest.STATUS_APPROVED,
                start_date__lte=self.leave.end_date, end_date__gte=self.leave.start_date).exists()
            if clash:
                raise forms.ValidationError(f"{to.full_name} is on leave in these days too. Choose somebody else.")
        return to


class GroupForm(BootstrapMixin, forms.ModelForm):
    """Create / edit a group: a name and any employees (tick one by one or add a whole department)."""

    members = forms.ModelMultipleChoiceField(queryset=Employee.objects.none(), required=False,
                                             widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Group
        fields = ["name", "members"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = services.staff_qs(Employee.objects.select_related("user", "designation", "department").filter(
            status=Employee.STATUS_ACTIVE))
        self._people = list(qs)
        self.fields["members"].queryset = qs
        self.fields["name"].widget.attrs["placeholder"] = "e.g. Survey field team"
        self._style()

    def people(self):
        boxes = {str(b.data["value"]): b for b in self["members"]}
        for e in self._people:
            yield {"employee": e, "checkbox": boxes.get(str(e.pk)),
                   "search": " ".join(filter(None, [e.full_name, e.employee_id, e.designation.name if e.designation else "",
                                                    e.department.name if e.department else ""]))}

    def clean_members(self):
        m = self.cleaned_data["members"]
        if not m:
            raise forms.ValidationError("Add at least one member to the group.")
        return m
