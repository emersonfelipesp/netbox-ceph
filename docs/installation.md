# Installation

## Requirements

- NetBox 4.5.x – 4.6.x
- Python 3.12+
- [`netbox-proxbox`](https://github.com/emersonfelipesp/netbox-proxbox) `>=0.0.16`
- A reachable [`proxbox-api`](https://github.com/emersonfelipesp/proxbox-api)
  instance exposing Ceph-aware endpoints

## Install

```bash
pip install netbox-ceph
```

In `configuration.py`:

```python
PLUGINS = [
    "netbox_proxbox",
    "netbox_ceph",
]
```

```bash
python manage.py migrate
```
