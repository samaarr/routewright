"""Google Places Autocomplete (New) client for backend-controlled suggestions (D34-D36).

Verified against the official docs (2026-10-06):
    - POST https://places.googleapis.com/v1/places:autocomplete
    - X-Goog-Api-Key header; X-Goog-FieldMask is optional — we send a minimal
      one so only identifying text and IDs come back.
    - ``includedPrimaryTypes: ["(cities)"]`` restricts to city-type results.
    - ``locationBias.rectangle`` biases (does not restrict) toward an area, so
      outside-city places remain selectable (D25).
    - Up to 5 predictions per request.

Session tokens (``sessionToken``): the browser generates one per search
session and sends it with every suggestion request and with the selection
lookup that ends it (Place Details with the same token). Per Google's session
pricing page, the first 12 Autocomplete requests in a session are still billed
per request ("Autocomplete Requests" SKU); only requests 13+ in a session that
is concluded by Place Details are free; an abandoned session is billed per
request; a token reused after the session ended is billed as if absent. The
selection lookup itself bills by its own field mask. We therefore follow the
documented completion rule but claim no session discount in cost estimates.
"""

import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.services.area import Viewport
from app.services.errors import ProviderTemporaryError, QuotaExceededError

AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
SUGGESTION_FIELD_MASK = (
    "suggestions.placePrediction.placeId,"
    "suggestions.placePrediction.structuredFormat.mainText.text,"
    "suggestions.placePrediction.structuredFormat.secondaryText.text"
)
SuggestionKind = Literal["city", "place"]
_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,300}$")


class InvalidQueryError(ValueError):
    """The provider rejected the query as invalid (HTTP 400)."""


@dataclass(frozen=True)
class Suggestion:
    place_id: str
    primary_text: str
    secondary_text: str | None


def build_request_body(
    query: str,
    *,
    kind: SuggestionKind,
    session_token: str | None,
    bias: Viewport | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"input": query}
    if session_token:
        body["sessionToken"] = session_token
    if kind == "city":
        body["includedPrimaryTypes"] = ["(cities)"]
    elif bias is not None:
        body["locationBias"] = {
            "rectangle": {
                "low": {"latitude": bias.low_lat, "longitude": bias.low_lng},
                "high": {"latitude": bias.high_lat, "longitude": bias.high_lng},
            }
        }
    return body


def parse_suggestions(payload: Any) -> list[Suggestion]:
    """Keep only place predictions with a valid ID and main text; never auto-pick."""
    if not isinstance(payload, dict):
        raise ProviderTemporaryError("Provider returned an unreadable response")
    out: list[Suggestion] = []
    for item in payload.get("suggestions") or []:
        pred = item.get("placePrediction") if isinstance(item, dict) else None
        if not isinstance(pred, dict):
            continue
        pid = pred.get("placeId")
        fmt = pred.get("structuredFormat") or {}
        main = (fmt.get("mainText") or {}).get("text")
        secondary = (fmt.get("secondaryText") or {}).get("text")
        if not isinstance(pid, str) or not _PLACE_ID_RE.fullmatch(pid):
            continue
        if not isinstance(main, str) or not main.strip():
            continue
        out.append(
            Suggestion(
                place_id=pid,
                primary_text=main.strip()[:300],
                secondary_text=secondary.strip()[:300]
                if isinstance(secondary, str) and secondary.strip()
                else None,
            )
        )
    return out


async def fetch_suggestions(
    query: str,
    *,
    kind: SuggestionKind,
    session_token: str | None,
    bias: Viewport | None,
    client: httpx.AsyncClient | None = None,
) -> list[Suggestion]:
    """One Autocomplete request. The caller handles admission and budget."""
    body = build_request_body(query, kind=kind, session_token=session_token, bias=bias)
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": SUGGESTION_FIELD_MASK,
    }
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=10.0) as one_shot:
                response = await one_shot.post(AUTOCOMPLETE_URL, json=body, headers=headers)
        else:
            response = await client.post(AUTOCOMPLETE_URL, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise ProviderTemporaryError("Suggestions temporarily unavailable") from exc
    if response.status_code == 400:
        raise InvalidQueryError("Provider rejected the query")
    if response.status_code == 429:
        raise QuotaExceededError("Places provider quota exceeded")
    if response.status_code != 200:
        raise ProviderTemporaryError("Suggestions temporarily unavailable")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderTemporaryError("Provider returned an unreadable response") from exc
    return parse_suggestions(payload)
