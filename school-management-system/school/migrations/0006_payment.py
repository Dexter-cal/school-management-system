from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ("school", "0005_apicredential"),
    ]

    operations = [
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("method", models.CharField(choices=[("cash", "Cash (Manual)"), ("mtn_momo", "MTN Mobile Money"), ("airtel_money", "Airtel Money"), ("bank", "Bank"), ("other", "Other")], default="cash", max_length=20)),
                ("reference", models.CharField(blank=True, max_length=80, null=True)),
                ("received_at", models.DateTimeField(default=timezone.now)),
                ("notes", models.TextField(blank=True, null=True)),
                ("status", models.CharField(choices=[("received", "Received"), ("reversed", "Reversed")], default="received", max_length=20)),
                ("received_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="received_payments", to="auth.user")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="school.student")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["received_at"], name="school_payme_received_c6b451_idx"),
                    models.Index(fields=["method"], name="school_payme_method_5f1241_idx"),
                    models.Index(fields=["status"], name="school_payme_status_0c0ae2_idx"),
                ],
            },
        ),
    ]

