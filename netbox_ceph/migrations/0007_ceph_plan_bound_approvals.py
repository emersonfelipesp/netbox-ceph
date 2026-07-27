"""Add fail-closed, plan-bound Ceph approval audit records."""

import django.core.validators
import django.db.models.deletion
import netbox.models.deletion
import taggit.managers
import utilities.json
from django.conf import settings
from django.db import migrations, models


def retire_legacy_confirmation_authority(apps, schema_editor):
    """Retire legacy authority without erasing its actor/time audit evidence."""

    CephOperation = apps.get_model("netbox_ceph", "CephOperation")
    CephPlan = apps.get_model("netbox_ceph", "CephPlan")

    CephPlan.objects.exclude(status="applied").update(status="stale")
    CephOperation.objects.filter(
        status__in=("planning", "planned", "awaiting_confirmation", "applying")
    ).update(status="pending", confirmed=False)

    operations = list(
        CephOperation.objects.exclude(requested_by=None).select_related("requested_by")
    )
    for operation in operations:
        operation.requested_by_username = str(operation.requested_by.username)
    if operations:
        CephOperation.objects.bulk_update(operations, ("requested_by_username",))

    plans = list(
        CephPlan.objects.exclude(operation__requested_by=None).select_related(
            "operation__requested_by"
        )
    )
    for plan in plans:
        plan.requester_id = plan.operation.requested_by_id
        plan.requester_username = str(plan.operation.requested_by.username)
    if plans:
        CephPlan.objects.bulk_update(plans, ("requester", "requester_username"))

    CephOperationRun = apps.get_model("netbox_ceph", "CephOperationRun")
    runs = list(CephOperationRun.objects.exclude(actor=None).select_related("actor"))
    for run in runs:
        run.actor_username = str(run.actor.username)
    if runs:
        CephOperationRun.objects.bulk_update(runs, ("actor_username",))


class Migration(migrations.Migration):
    dependencies = [
        ("extras", "0134_owner"),
        ("netbox_ceph", "0006_cephrbdimage_cephrbdsnapshot_cephrbdclone_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="cephoperation",
            options={
                "ordering": ("-created", "-pk"),
                "permissions": (
                    ("request_cephoperation", "Can request and plan Ceph operations"),
                    ("apply_cephoperation", "Can submit approved Ceph operations"),
                    ("approve_cephoperation", "Can independently approve Ceph operations"),
                ),
                "verbose_name": "Ceph operation",
                "verbose_name_plural": "Ceph operations",
            },
        ),
        migrations.AddField(
            model_name="cephoperation",
            name="requested_by_username",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="cephoperation",
            name="planning_reservation_id",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="cephoperation",
            name="planning_reservation_expires_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="cephoperation",
            name="execution_node",
            field=models.CharField(
                default="",
                help_text="Exact Proxmox node that will execute the planned mutation.",
                max_length=128,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "Enter an exact Proxmox node name (letters, numbers, '.', '_' and '-')."
                        ),
                        regex="^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="cephpooldesiredstate",
            name="execution_node",
            field=models.CharField(
                default="",
                help_text="Exact Proxmox node that will execute this desired mutation.",
                max_length=128,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "Enter an exact Proxmox node name (letters, numbers, '.', '_' and '-')."
                        ),
                        regex="^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="cephfilesystemdesiredstate",
            name="execution_node",
            field=models.CharField(
                default="",
                help_text="Exact Proxmox node that will execute this desired mutation.",
                max_length=128,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "Enter an exact Proxmox node name (letters, numbers, '.', '_' and '-')."
                        ),
                        regex="^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="cephfilesystemdesiredstate",
            name="pg_num",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cephfilesystemdesiredstate",
            name="add_storage",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="backend_endpoint_id",
            field=models.PositiveBigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="backend_endpoint_config_revision",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="plugin_endpoint_id",
            field=models.PositiveBigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="provider_id_snapshot",
            field=models.PositiveBigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="provider_kind_snapshot",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="execution_node",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="local_config_digest",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="backend_plan_digest",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="backend_plan_id",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="request_digest",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="requester",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="requested_ceph_plans",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="cephplan",
            name="requester_username",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AlterField(
            model_name="cephplan",
            name="operation",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="plans",
                to="netbox_ceph.cephoperation",
            ),
        ),
        migrations.CreateModel(
            name="CephOperationApproval",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("last_updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "custom_field_data",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        encoder=utilities.json.CustomFieldJSONEncoder,
                    ),
                ),
                ("backend_plan_id", models.CharField(db_index=True, max_length=64)),
                ("backend_plan_digest", models.CharField(max_length=64)),
                ("backend_endpoint_id", models.PositiveBigIntegerField(db_index=True)),
                ("backend_endpoint_config_revision", models.CharField(max_length=64)),
                ("plugin_endpoint_id", models.PositiveBigIntegerField(db_index=True)),
                ("provider_id_snapshot", models.PositiveBigIntegerField(db_index=True)),
                ("provider_kind_snapshot", models.CharField(max_length=32)),
                ("execution_node", models.CharField(max_length=128)),
                ("local_config_digest", models.CharField(max_length=64)),
                (
                    "backend_approval_id",
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                (
                    "issuance_reservation_id",
                    models.UUIDField(blank=True, editable=False, null=True, unique=True),
                ),
                (
                    "issuance_reservation_expires_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(default="issued", max_length=32)),
                (
                    "backend_run_id",
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                ("failure_code", models.CharField(blank=True, max_length=128)),
                ("failure_detail", models.TextField(blank=True)),
                ("requester_username", models.CharField(blank=True, max_length=150)),
                ("approver_username", models.CharField(blank=True, max_length=150)),
                (
                    "approver",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_ceph_operations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "operation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approvals",
                        to="netbox_ceph.cephoperation",
                    ),
                ),
                (
                    "plan",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval",
                        to="netbox_ceph.cephplan",
                    ),
                ),
                (
                    "requester",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_ceph_approvals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tags",
                    taggit.managers.TaggableManager(
                        through="extras.TaggedItem",
                        to="extras.Tag",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ceph operation approval",
                "verbose_name_plural": "Ceph operation approvals",
                "ordering": ("-created", "-pk"),
            },
            bases=(netbox.models.deletion.DeleteMixin, models.Model),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="approval",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="run",
                to="netbox_ceph.cephoperationapproval",
            ),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="actor_username",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="backend_run_id",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="backend_endpoint_config_revision",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="plugin_endpoint_id",
            field=models.PositiveBigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="provider_id_snapshot",
            field=models.PositiveBigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="provider_kind_snapshot",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="execution_node",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="local_config_digest",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="cephoperationrun",
            name="outcome_unknown",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="cephoperationrun",
            name="operation",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="runs",
                to="netbox_ceph.cephoperation",
            ),
        ),
        migrations.AlterField(
            model_name="cephoperationrun",
            name="plan",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="runs",
                to="netbox_ceph.cephplan",
            ),
        ),
        migrations.RunPython(
            retire_legacy_confirmation_authority,
            migrations.RunPython.noop,
        ),
    ]
