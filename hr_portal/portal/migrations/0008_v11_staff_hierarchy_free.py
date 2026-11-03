from django.db import migrations, models

from portal.hierarchy import department_sort_order, rank_for


def set_orders(apps, schema_editor):
    Designation = apps.get_model("portal", "Designation")
    Department = apps.get_model("portal", "Department")
    for d in Designation.objects.all():
        d.rank = rank_for(d.name)
        d.save(update_fields=["rank"])
    for d in Department.objects.all():
        d.sort_order = department_sort_order(d.name)
        d.save(update_fields=["sort_order"])


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0007_v10_project_client_code_groups_perm'),
    ]

    operations = [
        migrations.AddField(
            model_name='department',
            name='sort_order',
            field=models.PositiveSmallIntegerField(default=100, help_text='Order in the Employee table (small number first). Drivers / housekeeping groups go last.'),
        ),
        migrations.AddField(
            model_name='designation',
            name='rank',
            field=models.PositiveSmallIntegerField(default=50, help_text='Seniority in the Employee table: 1 = Managing Director, 2 = Director, 3 = Associate Director ... 1 to 3 are listed first (top management), then department by department'),
        ),
        migrations.AddField(
            model_name='employee',
            name='attendance_free',
            field=models.BooleanField(default=False, help_text='Free staff (e.g. Managing Director) have no in / out / absent - they are always shown as Present and are left out of the attendance tables', verbose_name='Free (no attendance)'),
        ),
        migrations.AlterModelOptions(name='department', options={'ordering': ['sort_order', 'name']}),
        migrations.AlterModelOptions(name='designation', options={'ordering': ['rank', 'name']}),
        migrations.RunPython(set_orders, migrations.RunPython.noop),
    ]
