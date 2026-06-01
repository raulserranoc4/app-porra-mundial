import os
from abc import ABC, abstractmethod
from datetime import datetime
from random import choice, randint

import requests


class BaseFootballProvider(ABC):
    @abstractmethod
    def sync(self) -> dict:
        raise NotImplementedError


class ManualProvider(BaseFootballProvider):
    def sync(self) -> dict:
        return {"provider": "manual", "synced": False, "message": "Modo manual activo. No se consultó ninguna API."}


class MockProvider(BaseFootballProvider):
    def sync(self) -> dict:
        statuses = ["scheduled", "in_play", "finished"]
        return {
            "provider": "mock",
            "synced": True,
            "generated_at": datetime.utcnow().isoformat(),
            "sample": {
                "status": choice(statuses),
                "home_score": randint(0, 4),
                "away_score": randint(0, 4),
            },
        }


class ApiFootballProvider(BaseFootballProvider):
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY", "")
        self.base_url = (base_url or os.getenv("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io")).rstrip("/")

    def sync(self) -> dict:
        if not self.api_key:
            return {"provider": "api-football", "synced": False, "message": "API_FOOTBALL_KEY no configurada."}

        response = requests.get(
            f"{self.base_url}/status",
            headers={"x-apisports-key": self.api_key},
            timeout=20,
        )
        response.raise_for_status()
        return {"provider": "api-football", "synced": True, "status": response.json()}


def get_provider(name: str | None = None) -> BaseFootballProvider:
    provider = (name or os.getenv("FOOTBALL_PROVIDER", "manual")).strip().lower()
    if provider == "mock":
        return MockProvider()
    if provider in {"api", "api-football", "api_football"}:
        return ApiFootballProvider()
    return ManualProvider()
