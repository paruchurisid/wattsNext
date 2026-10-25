"""Read-only current U.S. hazard layer from the official NWS API."""
import json
import urllib.request
import urllib.error

NWS_ALERTS = "https://api.weather.gov/alerts/active?status=actual&message_type=alert,update"

def active_alerts():
    request = urllib.request.Request(NWS_ALERTS, headers={
        "Accept": "application/geo+json, application/geo+json", 
        "User-Agent": "WattsNext/1.0 contact=local-demo"
    })
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode())
        features = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            features.append({
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": {
                    "event": props.get("event", "Weather alert"),
                    "severity": props.get("severity", "Unknown"),
                    "headline": props.get("headline", ""),
                    "area": props.get("areaDesc", "United States"),
                    "expires": props.get("expires"),
                    "source": "National Weather Service"
                }
            })
        return {"type": "FeatureCollection", "features": features, "source": "NWS", "live": True}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return {"type": "FeatureCollection", "features": [], "source": "NWS", "live": False, "error": str(exc)}
