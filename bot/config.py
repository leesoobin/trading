import os
import yaml
from pathlib import Path


def load_config(path: str = None) -> dict:
    if path is None:
        path = Path(__file__).parent.parent / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class Config:
    def __init__(self, path: str = None):
        self._data = load_config(path)

    def get(self, *keys, default=None):
        node = self._data
        for key in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(key, default)
            if node is None:
                return default
        return node

    @property
    def upbit(self) -> dict:
        return self._data.get("upbit", {})

    @property
    def kis(self) -> dict:
        return self._data.get("kis", {})

    @property
    def telegram(self) -> dict:
        return self._data.get("telegram", {})

    @property
    def strategy(self) -> dict:
        return self._data.get("strategy", {})

    @property
    def risk(self) -> dict:
        return self._data.get("risk", {})

    @property
    def indicators(self) -> dict:
        return self._data.get("indicators", {})
