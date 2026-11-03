# v10 changes (final handover)

After unzipping run once (adds project Client / Project code, chat-group permission; data is kept):

    python manage.py migrate

1. Header (logo + company name + theme / logout) is frozen at the top; sidebar sits under it.
2. Attendance: Present = green, Absent = red blinking (profile table, dots, home).
3. "Days in field work" card shows On shore and Off shore counts separately (profile, home, yearly table, admin table).
4. Project details and each member's work description: max 100 words (live counter + server check); long text wraps to the next line.
5. Project create asks Project title*, Client, Project code, Details of work*. Only * are compulsory.
6. After creating a project the "Assign members" page opens automatically (also a button in list / detail).
7. "Today company holiday" bar on the Holidays page is hidden (kept inside a {% comment %} in holiday_list.html).
8. Notifications: message wraps inside a fixed width, tidy table, smaller font on phone.
9. Working days summary: new Leave and Today (Not in yet) columns. Working = Present + Leave + Absent + Today.
10. Chat: everybody can read / reply in their groups. Create / edit / delete groups needs Admin/HR or a designation with "Create chat groups".
11. One login page for everybody; /admin-login/ redirects to /login/.
