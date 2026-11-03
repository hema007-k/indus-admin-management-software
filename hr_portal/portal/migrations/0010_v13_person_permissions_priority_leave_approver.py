from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


def copy_permissions_and_priority(apps, schema_editor):
    """Existing designation permissions move to the people who hold that designation; priority starts from the old rank."""
    Employee = apps.get_model("portal", "Employee")
    for e in Employee.objects.select_related("designation"):
        d = e.designation
        if not d:
            continue
        e.can_manage_employees = d.can_manage_employees
        e.can_manage_projects = d.can_manage_projects
        e.can_manage_leave = d.can_manage_leave
        e.can_manage_attendance = d.can_manage_attendance
        e.can_manage_groups = d.can_manage_groups
        e.display_priority = 50 if d.rank == 50 else max(1, 100 - (d.rank - 1) * 5)
        e.save(update_fields=["can_manage_employees", "can_manage_projects", "can_manage_leave",
                              "can_manage_attendance", "can_manage_groups", "display_priority"])


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0009_v12_profile_photo'),
    ]

    operations = [
        migrations.AddField(model_name='employee', name='display_priority', field=models.PositiveSmallIntegerField(
            default=50, validators=[MinValueValidator(1), MaxValueValidator(100)], verbose_name='List priority',
            help_text='Order in the Employee table: 100 = shown first, 1 = shown last. Same number = A to Z by name.')),
        migrations.AddField(model_name='employee', name='can_manage_employees', field=models.BooleanField(
            default=False, help_text='Add / edit / delete employees, departments and teams')),
        migrations.AddField(model_name='employee', name='can_manage_projects', field=models.BooleanField(
            default=False, help_text='Add / edit projects and assign employees')),
        migrations.AddField(model_name='employee', name='can_manage_leave', field=models.BooleanField(
            default=False, help_text='Approve / reject leave (people choose who to send their leave request to)')),
        migrations.AddField(model_name='employee', name='can_manage_attendance', field=models.BooleanField(
            default=False, help_text='Add / edit attendance records')),
        migrations.AddField(model_name='employee', name='can_manage_groups', field=models.BooleanField(
            default=False, help_text='Create / edit / delete chat groups')),
        migrations.AddField(model_name='leaverequest', name='approver', field=models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='leave_to_approve',
            to='portal.employee', verbose_name='Send request to', help_text='The person who approves this leave')),
        migrations.RunPython(copy_permissions_and_priority, migrations.RunPython.noop),
    ]
