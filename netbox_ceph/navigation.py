"""NetBox plugin navigation menu for netbox-ceph."""

from __future__ import annotations

from netbox.plugins import PluginMenu, PluginMenuButton, PluginMenuItem

_buttons = {
    "settings": [
        PluginMenuButton(
            link="plugins:netbox_ceph:cephpluginsettings_singleton_edit",
            title="Edit settings",
            icon_class="mdi mdi-cog",
        ),
    ],
    "provider": [
        PluginMenuButton(
            link="plugins:netbox_ceph:cephprovider_add",
            title="Add provider",
            icon_class="mdi mdi-plus-thick",
        ),
    ],
    "operation": [
        PluginMenuButton(
            link="plugins:netbox_ceph:cephoperation_add",
            title="Add operation",
            icon_class="mdi mdi-plus-thick",
        ),
    ],
    "pool_desired": [
        PluginMenuButton(
            link="plugins:netbox_ceph:cephpooldesiredstate_add",
            title="Add desired pool",
            icon_class="mdi mdi-plus-thick",
        ),
    ],
    "filesystem_desired": [
        PluginMenuButton(
            link="plugins:netbox_ceph:cephfilesystemdesiredstate_add",
            title="Add desired filesystem",
            icon_class="mdi mdi-plus-thick",
        ),
    ],
}


_inventory_items = (
    PluginMenuItem(
        link="plugins:netbox_ceph:cephcluster_list",
        link_text="Clusters",
        permissions=["netbox_ceph.view_cephcluster"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephdaemon_list",
        link_text="Daemons",
        permissions=["netbox_ceph.view_cephdaemon"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephosd_list",
        link_text="OSDs",
        permissions=["netbox_ceph.view_cephosd"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephpool_list",
        link_text="Pools",
        permissions=["netbox_ceph.view_cephpool"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephfilesystem_list",
        link_text="Filesystems",
        permissions=["netbox_ceph.view_cephfilesystem"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephcrushrule_list",
        link_text="CRUSH Rules",
        permissions=["netbox_ceph.view_cephcrushrule"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephflag_list",
        link_text="Flags",
        permissions=["netbox_ceph.view_cephflag"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephhealthcheck_list",
        link_text="Health Checks",
        permissions=["netbox_ceph.view_cephhealthcheck"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephpluginsettings_singleton_edit",
        link_text="Plugin Settings",
        permissions=["netbox_ceph.change_cephpluginsettings"],
        buttons=_buttons["settings"],
    ),
)

_v2_items = (
    PluginMenuItem(
        link="plugins:netbox_ceph:ceph_v2_dashboard",
        link_text="Dashboard",
        permissions=["netbox_ceph.view_cephcluster"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephprovider_list",
        link_text="Providers",
        permissions=["netbox_ceph.view_cephprovider"],
        buttons=_buttons["provider"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephoperation_list",
        link_text="Operations",
        permissions=["netbox_ceph.view_cephoperation"],
        buttons=_buttons["operation"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephplan_list",
        link_text="Plans",
        permissions=["netbox_ceph.view_cephplan"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephvalidationresult_list",
        link_text="Validation Results",
        permissions=["netbox_ceph.view_cephvalidationresult"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephoperationrun_list",
        link_text="Operation Runs",
        permissions=["netbox_ceph.view_cephoperationrun"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephdriftrecord_list",
        link_text="Drift Records",
        permissions=["netbox_ceph.view_cephdriftrecord"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephmetricsnapshot_list",
        link_text="Metric Snapshots",
        permissions=["netbox_ceph.view_cephmetricsnapshot"],
    ),
)


_desired_state_items = (
    PluginMenuItem(
        link="plugins:netbox_ceph:cephpooldesiredstate_list",
        link_text="Pools",
        permissions=["netbox_ceph.view_cephpooldesiredstate"],
        buttons=_buttons["pool_desired"],
    ),
    PluginMenuItem(
        link="plugins:netbox_ceph:cephfilesystemdesiredstate_list",
        link_text="Filesystems",
        permissions=["netbox_ceph.view_cephfilesystemdesiredstate"],
        buttons=_buttons["filesystem_desired"],
    ),
)


menu = PluginMenu(
    label="Ceph",
    groups=(
        ("Inventory", _inventory_items),
        ("Ceph v2", _v2_items),
        ("Desired State", _desired_state_items),
    ),
    icon_class="mdi mdi-database-clock",
)
