from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0008_v11_staff_hierarchy_free'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='photo_updated',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.CreateModel(
            name='EmployeePhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('data', models.BinaryField()),
                ('content_type', models.CharField(default='image/jpeg', max_length=20)),
                ('employee', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='photo', to='portal.employee')),
            ],
        ),
    ]
