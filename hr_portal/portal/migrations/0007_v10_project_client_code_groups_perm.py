from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0006_field_type_onshore_offshore'),
    ]

    operations = [
        migrations.AddField(
            model_name='designation',
            name='can_manage_groups',
            field=models.BooleanField(default=False, help_text='Create / edit / delete chat groups (everybody can still read and reply in their groups)'),
        ),
        migrations.AddField(
            model_name='project',
            name='client',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name='project',
            name='project_code',
            field=models.CharField(blank=True, max_length=50, verbose_name='Project code'),
        ),
        migrations.AlterField(
            model_name='project',
            name='name',
            field=models.CharField(max_length=150, verbose_name='Project title'),
        ),
        migrations.AlterField(
            model_name='project',
            name='description',
            field=models.TextField(blank=True, verbose_name='Details of work'),
        ),
        migrations.AlterField(
            model_name='projectassignment',
            name='work_description',
            field=models.TextField(blank=True, verbose_name='Work assigned'),
        ),
    ]
