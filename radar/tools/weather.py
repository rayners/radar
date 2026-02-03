"""Weather tool using Open-Meteo API (free, no API key required)."""

import httpx

from radar.semantic import is_embedding_available, search_memories, store_memory
from radar.tools import tool

# Weather codes from WMO
WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


def _get_remembered_location() -> dict | None:
    """Search semantic memory for stored location."""
    if not is_embedding_available():
        return None

    try:
        # Search for location-related memories
        memories = search_memories("my location weather city I live in", limit=3)
        for memory in memories:
            content = memory["content"].lower()
            # Look for patterns like "My weather location is X"
            if "weather location" in content or "i live in" in content or "my location" in content:
                # Try to extract city from the memory
                if memory["similarity"] > 0.5:
                    # Return the raw content for the LLM to parse
                    return {"raw": memory["content"]}
        return None
    except Exception:
        return None


def _geocode(location: str) -> dict | None:
    """Geocode a location name to coordinates.

    Args:
        location: City name or location string

    Returns:
        Dict with name, country, latitude, longitude or None if not found
    """
    try:
        response = httpx.get(
            GEOCODING_URL,
            params={"name": location, "count": 1, "language": "en", "format": "json"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        if not results:
            return None

        result = results[0]
        return {
            "name": result.get("name"),
            "country": result.get("country", ""),
            "admin1": result.get("admin1", ""),  # State/province
            "latitude": result["latitude"],
            "longitude": result["longitude"],
        }
    except Exception:
        return None


def _get_weather(lat: float, lon: float) -> dict | None:
    """Fetch weather data from Open-Meteo API.

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        Dict with current conditions and forecast or None on error
    """
    try:
        response = httpx.get(
            WEATHER_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
                "forecast_days": 4,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _format_weather(location_info: dict, weather_data: dict) -> str:
    """Format weather data for display.

    Args:
        location_info: Dict with name, country
        weather_data: Raw weather data from API

    Returns:
        Formatted weather string
    """
    current = weather_data.get("current", {})
    daily = weather_data.get("daily", {})

    # Format location
    location_parts = [location_info["name"]]
    if location_info.get("admin1"):
        location_parts.append(location_info["admin1"])
    if location_info.get("country"):
        location_parts.append(location_info["country"])
    location_str = ", ".join(location_parts)

    # Current conditions
    temp = current.get("temperature_2m", "N/A")
    feels_like = current.get("apparent_temperature", "N/A")
    humidity = current.get("relative_humidity_2m", "N/A")
    wind = current.get("wind_speed_10m", "N/A")
    weather_code = current.get("weather_code", 0)
    condition = WEATHER_CODES.get(weather_code, "Unknown")

    lines = [
        f"**Weather for {location_str}**",
        "",
        f"**Now:** {condition}, {temp}°F (feels like {feels_like}°F)",
        f"Humidity: {humidity}% | Wind: {wind} mph",
        "",
        "**Forecast:**",
    ]

    # Daily forecast
    dates = daily.get("time", [])
    max_temps = daily.get("temperature_2m_max", [])
    min_temps = daily.get("temperature_2m_min", [])
    codes = daily.get("weather_code", [])
    precip_probs = daily.get("precipitation_probability_max", [])

    for i in range(min(3, len(dates))):
        if i == 0:
            day_label = "Today"
        else:
            day_label = dates[i]

        code = codes[i] if i < len(codes) else 0
        condition = WEATHER_CODES.get(code, "Unknown")
        min_t = min_temps[i] if i < len(min_temps) else "N/A"
        max_t = max_temps[i] if i < len(max_temps) else "N/A"
        precip = precip_probs[i] if i < len(precip_probs) else None

        forecast_line = f"- {day_label}: {condition}, {min_t}°F - {max_t}°F"
        if precip is not None and precip > 0:
            forecast_line += f" ({precip}% chance of rain)"
        lines.append(forecast_line)

    return "\n".join(lines)


@tool(
    name="weather",
    description="Get current weather and forecast. Uses remembered location or asks for one.",
    parameters={
        "location": {
            "type": "string",
            "description": "City name (optional if location was previously saved)",
            "optional": True,
        },
        "save_location": {
            "type": "boolean",
            "description": "Save as default location (default: true)",
            "optional": True,
        },
    },
)
def weather(location: str | None = None, save_location: bool = True) -> str:
    """Get current weather and forecast.

    Args:
        location: City name (optional if previously saved)
        save_location: Whether to save this as the default location

    Returns:
        Formatted weather report or error/prompt message
    """
    location_info = None

    # If no location provided, check memory
    if not location:
        remembered = _get_remembered_location()
        if remembered:
            # The memory contains something like "My weather location is Seattle, United States"
            # Try to extract and geocode it
            raw = remembered.get("raw", "")
            # Simple extraction: look for text after "is" or "in"
            for marker in ["location is ", "live in ", "I'm in "]:
                if marker in raw.lower():
                    idx = raw.lower().find(marker) + len(marker)
                    location = raw[idx:].strip().rstrip(".")
                    break
            if not location:
                # Use the whole memory content as a fallback
                location = raw

    # If still no location, ask for one
    if not location:
        return "I don't have a saved location. Please provide a city name, e.g., 'What's the weather in Seattle?'"

    # Geocode the location
    location_info = _geocode(location)
    if not location_info:
        return f"Could not find location: {location}. Please try a different city name."

    # Fetch weather
    weather_data = _get_weather(location_info["latitude"], location_info["longitude"])
    if not weather_data:
        return f"Could not fetch weather data for {location}. Please try again later."

    # Save location if requested
    if save_location and is_embedding_available():
        try:
            location_str = location_info["name"]
            if location_info.get("country"):
                location_str += f", {location_info['country']}"
            store_memory(f"My weather location is {location_str}", source="weather")
        except Exception:
            pass  # Don't fail on memory storage errors

    return _format_weather(location_info, weather_data)
