from django.db import migrations, models


def spread_permissions(apps, schema_editor):
    """Old 'manage' permission = everything, so those people keep View + Create + Edit."""
    Employee = apps.get_model("portal", "Employee")
    Employee.objects.filter(can_edit_employees=True).update(can_view_employees=True, can_create_employees=True)
    Employee.objects.filter(can_edit_projects=True).update(can_view_projects=True, can_create_projects=True)


def copy_free_back(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0010_v13_person_permissions_priority_leave_approver'),
    ]

    operations = [
        # permissions: View / Create / Edit for Employees and for Projects
        migrations.RenameField(model_name='employee', old_name='can_manage_employees', new_name='can_edit_employees'),
        migrations.RenameField(model_name='employee', old_name='can_manage_projects', new_name='can_edit_projects'),
        migrations.AlterField(model_name='employee', name='can_edit_employees', field=models.BooleanField(
            default=False, help_text='Edit / delete employees, departments and teams')),
        migrations.AlterField(model_name='employee', name='can_edit_projects', field=models.BooleanField(
            default=False, help_text='Edit / delete projects and change their members')),
        migrations.AddField(model_name='employee', name='can_view_employees', field=models.BooleanField(
            default=False, help_text="See the employee list and other people's profiles")),
        migrations.AddField(model_name='employee', name='can_create_employees', field=models.BooleanField(
            default=False, help_text='Add new employees')),
        migrations.AddField(model_name='employee', name='can_view_projects', field=models.BooleanField(
            default=False, help_text='See ALL projects (otherwise only the projects the person is assigned to)')),
        migrations.AddField(model_name='employee', name='can_create_projects', field=models.BooleanField(
            default=False, help_text='Create new projects and give them their first members')),
        # the "Free" option is removed
        migrations.RemoveField(model_name='employee', name='attendance_free'),
        # new personal details
        migrations.AlterField(model_name='employee', name='phone', field=models.CharField(
            blank=True, max_length=20, verbose_name='Contact number')),
        migrations.AddField(model_name='employee', name='emergency_name2', field=models.CharField(
            blank=True, max_length=100, verbose_name='Emergency contact 2 - name')),
        migrations.AddField(model_name='employee', name='emergency_phone2', field=models.CharField(
            blank=True, max_length=20, verbose_name='Emergency contact 2 - number')),
        migrations.AddField(model_name='employee', name='emergency_relation2', field=models.CharField(
            blank=True, max_length=50, verbose_name='Emergency contact 2 - relationship')),
        migrations.AddField(model_name='employee', name='permanent_address', field=models.TextField(
            blank=True, verbose_name='Permanent address')),
        migrations.AddField(model_name='employee', name='current_address', field=models.TextField(
            blank=True, verbose_name='Current address')),
        migrations.AddField(model_name='employee', name='aadhaar_number', field=models.CharField(
            blank=True, max_length=12, verbose_name='Aadhaar card number')),
        migrations.AddField(model_name='employee', name='pan_number', field=models.CharField(
            blank=True, max_length=10, verbose_name='PAN card number')),
        migrations.AddField(model_name='employee', name='vehicle_number', field=models.CharField(
            blank=True, max_length=20, verbose_name='Vehicle number')),
        migrations.AddField(model_name='employee', name='doctor_name', field=models.CharField(
            blank=True, max_length=100, verbose_name='Doctor name')),
        migrations.AddField(model_name='employee', name='doctor_phone', field=models.CharField(
            blank=True, max_length=20, verbose_name='Doctor contact number')),
        migrations.RunPython(spread_permissions, copy_free_back),
    ]
