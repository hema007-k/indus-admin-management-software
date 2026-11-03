# v9 changes

After unzipping run once (adds the On shore / Off shore column, data is kept):

    python manage.py migrate

1. Admin home: the "Today company holiday" card is removed.
2. Every table scrolls after 6 rows (header stays on top) and has a search box.
3. Ajax: search, paging and filters refresh only the table area - no page reload. Ajax requests send only the page content (no header/sidebar).
4. Design: icons in the menu, dashboard tiles and buttons; Dark/Light theme and Logout are icon buttons in the header (also on phone); phone view has a bottom icon menu.
5. Groups are now **Chat**: chat-bubble screen, send box with Send icon, "Open chat" instead of WhatsApp labels.
6. Field work: choose Location = Field and the next box asks On shore / Off shore (clock-in, Add/Edit Attendance, Project members). Shown as "Field (On shore)" / "Field (Off shore)" everywhere.
