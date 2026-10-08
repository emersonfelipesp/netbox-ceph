# Installation

## Requirements

- NetBox 4.5.8 through 4.6.6, plus the NetBox 4.7 series (4.7.0 GA through 4.7.99)
- Python 3.12+
- [`netbox-proxbox`](https://github.com/emersonfelipesp/netbox-proxbox) `>=0.0.25.post2,<0.1.0`
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
