# v13 changes

    python manage.py migrate        # 0010: person permissions, list priority, leave "send to"

1. **Employee table order = List priority per person.** Employee form has "List priority (1-100)":
   100 = shown first, 1 = shown last; people with the same number come one by one in A-Z order.
   (Existing people start from their old designation rank: MD 100, Director 95 ... ; new people 50.)
   The department headings in the table were removed.
2. **Delete several employees at once:** tick the boxes (or the top box = all), press "Delete selected (n)", confirm once.
   Your own account and Admin/HR accounts you may not touch are never deleted.
3. **Permissions are now per person, not per designation.** The Employee add / edit form has tick boxes:
   Manage employees, Manage projects, Approve leave, Manage attendance, Create chat groups (only Admin / HR can tick them).
   Designation no longer carries permissions. On migrate, people who held a designation with permissions keep them.
4. **Leave:** when an employee applies, the form lists everybody who has the Approve-leave permission (plus Admin / HR);
   the employee chooses one. Only that person gets the notification and sees the request (Admin / HR see all).
   When the request is approved or declined the applicant gets a notification either way.
   Free people (e.g. MD) can be chosen too - they only need the Approve-leave permission.
