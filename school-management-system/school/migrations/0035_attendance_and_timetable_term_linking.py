from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('school', '0034_payment_mobile_gateway_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='attendance',
            name='academic_year',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='attendance',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='attendance',
            name='term_number',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='timetable',
            name='academic_year',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='timetable',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='timetable',
            name='term_number',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterUniqueTogether(
            name='timetable',
            unique_together={('school_class', 'section', 'academic_year', 'term_number')},
        ),
        migrations.AddIndex(
            model_name='timetable',
            index=models.Index(fields=['academic_year', 'term_number', 'is_active'], name='school_timet_academi_4e93b0_idx'),
        ),
    ]
