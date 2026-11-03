# v16 changes

    python manage.py migrate        # 0013: project locations, extra doctors, biometric machines

1. **Project** form: new optional **Project location** and **Client location** (shown on the project page and list).
2. **Employee form -> Doctor**: a **+ Add doctor** button next to the Doctor heading adds Doctor 2, then Doctor 3
   (all optional, each has Remove). Shown on the employee profile.
3. **Biometric machines** (sidebar -> *Biometric*, Admin / HR only)
   * Add a machine (name, location, serial number) -> the page shows its URL and key.
   * Machine user ID = the person's **Employee ID** (EMP001). Just the number (1) also works.
   * First punch of the day = **In time**, last punch = **Out time**. A double scan within 2 minutes is ignored.
     Old punches that arrive late (machine sends its backlog) are placed correctly.
   * Way 1 - JSON push: `POST /api/biometric/punch/` with header `X-Device-Key: <key>`
     body `{"employee_id":"EMP001","timestamp":"2026-11-03 09:05:00"}` or `{"punches":[...]}`.
   * Way 2 - ZKTeco "cloud server / ADMS" push: machine menu -> Comm. -> Cloud Server = this PC's IP, port 8000;
     add the machine's serial number on the Biometric page. (`/iclock/cdata`, `/iclock/getrequest`)
   * Every punch is logged (also unknown IDs) on the Biometric page and in /django-admin/.
4. **"Code" -> "Employee ID"** everywhere on screen.
5. **Phone view**: theme / logout icons smaller; employee names stay on one line (table scrolls sideways instead).
6. Small fixes: *List priority* now defaults to 50 on Add Employee; Aadhaar typed as `1234 5678 9012` is accepted.
7. Tests: new `V16Tests`.
8. **Employee: Date of birth** (Basic details, shown on the profile).
9. **Emergency contacts** are one block now: "Phone number 1" and "Phone number 2" (both always visible, no + button).
10. **Doctor details** block: name, phone, **location** for each doctor (+ Add doctor for Doctor 2 / 3). Migration 0014.
11. **Medical insurance number** field (Address & ID section, optional). Migration 0015.
12. **Employee table grouped by department**: each department has a header with its average attendance % (this month); departments with the highest % come first, lowest last. Inside a department the highest % employee comes first.
