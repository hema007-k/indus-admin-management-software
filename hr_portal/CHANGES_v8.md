# v8 changes

After unzipping run once (this adds the new columns / tables, existing data is kept):

    python manage.py migrate

1. Home tile "Active employees" -> **Total employees**
2. "On leave today" -> **Absent today** (everybody not in on a working day)
3. Pending-leave tile + panel removed. **Leave** is now one row (Total / Approved / Waiting / Declined / Loss of Pay) with a filter: Today, Yesterday, This week, This month, This year
4. Tiles: Projects running + **Departments** (Team count removed)
5. "Attendance of everyone" block removed
6. Table title is **Employees today status**
7. Columns: **In Time / Out Time / Location** (also on attendance pages and forms)
8. **Groups** (sidebar, Admin / HR / Managing Director dept): every department is a group. One message goes to all members in the portal + WhatsApp. Computer -> WhatsApp Web, phone -> WhatsApp app. With WHATSAPP_MODE=cloud it is sent automatically.
9. Employee form: blood group + emergency contact (name, number, relationship). Admin sees every password (employee details -> Login -> Show). Each employee sees own password + emergency contact in **My Profile**.
10. No duplicate data: Employee details / My Profile has tabs (Profile, Attendance, Leave, Projects); Leave page shows leave only; Home shows only today + a small month summary; project page does not repeat the daily-update form.
11. **Transfer to** button on a leave row (Leave page). HR's permissions go to the chosen person only for the leave days (1 day leave = 1 day, 2 days = 2 days), then return automatically. The Super Admin is not listed as an employee and has no employee code on screen.
12. Projects show **work assigned to (description)** and **number of days** for every member.
13. Project completion % is optional.
14. Logo has no circle, heading is only "Indomer". Leave balance: green when no leave taken, red when leave taken. A person who is not in because of **Loss of Pay** leave shows a red blinking "Not in" (faster blink when the leave is more than 3 days).

# v8.1 (second round)
- **Leave in one place**: the "Employees today status" table (In Time / Out Time / Location / Status). Status shows Present, On leave (CL) or Not in. Everybody who did not come shows a red blinking **Not in**; Loss of Pay leave longer than 3 days blinks faster. Leave is no longer repeated on Home, employee details, attendance and project pages (the Leave page is the only other place).
- **Pagination everywhere** (Home table, Employees, Attendance, Leave, Projects, Notifications, Groups, group messages). A page only builds the rows you see; attendance summaries are calculated for the 15 people on the page only.
- **Faster pages**: edit / delete icons come from one icon sheet (not repeated in every row), HTML is about 5-8x smaller, the date picker is downloaded only on pages with a date box, link prefetching is off. Query counts stay flat (6-14 per page) however many employees there are - checked with 80 employees / 2000 attendance rows.
- **Groups**: "+ Create Group" - name + pick employees one by one or "+ Add whole department"; edit / delete; open a group to send the message (portal + WhatsApp). Old department messages from v8 are converted to groups by the migration.
- **Permissions**: "Transfer to" now lets you tick exactly which permissions are handed over (only ones HR really has), refuses a person who is on leave in the same days, follows the leave if its dates change and disappears if the leave is declined.

Run `python manage.py migrate` (adds 0004 and 0005).
