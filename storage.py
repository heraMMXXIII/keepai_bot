import json
from pathlib import Path
from typing import Dict, Optional


BALANCE_SERVICES = ("elevenlabs", "suno", "runway")


class TopupStorage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _default_data(self) -> Dict[str, Dict[str, Optional[str]]]:
        return {"last_topup": {service: None for service in BALANCE_SERVICES}}

    def _read(self) -> Dict:
        if not self.path.exists():
            data = self._default_data()
            self._write(data)
            return data

        with self.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write(self, data: Dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=True, indent=2)

    def get_all_dates(self) -> Dict[str, Optional[str]]:
        data = self._read()
        last_topup = data.setdefault("last_topup", {})
        for service in BALANCE_SERVICES:
            last_topup.setdefault(service, None)
        return last_topup

    def set_date(self, service: str, date_value: str) -> None:
        if service not in BALANCE_SERVICES:
            raise ValueError(f"Unsupported service '{service}'")
        data = self._read()
        data.setdefault("last_topup", {})[service] = date_value
        self._write(data)

