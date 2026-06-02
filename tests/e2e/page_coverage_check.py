"""Visit every netbox-ceph plugin page and assert HTTP 200 with no Django 500 body.

Usage:
    NETBOX_BASE_URL=http://127.0.0.1:18080 \
    NETBOX_API_TOKEN=<admin-token> \
    python tests/e2e/page_coverage_check.py

Exit 0 = all pages OK, Exit 1 = one or more failures.
"""

from __future__ import annotations

import os
import sys

import requests

_NETBOX_BASE_URL = os.environ.get("NETBOX_BASE_URL", "http://127.0.0.1:18080").rstrip("/")
_NETBOX_API_TOKEN = os.environ.get("NETBOX_API_TOKEN", "")

LIST_PAGES: list[tuple[str, str]] = [
    ("home", "/plugins/ceph/"),
    ("ceph-v2-dashboard", "/plugins/ceph/v2/"),
    ("sitemap", "/plugins/ceph/sitemap.txt"),
    ("clusters-list", "/plugins/ceph/clusters/"),
    ("daemons-list", "/plugins/ceph/daemons/"),
    ("osds-list", "/plugins/ceph/osds/"),
    ("pools-list", "/plugins/ceph/pools/"),
    ("filesystems-list", "/plugins/ceph/filesystems/"),
    ("crush-rules-list", "/plugins/ceph/crush-rules/"),
    ("flags-list", "/plugins/ceph/flags/"),
    ("health-checks-list", "/plugins/ceph/health-checks/"),
    ("providers-list", "/plugins/ceph/providers/"),
    ("operations-list", "/plugins/ceph/operations/"),
    ("plans-list", "/plugins/ceph/plans/"),
    ("validation-results-list", "/plugins/ceph/validation-results/"),
    ("operation-runs-list", "/plugins/ceph/operation-runs/"),
    ("drift-records-list", "/plugins/ceph/drift-records/"),
    ("metric-snapshots-list", "/plugins/ceph/metric-snapshots/"),
    ("pool-desired-states-list", "/plugins/ceph/pool-desired-states/"),
    ("filesystem-desired-states-list", "/plugins/ceph/filesystem-desired-states/"),
    ("rbd-image-desired-states-list", "/plugins/ceph/rbd-image-desired-states/"),
    ("rbd-snapshot-desired-states-list", "/plugins/ceph/rbd-snapshot-desired-states/"),
    ("rgw-realm-desired-states-list", "/plugins/ceph/rgw-realm-desired-states/"),
    ("rgw-zone-desired-states-list", "/plugins/ceph/rgw-zone-desired-states/"),
    ("rgw-user-desired-states-list", "/plugins/ceph/rgw-user-desired-states/"),
    ("rgw-bucket-desired-states-list", "/plugins/ceph/rgw-bucket-desired-states/"),
]


def login_session(base_url: str) -> requests.Session:
    session = requests.Session()
    session.get(f"{base_url}/login/", timeout=30)
    csrf = session.cookies.get("csrftoken")
    if not csrf:
        raise RuntimeError(f"Login page did not set csrftoken at {base_url}/login/")
    resp = session.post(
        f"{base_url}/login/",
        data={
            "username": "admin",
            "password": "admin",
            "csrfmiddlewaretoken": csrf,
            "next": "/",
        },
        headers={"Referer": f"{base_url}/login/"},
        allow_redirects=False,
        timeout=30,
    )
    if resp.status_code != 302:
        raise RuntimeError(
            f"Session login failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )
    return session


def check_page(
    session: requests.Session,
    url: str,
    label: str,
    failures: list[str],
) -> None:
    try:
        resp = session.get(url, allow_redirects=True, timeout=30)
    except requests.RequestException as exc:
        failures.append(f"{label}: connection error — {exc}")
        print(f"  FAIL  {label}: {exc}")
        return

    if not (200 <= resp.status_code < 400):
        failures.append(f"{label}: HTTP {resp.status_code}")
        print(f"  FAIL  {label}: HTTP {resp.status_code}  ({url})")
        return

    body = resp.text
    if "Internal Server Error" in body or "Traceback (most recent call last)" in body:
        failures.append(f"{label}: Django 500 body detected")
        print(f"  FAIL  {label}: Django 500 content in HTTP {resp.status_code} response  ({url})")
        return

    print(f"  OK    {label}  HTTP {resp.status_code}")


def main() -> None:
    if not _NETBOX_API_TOKEN:
        print("ERROR: NETBOX_API_TOKEN environment variable is required")
        sys.exit(1)

    print(f"Page coverage check against {_NETBOX_BASE_URL}")
    print(f"  {len(LIST_PAGES)} pages")
    print()

    session = login_session(_NETBOX_BASE_URL)
    failures: list[str] = []

    print("── Pages ─────────────────────────────────────────────────────────────")
    for label, path in LIST_PAGES:
        url = f"{_NETBOX_BASE_URL}{path}"
        check_page(session, url, label, failures)

    print()
    if failures:
        print(f"── FAILED: {len(failures)} page(s) ──────────────────────────────")
        for msg in failures:
            print(f"  • {msg}")
        sys.exit(1)
    else:
        print(f"── All {len(LIST_PAGES)} pages passed ✓")


if __name__ == "__main__":
    main()
