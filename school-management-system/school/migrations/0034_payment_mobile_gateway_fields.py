from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('school', '0033_communicationcampaign_communicationdelivery_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='gateway_reference',
            field=models.CharField(blank=True, db_index=True, max_length=120, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='provider_name',
            field=models.CharField(blank=True, max_length=40, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='provider_payload',
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='provider_status',
            field=models.CharField(blank=True, max_length=40, null=True),
        ),
    ]
