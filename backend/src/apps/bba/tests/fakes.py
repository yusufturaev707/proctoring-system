"""Console'ning test o'rinbosarlari: HTTP darajasi va client darajasi."""

from __future__ import annotations

import copy
import json

CONSOLE_REGION = "ee6858af-01bb-4287-9b1e-dc913cb5befd"
CONSOLE_ROOM = "b7fb90b8-1913-4fe6-bdf9-a080f754167a"

#: `bba_agent_api.md` §4.4 dagi haqiqiy javob (qisqartirilgan).
SNAPSHOT = {
    "ID": "snap-1",
    "DeviceID": "5de8ef40-ef17-464d-ba5a-f3c55915a790",
    "CapturedAt": "2026-10-06T14:01:40+05:00",
    "Hostname": "BBA-110-3",
    "OS": "windows",
    "OSVersion": "Windows 10 Pro 21H1 (Build 19043.928)",
    "LastBootAt": "2026-10-06T13:01:16+05:00",
    "InstalledSoftware": [{"name": "RustDesk", "version": "1.4.9"}],
    "NetworkConfig": [
        {"name": "Ethernet 3", "mac": "30-C5-99-18-53-A1", "enabled": True, "dhcp": True,
         "addrs": ["192.168.0.57/24", "fe80::1/64"], "gateway": "192.168.0.254",
         "dns": ["192.168.200.200"]},
        {"name": "vEthernet (WSL)", "mac": "00-15-5D-01-02-03", "enabled": True,
         "addrs": ["172.20.0.1/20"], "gateway": ""},
    ],
    "Hardware": {
        "cpu": "13th Gen Intel(R) Core(TM) i5-13400F",
        "motherboard": "ASUSTeK COMPUTER INC. PRIME B760M-K",
        "storage": [{"model": "Lexar SSD NM620 512GB", "serial": "0000_0006_2505_2155."}],
        "ids": {
            "system_uuid": "124023ec-fff9-9177-3e7d-30c5991853a1",
            "system_serial": "System Serial Number",
            "baseboard_serial": "250861367400312",
            "cpu_id": "BFEBFBFF000B0671",
            "machine_guid": "a865c9f2-56ae-43c5-a9c4-d2d423d2ce34",
            "tpm_ek_hash": "8fcbaf1facb3b35bf26dd683f70f451e91e0205b89049b1cd4641d8d2e7bad2f",
            "network_adapters": [
                {"name": "Realtek PCIe GbE Family Controller #3", "mac": "C4-62-37-01-DE-1A"},
                {"name": "Realtek Gaming 2.5GbE Family Controller", "mac": "30-C5-99-18-53-A1"},
            ],
        },
    },
    "StartupApps": [{"name": "RustDesk", "enabled": True, "scope": "machine", "command": "rustdesk.exe"}],
}


def console_device(console_id: str, *, status="online", room=CONSOLE_ROOM, **extra) -> dict:
    return {
        "ID": console_id,
        "Status": status,
        "RoomID": room,
        "EnrolledAt": "2026-09-04T18:45:16+05:00",
        "LastSeenAt": "2026-10-06T13:01:23+05:00",
        "AgentVersion": "0.1.96",
        "RevokedAt": None,
        "HostnameCode": extra.pop("code", "BBA-110-3"),
        "Hostname": "BBA-110-3",
        "TestModeEnabled": False,
        **extra,
    }


class FakeResponse:
    def __init__(self, status=200, payload=None, *, text=None, headers=None):
        self.status_code = status
        if text is not None:
            self.text = text
        elif payload is not None:
            self.text = json.dumps(payload)
        else:
            self.text = ""
        self.content = self.text.encode()
        self.headers = headers or {}

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """`requests.Session` o'rnida: javoblar navbat bilan, chaqiruvlar yoziladi."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def login_ok(token="tok-1") -> FakeResponse:
    return FakeResponse(200, {"token": token, "expires_at": "2099-01-01T00:00:00+05:00",
                              "must_change_password": False})


class FakeConsole:
    """`BbaClient` o'rnida (servis testlari) — holat qo'lda o'zgartiriladi."""

    def __init__(self):
        self.regions_data = [{"ID": CONSOLE_REGION, "Name": "Toshkent Shahar", "Code": "R-01",
                              "Subnet": "172.16.0.0/16", "room_count": 1, "device_count": 2}]
        self.rooms_data = [{"ID": CONSOLE_ROOM, "RegionID": CONSOLE_REGION, "Name": "Class-110",
                            "Code": "RM-0003", "device_count": 2}]
        self.devices: list[dict] = []
        self.inventories: dict[str, dict] = {}
        self.jobs_data: list[dict] = []
        self.created_jobs: list[tuple] = []
        self.bulk_response: dict | None = None
        self.error: Exception | None = None

    def _maybe_fail(self):
        if self.error is not None:
            raise self.error

    def regions(self):
        self._maybe_fail()
        return copy.deepcopy(self.regions_data)

    def rooms(self):
        return copy.deepcopy(self.rooms_data)

    def iter_devices(self, **filters):
        self._maybe_fail()
        return iter(copy.deepcopy(self.devices))

    def inventory(self, console_id):
        self._maybe_fail()
        return copy.deepcopy(self.inventories.get(console_id, {"snapshot": None, "changes": None}))

    def jobs(self, **filters):
        records = self.jobs_data
        if filters.get("device_id"):
            records = [r for r in records if r.get("DeviceID") == filters["device_id"]]
        return {"jobs": copy.deepcopy(records), "total": len(records)}

    def create_job(self, console_id, body):
        self._maybe_fail()
        self.created_jobs.append((console_id, body))
        return {"job_id": f"job-{len(self.created_jobs)}", "status": "sent"}

    def bulk_create_jobs(self, console_ids, body):
        self._maybe_fail()
        self.created_jobs.append((tuple(console_ids), body))
        return self.bulk_response or {
            "bulk_operation_id": "bulk-1",
            "jobs": [{"device_id": cid, "job_id": f"job-{i}", "status": "sent"}
                     for i, cid in enumerate(console_ids)],
        }

    def wake(self, console_id):
        return {"status": "sent"}

    def wake_many(self, console_ids):
        return {"results": [{"device_id": cid, "status": "sent"} for cid in console_ids]}

    def connectivity(self, console_id, limit=50):
        return [{"Kind": "connected", "OccurredAt": "2026-10-06T13:00:00+05:00"}]

    def cancel_job(self, job_id):
        return {"status": "cancelled"}

    def resend_job(self, job_id):
        return {"status": "sent"}
