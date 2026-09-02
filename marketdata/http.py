from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Optional

import requests


DEFAULT_TIMEOUT_S = 20


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status_code: int
    text: str
    headers: Mapping[str, str]

    def json(self) -> Any:
        return json.loads(self.text)


def get(
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    params: Optional[Mapping[str, str]] = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> HttpResponse:
    h: MutableMapping[str, str] = {
        "User-Agent": "marketdata-fetcher/1.0 (+https://github.com/twistedbanyan-hue/test)",
        "Accept": "*/*",
    }
    if headers:
        h.update(headers)

    resp = requests.get(url, headers=h, params=params, timeout=timeout_s)
    return HttpResponse(
        url=str(resp.url),
        status_code=resp.status_code,
        text=resp.text,
        headers=dict(resp.headers),
    )

