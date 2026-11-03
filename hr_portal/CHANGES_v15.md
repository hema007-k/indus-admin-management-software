# v15 changes

    python manage.py migrate        # 0012: the old permission tick-boxes are removed from Designation

1. **New "Permissions" page (Admin / HR only)** - sidebar -> *Permissions* (`/permissions/`).
   One table, one row per person, one tick box per permission:
   * Employees: View / Create / Edit
   * Projects: View / Create / Edit
   * Approve leave, Attendance, Chat groups
   Header tick box = whole column, row buttons *All* / *None*, live search, one **Save permissions** button.
   Create or Edit automatically ticks View (also un-ticking View clears Create / Edit).
   Super Admin and HR rows are locked: they always have everything.
2. **Permissions belong to the person, never to the designation.** The five leftover `can_manage_*` flags were
   removed from the Designation model (migration 0012). A designation is only a job title.
   (The Employee add / edit form still has the same permission table; both places change the same data.)
3. **Bug fix - Super Admin login had no View / Create / Edit permissions.** The `admin` superuser only received the
   four old areas, so Employee list, Add Employee, Org Setup etc. showed "Access denied". Admin now holds every permission.
4. **Bug fix - Employee page crashed** (`services.group_label` no longer exists but `employee_list` still called it).
5. `seed_demo` gives the demo permissions to the *person* (hr = everything, arun = projects) instead of to designations.
6. Tests: new `PermissionsPageTests` (page access, saving, View-included rule, Admin / HR can open every manager page).
