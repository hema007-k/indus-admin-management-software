"""Import / update the staff from the company "Staff list" Excel sheet.

    python manage.py import_staff "Staff list.xlsx"            # DRY RUN: only shows what would happen
    python manage.py import_staff "Staff list.xlsx" --apply    # really saves

* People already in the portal (matched by name) get their designation / department / team updated; their
  login, password and attendance are never touched.
* New people get an account (username = first name, password shown at the end) and the next employee code.
* Designation rank and department order are set from portal/hierarchy.py, so the Employee table lists
  Managing Director -> Directors -> Associate Directors first, then department by department
  (Drivers / Field Supervisors / House keeping last).
* Date of joining / DOB are NOT imported: in the sheet they are typed dd/mm but stored by Excel as mm/dd for some rows.
"""
import re
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from portal.hierarchy import department_sort_order, rank_for
from portal.models import Department, Designation, Employee, Team

User = get_user_model()

NOT_A_DEPARTMENT = {"other places", "senior staff and faes", "theni ( jp lab)"}
NOT_A_TEAM = {"senior staff and faes"}
TITLES = re.compile(r"^(mr|mrs|ms|miss)\.?\s+", re.I)


def clean_name(raw):
    name = re.sub(r"\([^)]*\)", "", str(raw or ""))          # (1.10.24) joining notes
    name = name.split("/")[0]                                   # "A / B" -> first person only
    name = TITLES.sub("", name.strip())
    return re.sub(r"\s+", " ", name).strip(" ,")


def tokens(name):
    """Name words without titles / initials:  'Dr. P. Chandramohan' -> {'chandramohan'}."""
    words = re.findall(r"[a-z]+", clean_name(name).lower())
    return frozenset(w for w in words if len(w) > 1 and w != "dr")


def find_existing(name, existing):
    """existing = {Employee: tokens}. Same words (any order, initials ignored) -> that person; otherwise one
    unambiguous person whose words contain / are contained in this name ('Dr. P. Chandramohan' ~ 'Ponnambalam Chandramohan')."""
    t = tokens(name)
    if not t:
        return None
    exact = [e for e, et in existing.items() if et == t]
    if len(exact) == 1:
        return exact[0]
    loose = [e for e, et in existing.items() if et and (t <= et or et <= t) and t & et]
    return loose[0] if len(loose) == 1 and not exact else None


def blood(raw):
    b = re.sub(r"[\s]", "", str(raw or "")).upper().replace("VE", "")
    return b if b in {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"} else ""


def phone(raw):
    return re.sub(r"\D", "", str(raw or ""))[-10:] if raw else ""


class Command(BaseCommand):
    help = "Import / update staff (designation, department, team, contacts) from the Staff list Excel sheet."

    def add_arguments(self, parser):
        parser.add_argument("xlsx")
        parser.add_argument("--apply", action="store_true", help="save the changes (default is a dry run)")

    def handle(self, *args, **opts):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("Install openpyxl first:  pip install openpyxl")
        ws = openpyxl.load_workbook(opts["xlsx"], data_only=True).active
        rows, section = [], ""
        for r in ws.iter_rows(min_row=2, values_only=True):
            r = list(r) + [None] * 15
            sl, name, desig, dept, _role, team = r[0], r[1], r[2], r[3], r[4], r[5]
            if isinstance(sl, str) and sl.strip() and not name:          # a section heading, e.g. "Seabed surveys"
                section = sl.strip()
                continue
            if not isinstance(sl, (int, float)) or not name or str(name).strip().lower() == "name":
                continue
            dept = (str(dept).strip() if dept else "")
            if not dept and section and section.lower() not in NOT_A_DEPARTMENT:
                dept = section
            dept = dept.split("/")[0].strip().replace("Modeling", "Modelling")
            team = str(team).strip() if team else ""
            if team.lower() in NOT_A_TEAM or team.lower() == dept.lower():
                team = ""
            rows.append(dict(name=clean_name(name), desig=str(desig).strip() if desig else "", dept=dept, team=team,
                             phone=phone(r[9]), email=str(r[10] or "").strip(), blood=blood(r[8]),
                             emg_name=str(r[12] or "").strip(), emg_phone=phone(r[13]), emg_rel=str(r[14] or "").strip(),
                             code=str(r[6]).strip() if r[6] else ""))

        existing = {e: tokens(e.full_name) for e in Employee.objects.select_related("user")}
        created, updated, creds = 0, 0, []
        apply = opts["apply"]
        with transaction.atomic():
            for d in rows:
                emp = find_existing(d["name"], existing)
                desig = dept = team = None
                if d["desig"]:
                    desig, _ = Designation.objects.get_or_create(name=d["desig"], defaults={"rank": rank_for(d["desig"])})
                    if desig.rank != rank_for(d["desig"]) and desig.rank == 50:
                        desig.rank = rank_for(d["desig"]); desig.save(update_fields=["rank"])
                if d["dept"]:
                    dept, _ = Department.objects.get_or_create(name=d["dept"], defaults={"sort_order": department_sort_order(d["dept"])})
                    if d["team"]:
                        team, _ = Team.objects.get_or_create(name=d["team"], department=dept)
                if emp:
                    for field, val in (("designation", desig), ("department", dept), ("team", team)):
                        if val is not None:
                            setattr(emp, field, val)
                    for field, val in (("phone", d["phone"]), ("blood_group", d["blood"]), ("emergency_name", d["emg_name"]),
                                       ("emergency_phone", d["emg_phone"]), ("emergency_relation", d["emg_rel"])):
                        if val and not getattr(emp, field):
                            setattr(emp, field, val)
                    emp.save()
                    updated += 1
                    self.stdout.write(f"  update  {emp.employee_id:8} {d['name']}  ->  {d['desig']} / {d['dept'] or '-'}")
                    continue
                base = re.sub(r"[^a-z0-9]", "", d["name"].split()[0].lower().replace("dr.", "")) or "staff"
                username, n = base, 1
                while User.objects.filter(username__iexact=username).exists():
                    n += 1
                    username = f"{base}{n}"
                password = secrets.token_urlsafe(6)
                first, _, last = d["name"].partition(" ")
                user = User.objects.create_user(username=username, password=password, first_name=first, last_name=last,
                                                email=d["email"])
                emp = Employee.objects.create(
                    user=user, designation=desig, department=dept, team=team, phone=d["phone"], blood_group=d["blood"],
                    emergency_name=d["emg_name"], emergency_phone=d["emg_phone"], emergency_relation=d["emg_rel"],
                    visible_password=password)
                existing[emp] = tokens(d["name"])
                created += 1
                creds.append((emp.employee_id, d["name"], username, password))
                self.stdout.write(f"  create  {emp.employee_id:8} {d['name']}  ->  {d['desig']} / {d['dept'] or '-'}")
            if not apply:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(
            f"{'APPLIED' if apply else 'DRY RUN (nothing saved - add --apply)'}: {created} to create, {updated} to update."))
        if apply and creds:
            self.stdout.write("\nNew logins (Admin can also see them on each employee's page):")
            for code, name, u, p in creds:
                self.stdout.write(f"  {code}  {name}: {u} / {p}")
