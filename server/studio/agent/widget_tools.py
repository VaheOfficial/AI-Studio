"""Quick-answer tools whose results show as widgets in the chat: weather (Open-Meteo, no key), a calculator,
unit and currency conversion (currency: ECB rates via Frankfurter, no key) and world clocks. The model still writes
the answer in text; the widget is the visual."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

import httpx

from ..schemas_workspace import CalcDisplay, ClockDisplay, ClockItem, ConversionDisplay, WeatherDay, WeatherDisplay
from .types import ToolContext, ToolFailure, ToolOutcome, ToolSpec

_TIMEOUT = httpx.Timeout(15)

SPECS: list[ToolSpec] = [
    ToolSpec("get_weather", "Current weather and a daily forecast for a place (shown to the user as a weather card). "
                            "If the user didn't say where, use their location from what you know about them, or ask.",
             {"type": "object", "properties": {
                 "location": {"type": "string", "description": "City, optionally with region/country"},
                 "days": {"type": "integer", "description": "Forecast days, 1-10 (default 5)"},
                 "units": {"type": "string", "enum": ["metric", "imperial"]},
             }, "required": ["location"]}),
    ToolSpec("calculate", "Evaluate an arithmetic expression exactly (shown as a calculator card): + - * / // % **, "
                          "parentheses, sqrt, sin/cos/tan (radians), log, log10, log2, exp, abs, round, floor, ceil, "
                          "factorial, pi, e. Use it instead of doing arithmetic in your head.",
             {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}),
    ToolSpec("convert", "Convert units (length, mass, volume incl. cups/tbsp, area, speed, time, data, energy, "
                        "pressure, temperature) or currencies (ISO codes like USD, EUR, ISK; daily ECB rates). Shown "
                        "as a conversion card.",
             {"type": "object", "properties": {
                 "value": {"type": "number"}, "from_unit": {"type": "string"}, "to_unit": {"type": "string"},
             }, "required": ["value", "from_unit", "to_unit"]}),
    ToolSpec("world_time", "The current time in one or more places (shown as live clocks). Places can be cities or "
                           "IANA time zones; 'here' is the user's own time zone.",
             {"type": "object", "properties": {"locations": {"type": "array", "items": {"type": "string"}}},
              "required": ["locations"]}),
]

# ------------------------------- places -------------------------------


async def _geocode(name: str) -> dict[str, Any]:
    city = name.split(",")[0].strip()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get("https://geocoding-api.open-meteo.com/v1/search",
                        params={"name": city, "count": 5, "language": "en", "format": "json"})
    r.raise_for_status()
    results = r.json().get("results") or []
    if not results:
        raise ToolFailure(f"No place called {name!r} found")
    rest = [p.strip().lower() for p in name.split(",")[1:] if p.strip()]
    if rest:  # "Portland, Maine": prefer the match whose region/country mentions the rest
        for p in results:
            where = " ".join(str(p.get(k) or "") for k in ("admin1", "country", "country_code")).lower()
            if all(part in where for part in rest):
                return p
    return results[0]


def _place_label(p: dict[str, Any]) -> str:
    return ", ".join(x for x in (p.get("name"), p.get("admin1"), p.get("country")) if x)


# ------------------------------- weather -------------------------------

_WMO = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Freezing fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain", 71: "Light snow",
        73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers", 81: "Showers", 82: "Violent showers",
        85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm", 96: "Thunderstorm with hail",
        99: "Thunderstorm with heavy hail"}


async def _get_weather(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    place = await _geocode(a["location"])
    units = a.get("units") or ("imperial" if place.get("country_code") in ("US", "LR", "MM") else "metric")
    days = max(1, min(int(a.get("days") or 5), 10))
    params: dict[str, Any] = {
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": days,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
    }
    if units == "imperial":
        params.update(temperature_unit="fahrenheit", wind_speed_unit="mph", precipitation_unit="inch")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get("https://api.open-meteo.com/v1/forecast", params=params)
    r.raise_for_status()
    data = r.json()
    cur, day = data["current"], data["daily"]
    chances = day.get("precipitation_probability_max") or [None] * len(day["time"])
    forecast = [WeatherDay(date=d, code=int(code), summary=_WMO.get(int(code), "Unknown"), t_max=hi, t_min=lo,
                           precip_mm=p or 0.0, precip_chance=ch)
                for d, code, hi, lo, p, ch in zip(day["time"], day["weather_code"], day["temperature_2m_max"],
                                                  day["temperature_2m_min"], day["precipitation_sum"], chances)]
    w = WeatherDisplay(location=_place_label(place), timezone=data.get("timezone", ""), units=units,
                       temp=cur["temperature_2m"], feels_like=cur["apparent_temperature"],
                       code=int(cur["weather_code"]), summary=_WMO.get(int(cur["weather_code"]), "Unknown"),
                       humidity=int(cur["relative_humidity_2m"]), wind=cur["wind_speed_10m"],
                       is_day=bool(cur["is_day"]), days=forecast)
    deg, speed = ("°C", "km/h") if units == "metric" else ("°F", "mph")
    lines = [f"{w.location} now: {w.temp:.0f}{deg} (feels {w.feels_like:.0f}{deg}), {w.summary}, humidity "
             f"{w.humidity}%, wind {w.wind:.0f} {speed}."]
    lines += [f"{d.date}: {d.summary}, {d.t_min:.0f}-{d.t_max:.0f}{deg}"
              + (f", {d.precip_chance}% chance of precipitation" if d.precip_chance is not None else "")
              for d in forecast]
    return ToolOutcome(True, "\n".join(lines) + "\n(Shown to the user as a weather card; source Open-Meteo.)",
                       display=w)


# ------------------------------- calculator -------------------------------

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
    "atan": math.atan, "log": math.log, "ln": math.log, "log10": math.log10, "log2": math.log2, "exp": math.exp,
    "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil, "factorial": math.factorial,
    "degrees": math.degrees, "radians": math.radians,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10_000:
            raise ToolFailure("Exponent too large")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        args = [_eval(x) for x in node.args]
        if node.func.id == "factorial" and args and args[0] > 5000:
            raise ToolFailure("factorial argument too large")
        return _FUNCS[node.func.id](*args)
    raise ToolFailure("Only numbers, arithmetic and the listed math functions are allowed")


def _fmt(x: Any) -> str:
    if isinstance(x, int) or (isinstance(x, float) and x.is_integer() and abs(x) < 1e15):
        return f"{int(x):,}"
    return f"{x:,.10g}" if abs(x) >= 1e-4 else f"{x:.6g}"


async def _calculate(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    expr = a["expression"].replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")
    try:
        value = _eval(ast.parse(expr.strip(), mode="eval"))
    except SyntaxError as exc:
        raise ToolFailure(f"Can't read {a['expression']!r} as arithmetic") from exc
    except ZeroDivisionError as exc:
        raise ToolFailure("Division by zero") from exc
    except (ValueError, OverflowError) as exc:
        raise ToolFailure(f"Math error: {exc}") from exc
    result = _fmt(value)
    return ToolOutcome(True, f"{a['expression']} = {result}", display=CalcDisplay(expression=a["expression"], result=result))


# ------------------------------- units -------------------------------

# category → unit → factor to the category's base unit
_UNITS: dict[str, dict[str, float]] = {
    "length": {"m": 1, "km": 1e3, "cm": 1e-2, "mm": 1e-3, "um": 1e-6, "nm": 1e-9, "mi": 1609.344, "yd": 0.9144,
               "ft": 0.3048, "in": 0.0254, "nmi": 1852},
    "mass": {"kg": 1, "g": 1e-3, "mg": 1e-6, "t": 1e3, "lb": 0.45359237, "oz": 0.028349523125, "st": 6.35029318},
    "volume": {"l": 1, "ml": 1e-3, "cl": 1e-2, "dl": 0.1, "m3": 1e3, "cup": 0.2365882365, "tbsp": 0.01478676478125,
               "tsp": 0.00492892159375, "floz": 0.0295735295625, "pt": 0.473176473, "qt": 0.946352946,
               "gal": 3.785411784, "impgal": 4.54609},
    "area": {"m2": 1, "km2": 1e6, "cm2": 1e-4, "ha": 1e4, "acre": 4046.8564224, "ft2": 0.09290304,
             "in2": 0.00064516, "mi2": 2589988.110336, "yd2": 0.83612736},
    "speed": {"m/s": 1, "km/h": 1 / 3.6, "mph": 0.44704, "knot": 0.514444, "ft/s": 0.3048},
    "time": {"s": 1, "ms": 1e-3, "min": 60, "h": 3600, "day": 86400, "week": 604800, "year": 31557600},
    "data": {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3,
             "tib": 1024 ** 4, "bit": 0.125, "mbit": 1.25e5, "gbit": 1.25e8},
    "energy": {"j": 1, "kj": 1e3, "cal": 4.184, "kcal": 4184, "wh": 3600, "kwh": 3.6e6, "btu": 1055.05585},
    "pressure": {"pa": 1, "kpa": 1e3, "bar": 1e5, "psi": 6894.757293, "atm": 101325, "mmhg": 133.322387},
}
_ALIASES = {
    "meter": "m", "metre": "m", "kilometer": "km", "kilometre": "km", "centimeter": "cm", "millimeter": "mm",
    "mile": "mi", "yard": "yd", "foot": "ft", "feet": "ft", "inch": "in", "inches": "in", "nauticalmile": "nmi",
    "kilogram": "kg", "kilo": "kg", "gram": "g", "milligram": "mg", "tonne": "t", "ton": "t", "pound": "lb",
    "lbs": "lb", "ounce": "oz", "stone": "st", "liter": "l", "litre": "l", "milliliter": "ml", "millilitre": "ml",
    "cups": "cup", "tablespoon": "tbsp", "teaspoon": "tsp", "fluidounce": "floz", "fl oz": "floz", "pint": "pt",
    "quart": "qt", "gallon": "gal", "imperialgallon": "impgal", "sqm": "m2", "squaremeter": "m2", "hectare": "ha",
    "acres": "acre", "sqft": "ft2", "squarefoot": "ft2", "squarefeet": "ft2", "kph": "km/h", "kmh": "km/h",
    "kmph": "km/h", "mps": "m/s", "knots": "knot", "kt": "knot", "second": "s", "sec": "s", "minute": "min",
    "hour": "h", "hr": "h", "days": "day", "weeks": "week", "years": "year", "yr": "year", "byte": "b",
    "joule": "j", "calorie": "cal", "kilocalorie": "kcal", "watthour": "wh", "kilowatthour": "kwh",
    "pascal": "pa", "celsius": "c", "°c": "c", "fahrenheit": "f", "°f": "f", "kelvin": "k",
}


def _unit(raw: str) -> tuple[str, str] | None:
    u = raw.strip().lower().replace("²", "2").replace("³", "3").replace("µ", "u").replace(".", "")
    candidates = [u, u.replace(" ", ""), u.rstrip("s") if len(u) > 3 else u, u.replace(" ", "").rstrip("s")]
    for c in candidates:
        c = _ALIASES.get(c, c)
        if c in ("c", "f", "k"):
            return "temperature", c
        for cat, table in _UNITS.items():
            if c in table:
                return cat, c
    return None


def _temperature(v: float, src: str, dst: str) -> float:
    kelvin = {"c": v + 273.15, "f": (v - 32) * 5 / 9 + 273.15, "k": v}[src]
    return {"c": kelvin - 273.15, "f": (kelvin - 273.15) * 9 / 5 + 32, "k": kelvin}[dst]


async def _currency(value: float, src: str, dst: str) -> tuple[float, str]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        r = await c.get("https://api.frankfurter.dev/v1/latest", params={"amount": value, "from": src, "to": dst})
    if r.status_code == 404 or r.status_code == 422:
        raise ToolFailure(f"No exchange rate for {src} → {dst} (ECB rates cover ~30 major currencies)")
    r.raise_for_status()
    data = r.json()
    return float(data["rates"][dst]), f"ECB reference rate of {data.get('date', 'today')}"


async def _convert(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    value = float(a["value"])
    src_raw, dst_raw = a["from_unit"], a["to_unit"]
    src, dst = _unit(src_raw), _unit(dst_raw)
    note = None
    if src is None and dst is None and len(src_raw.strip()) == 3 and len(dst_raw.strip()) == 3:
        category = "currency"
        result, note = await _currency(value, src_raw.strip().upper(), dst_raw.strip().upper())
        src_label, dst_label = src_raw.strip().upper(), dst_raw.strip().upper()
    else:
        if src is None or dst is None:
            raise ToolFailure(f"Unknown unit: {src_raw if src is None else dst_raw}")
        if src[0] != dst[0]:
            raise ToolFailure(f"Can't convert {src[0]} ({src_raw}) to {dst[0]} ({dst_raw})")
        category = src[0]
        result = (_temperature(value, src[1], dst[1]) if category == "temperature"
                  else value * _UNITS[category][src[1]] / _UNITS[category][dst[1]])
        src_label, dst_label = src_raw.strip(), dst_raw.strip()
    display = ConversionDisplay(value=value, from_unit=src_label, to_unit=dst_label, result=result,
                                category=category, note=note)
    return ToolOutcome(True, f"{value:g} {src_label} = {result:.6g} {dst_label}" + (f" ({note})" if note else ""),
                       display=display)


# ------------------------------- clocks -------------------------------

_ZONES = {z.lower(): z for z in available_timezones()}


async def _world_time(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    places = [p for p in a["locations"] if isinstance(p, str) and p.strip()][:8] or ["here"]
    clocks: list[ClockItem] = []
    for p in places:
        key = p.strip().lower()
        if key in ("here", "local", "me", "my time"):
            tz = datetime.now().astimezone().tzinfo
            name = getattr(tz, "key", None) or _local_zone()
            clocks.append(ClockItem(location="Your time", timezone=name))
        elif key in _ZONES:
            clocks.append(ClockItem(location=_ZONES[key].split("/")[-1].replace("_", " "), timezone=_ZONES[key]))
        else:
            place = await _geocode(p)
            clocks.append(ClockItem(location=_place_label(place), timezone=place["timezone"]))
    now = datetime.now(ZoneInfo("UTC"))
    lines = [f"{c.location}: {now.astimezone(ZoneInfo(c.timezone)):%A %Y-%m-%d %H:%M} ({c.timezone})" for c in clocks]
    return ToolOutcome(True, "\n".join(lines) + "\n(Shown to the user as live clocks.)", display=ClockDisplay(clocks=clocks))


def _local_zone() -> str:
    """The PC's IANA zone name (Windows only exposes a display name like 'Pacific Daylight Time')."""
    try:
        import tzlocal  # type: ignore[import-not-found]

        return str(tzlocal.get_localzone_name())
    except Exception:  # noqa: BLE001 - optional dependency
        offset = datetime.now().astimezone().utcoffset()
        hours = int(offset.total_seconds() // 3600) if offset else 0
        return f"Etc/GMT{-hours:+d}" if hours else "UTC"


IMPL: dict[str, Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutcome]]] = {
    "get_weather": _get_weather, "calculate": _calculate, "convert": _convert, "world_time": _world_time,
}
