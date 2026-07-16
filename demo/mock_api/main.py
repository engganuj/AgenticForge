"""Tiny demo REST API used as the target for the first MCP tool (M2) and,
later, the OpenAPI-to-MCP adapter (M3) via its auto-generated /openapi.json.
"""

from fastapi import FastAPI

app = FastAPI(title="Demo Weather API", version="1.0.0")

_WEATHER = {
    "london": {"tempC": 14, "condition": "cloudy"},
    "san francisco": {"tempC": 18, "condition": "foggy"},
    "mumbai": {"tempC": 31, "condition": "humid"},
}


@app.get("/weather/{city}", operation_id="getWeatherByCity")
def get_weather(city: str) -> dict:
    return _WEATHER.get(city.lower(), {"tempC": 20, "condition": "unknown"})


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DEMO_API_PORT", "9000")))
