# v14 changes

    python manage.py migrate        # 0011: personal details, View / Create / Edit permissions, "Free" removed

1. **Add / Edit Employee form (new layout)**
   * Compulsory (red star): **Employee code, Name, Contact number, Mail id, Blood group**. Everything else is optional.
   * The employee code is filled in with the next free code (EMP00x) - you can change it.
   * **Emergency contact 1** (name, relationship, number) + a **"+ Add emergency contact 2"** button that opens a second
     contact (same fields). Contact 2 can be removed again.
   * New optional fields: Permanent address, Current address, Aadhaar number (12 digits), PAN number (ABCDE1234F),
     Vehicle number, Doctor name, Doctor contact number.
   * Phone numbers are checked (10 to 13 digits); Aadhaar / PAN formats are checked.
2. **Everybody edits their own details:** My Profile -> "Edit my details". Everything can be changed except the
   **employee code and the name** (and department / designation / role / permissions, which stay with HR).
   Aadhaar and PAN are shown in full only to the person himself and Admin / HR; others with View see them hidden.
3. **"Free" option removed** everywhere (form, tables, dashboards, attendance). Everybody clocks in / out.
4. **Permissions are View / Create / Edit, separately for Employees and for Projects.**
   They are ticked in the permission table while creating / editing the employee (only Admin / HR can tick them).
   * Employees: View = employee list + other people's profiles; Create = Add Employee; Edit = edit / delete employees,
     departments and teams.
   * Projects: View = see **all** projects (without it a person sees only the projects assigned to him);
     Create = create a project and give a **new** project its first members; Edit = edit / delete a project and change members.
   * Create or Edit always includes View. Buttons and menus show only what the person is allowed to do.
   * Old "manage employees / manage projects" people were moved to View + Create + Edit automatically.
   * Leave-cover (permission transfer) only hands over what the person on leave really has.
5. **Working days in the month:** the attendance tiles (Home and Profile -> Attendance) now start with
   **"Working days in October 2026"** = all working days of the whole month (Sundays, 2nd Saturdays and holidays left out).
   The old tile is now "Working days till today", so Working = Present + Leave + Absent + Today still adds up.
