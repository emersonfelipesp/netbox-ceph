"""API URL routes for the netbox-ceph plugin."""

from __future__ import annotations

from netbox.api.routers import NetBoxRouter

from netbox_ceph.api import views

app_name = "netbox_ceph-api"

router = NetBoxRouter()
router.register("settings", views.CephPluginSettingsViewSet)
router.register("clusters", views.CephClusterViewSet)
router.register("daemons", views.CephDaemonViewSet)
router.register("osds", views.CephOSDViewSet)
router.register("pools", views.CephPoolViewSet)
router.register("filesystems", views.CephFilesystemViewSet)
router.register("crush-rules", views.CephCrushRuleViewSet)
router.register("flags", views.CephFlagViewSet)
router.register("health-checks", views.CephHealthCheckViewSet)
router.register("rgw-realms", views.CephRGWRealmViewSet)
router.register("rgw-zone-groups", views.CephRGWZoneGroupViewSet)
router.register("rgw-zones", views.CephRGWZoneViewSet)
router.register("rgw-placement-targets", views.CephRGWPlacementTargetViewSet)
router.register("rgw-users", views.CephRGWUserReflectedViewSet)
router.register("rgw-buckets", views.CephRGWBucketReflectedViewSet)
router.register("rbd-images", views.CephRBDImageViewSet)
router.register("rbd-snapshots", views.CephRBDSnapshotViewSet)
router.register("rbd-clones", views.CephRBDCloneViewSet)
router.register("providers", views.CephProviderViewSet)
router.register("operations", views.CephOperationViewSet)
router.register("plans", views.CephPlanViewSet)
router.register("validation-results", views.CephValidationResultViewSet)
router.register("operation-runs", views.CephOperationRunViewSet)
router.register("drift-records", views.CephDriftRecordViewSet)
router.register("metric-snapshots", views.CephMetricSnapshotViewSet)
router.register("pool-desired-states", views.CephPoolDesiredStateViewSet)
router.register("filesystem-desired-states", views.CephFilesystemDesiredStateViewSet)
router.register("rbd-image-desired-states", views.CephRBDImageDesiredStateViewSet)
router.register("rbd-snapshot-desired-states", views.CephRBDSnapshotDesiredStateViewSet)
router.register("rgw-realm-desired-states", views.CephRGWRealmDesiredStateViewSet)
router.register("rgw-zone-desired-states", views.CephRGWZoneDesiredStateViewSet)
router.register("rgw-user-desired-states", views.CephRGWUserDesiredStateViewSet)
router.register("rgw-bucket-desired-states", views.CephRGWBucketDesiredStateViewSet)

urlpatterns = router.urls
