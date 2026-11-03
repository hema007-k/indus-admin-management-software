# v11 changes

After unzipping run once (keeps all data):

    python manage.py migrate
    python manage.py collectstatic --noinput      # only if you run with DJANGO_DEBUG=0
    (browser: Ctrl+F5 once)

1. **Header frozen** - the company header (logo + name + theme / logout) now uses fixed positioning, so it stays on top
   on every page and screen size; page content starts just below it.
2. "Projects running" / "No project running" wording -> **Current projects / No current project**.
3. **Employee table order** (from the Staff list):
   Managing Director -> Directors -> Associate Directors / FAEs (top management, shown under "Management"),
   then department by department (senior designation first), Drivers / Field Supervisors / House keeping last.
   Designation has a new **Rank** (1 = Managing Director, 2 = Director, 3 = Associate Director ...) and Department a
   **Sort order**; both are editable in Organization. Existing designations / departments are ranked automatically by name.
   Directors need no department.
4. **Free** option on the employee form (Admin / HR): Free staff have no in / out / absent. They show
   "Present - Free" everywhere, are left out of the attendance tables and cannot clock in.
5. `python manage.py import_staff "Staff list.xlsx"` - dry run first, add `--apply` to save. Matches people already in the
   portal by name (login / password / attendance untouched), creates the rest with the next employee code.
   Date of joining / DOB are NOT imported (several dates in the sheet are month / day swapped).
