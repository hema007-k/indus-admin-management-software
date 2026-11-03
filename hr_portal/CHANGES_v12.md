# v12 changes

    pip install -r requirements.txt
    python manage.py migrate        # adds the profile-photo table (0009)

* **Profile photo** - on My Profile (and Admin / HR on any employee's page) tap **Add photo / Change / Remove**.
  The picture is cropped to a square and shrunk to 256 x 256 in the browser, then stored in the database
  (works with SQLite and Neon, no media folder needed). It shows in the sidebar, profile, home, Employee table,
  group members. Employees can change only their own photo; JPG / PNG / WEBP.
