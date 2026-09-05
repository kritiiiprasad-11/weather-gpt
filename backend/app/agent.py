"""The conversational layer.

Two execution paths share one tool registry:

1. `LLMAgent`  - LangChain chat model with native tool calling. The model picks
   tools, we execute them ourselves so we can capture the structured payload
   that becomes a card in the React chat stream, then the model writes the
   final natural-language answer (streamed token by token).

2. `RuleAgent` - keyword router used when LLM_PROVIDER=none. Same tools, same
   cards, templated prose. This keeps the whole product demoable with zero
   paid keys.

Both emit the same event stream:
    {"type": "tool",  "name": ...}
    {"type": "card",  "card": {...}}
    {"type": "token", "text": ...}
    {"type": "done",  "tools_used": [...]}
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator

from .advisories import build_for_location
from .alerts import evaluate_location
from .config import settings
from .models import ChatCard, ChatRequest, Location
from .weather_service import WeatherServiceError, weather_service

log = logging.getLogger("weathergpt.agent")

LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi",
    "ta": "Tamil", "bn": "Bengali",
}

SYSTEM_PROMPT = """You are WeatherGPT, a meteorological assistant built for India.

Rules:
- Always call a tool before stating any weather number. Never invent values.
- Answer in {language}. Use the local script for that language.
- Keep replies to 2-4 short sentences unless the user asks for detail. People
  often hear this through text-to-speech, so write for the ear: no markdown,
  no bullet lists, no symbols like * or #. Spell out units ("kilometres per
  hour", "millimetres").
- When a tool returns a warning, lead with the hazard and the single most
  useful protective action.
- If the user has not named a place and no coordinates are available, ask which
  place they mean before calling tools.
- Current user context: {context}
"""


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------
_LOCATION_PROPS = {
    "place": {
        "type": "string",
        "description": "Place name, e.g. 'Pune' or 'Nashik, Maharashtra'. "
                       "Omit to use the user's own coordinates.",
    }
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "get_current_weather",
        "description": ("Live temperature, humidity, wind speed and direction, rainfall "
                        "rate, pressure and visibility for a place."),
        "parameters": {"type": "object", "properties": dict(_LOCATION_PROPS), "required": []},
    },
    {
        "name": "get_forecast",
        "description": "Hourly and daily forecast for the next 1-7 days.",
        "parameters": {
            "type": "object",
            "properties": {
                **_LOCATION_PROPS,
                "days": {"type": "integer", "description": "Days ahead, 1 to 7."},
            },
            "required": [],
        },
    },
    {
        "name": "check_extreme_weather",
        "description": ("Run the flash flood, cyclone and heatwave threshold checks and "
                        "return colour-coded warnings. Call this whenever the user asks "
                        "about safety, storms, floods, heat or 'is it safe'."),
        "parameters": {"type": "object", "properties": dict(_LOCATION_PROPS), "required": []},
    },
    {
        "name": "get_sector_advisory",
        "description": ("Practical guidance for a specific sector: agriculture (irrigation, "
                        "spraying, harvest), urban_transport (travel, waterlogging), "
                        "aviation (cloud base, visibility, shear), marine (sea state)."),
        "parameters": {
            "type": "object",
            "properties": {
                **_LOCATION_PROPS,
                "sector": {
                    "type": "string",
                    "enum": ["agriculture", "urban_transport", "aviation", "marine"],
                },
            },
            "required": ["sector"],
        },
    },
    {
        "name": "compare_historical_climate",
        "description": ("Compare this month's rainfall or temperature against a multi-year "
                        "baseline from the reanalysis archive."),
        "parameters": {
            "type": "object",
            "properties": {
                **_LOCATION_PROPS,
                "variable": {"type": "string", "enum": ["rainfall", "temperature"]},
                "month": {"type": "integer", "description": "1-12. Defaults to current month."},
                "years": {"type": "integer", "description": "Baseline length, default 10."},
            },
            "required": [],
        },
    },
]


async def _resolve(args: dict, req: ChatRequest) -> Location:
    """Prefer a named place; fall back to the user's coordinates.

    A named place that does not geocode (the extractor picked up "my field")
    must not become an error - it should quietly fall back to where the user is.
    """
    place = args.get("place") or req.place
    if place:
        try:
            return await weather_service.resolve(place=place)
        except Exception:  # noqa: BLE001 - not a real place, use coordinates
            pass
    return await weather_service.resolve(latitude=req.latitude, longitude=req.longitude)


async def execute_tool(name: str, args: dict, req: ChatRequest) -> tuple[str, ChatCard | None]:
    """Run a tool. Returns (text for the model, card for the UI)."""
    loc = await _resolve(args, req)

    if name == "get_current_weather":
        cur = await weather_service.current(loc)
        payload = json.loads(cur.model_dump_json())
        return json.dumps(payload), ChatCard(type="weather", data=payload)

    if name == "get_forecast":
        days = int(args.get("days") or 3)
        fc = await weather_service.forecast(loc, hours=days * 24, days=days)
        payload = json.loads(fc.model_dump_json())
        compact = {
            "location": loc.name,
            "daily": [
                {"date": d, "max_c": mx, "min_c": mn, "rain_mm": rn}
                for d, mx, mn, rn in zip(
                    fc.daily_dates, fc.daily_max_c, fc.daily_min_c, fc.daily_rain_mm
                )
            ][:days],
        }
        return json.dumps(compact), ChatCard(type="forecast", data=payload)

    if name == "check_extreme_weather":
        bundle = await evaluate_location(loc)
        payload = json.loads(bundle.model_dump_json())
        return json.dumps(payload), ChatCard(type="alert", data=payload)

    if name == "get_sector_advisory":
        sector = args.get("sector", "agriculture")
        adv = await build_for_location(loc, sector)
        payload = json.loads(adv.model_dump_json())
        return json.dumps(payload), ChatCard(type="advisory", data=payload)

    if name == "compare_historical_climate":
        cmp = await weather_service.compare_climate(
            loc,
            variable=args.get("variable") or "rainfall",
            month=args.get("month"),
            years=int(args.get("years") or 10),
        )
        payload = json.loads(cmp.model_dump_json())
        return json.dumps(payload), ChatCard(type="climate", data=payload)

    return json.dumps({"error": f"Unknown tool {name}"}), None


# ---------------------------------------------------------------------------
# LLM-backed agent
# ---------------------------------------------------------------------------
def build_llm(streaming: bool = False):
    p = settings.LLM_PROVIDER
    if p == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.2,
        )
    if p == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=0.2,
            streaming=streaming,
        )
    if p == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=settings.GROQ_MODEL,
            api_key=settings.GROQ_API_KEY,
            temperature=0.2,
        )
    if p == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.OLLAMA_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=0.2,
        )
    raise RuntimeError("LLM_PROVIDER is 'none'")


class LLMAgent:
    MAX_TOOL_ROUNDS = 3

    async def stream(self, req: ChatRequest) -> AsyncGenerator[dict, None]:
        from langchain_core.messages import (
            AIMessage,
            HumanMessage,
            SystemMessage,
            ToolMessage,
        )

        llm = build_llm(streaming=True)
        bound = llm.bind_tools(TOOL_SPECS)

        context = (
            f"latitude={req.latitude}, longitude={req.longitude}, "
            f"saved place={req.place or 'unknown'}"
        )
        messages: list[Any] = [
            SystemMessage(
                content=SYSTEM_PROMPT.format(
                    language=LANGUAGE_NAMES.get(req.language, "English"),
                    context=context,
                )
            )
        ]
        for turn in req.history[-8:]:
            messages.append(
                HumanMessage(content=turn.content)
                if turn.role == "user"
                else AIMessage(content=turn.content)
            )
        messages.append(HumanMessage(content=req.message))

        tools_used: list[str] = []
        for _ in range(self.MAX_TOOL_ROUNDS):
            ai = await bound.ainvoke(messages)
            calls = getattr(ai, "tool_calls", None) or []
            if not calls:
                messages.append(ai)
                break
            messages.append(ai)
            for call in calls:
                name = call["name"]
                args = call.get("args") or {}
                tools_used.append(name)
                yield {"type": "tool", "name": name, "args": args}
                try:
                    result, card = await execute_tool(name, args, req)
                    if card:
                        yield {"type": "card", "card": card.model_dump()}
                except WeatherServiceError as exc:
                    result = json.dumps({"error": str(exc)})
                except Exception as exc:  # noqa: BLE001
                    result = json.dumps({"error": f"Data source failed: {exc}"})
                messages.append(ToolMessage(content=result, tool_call_id=call["id"]))

        # Final answer, streamed without tools bound so it cannot loop again.
        last = messages[-1]
        if getattr(last, "content", "") and not getattr(last, "tool_calls", None):
            for chunk in _chunk(last.content):
                yield {"type": "token", "text": chunk}
        else:
            async for piece in llm.astream(messages):
                if piece.content:
                    yield {"type": "token", "text": piece.content}

        yield {"type": "done", "tools_used": tools_used}


def _chunk(text: str, size: int = 10):
    """Split a finished string into small pieces so the UI can type it out."""
    words = text.split()
    for i in range(0, len(words), size):
        piece = " ".join(words[i:i + size])
        yield piece if i == 0 else " " + piece


# ---------------------------------------------------------------------------
# Keyless fallback agent
# ---------------------------------------------------------------------------
KEYWORDS = {
    "check_extreme_weather": [
        "alert", "warning", "safe", "safety", "cyclone", "storm", "flood", "flooding",
        "heatwave", "heat wave", "danger", "चेतावनी", "बाढ़", "तूफान", "गर्मी",
    ],
    "get_sector_advisory": [
        "crop", "farm", "irrigat", "spray", "sow", "harvest", "फसल", "सिंचाई",
        "flight", "aviation", "runway", "visibility", "fishing", "sea", "boat",
        "traffic", "commute", "travel", "drive", "road",
    ],
    "compare_historical_climate": [
        "average", "compare", "historical", "normal", "trend", "10-year", "10 year",
        "last year", "baseline", "औसत", "तुलना",
    ],
    "get_forecast": [
        "tomorrow", "forecast", "next", "week", "weekend", "will it", "कल", "पूर्वानुमान",
    ],
}

SECTOR_HINTS = {
    "agriculture": ["crop", "farm", "irrigat", "spray", "sow", "harvest", "फसल", "सिंचाई"],
    "aviation": ["flight", "aviation", "runway", "cloud base", "shear", "airport"],
    "marine": ["fishing", "sea", "boat", "marine", "wave", "मछली"],
    "urban_transport": ["traffic", "commute", "travel", "drive", "road", "यातायात"],
}

PHRASEBOOK = {
    "en": "{place}: {cond}, {temp} degrees Celsius, humidity {hum} percent, wind {wind} kilometres per hour from the {dir}.",
    "hi": "{place}: {cond}, तापमान {temp} डिग्री सेल्सियस, आर्द्रता {hum} प्रतिशत, हवा {wind} किलोमीटर प्रति घंटा, दिशा {dir}।",
    "mr": "{place}: {cond}, तापमान {temp} अंश सेल्सिअस, आर्द्रता {hum} टक्के, वारा {wind} किलोमीटर प्रति तास, दिशा {dir}.",
    "ta": "{place}: {cond}, வெப்பநிலை {temp} டிகிரி செல்சியஸ், ஈரப்பதம் {hum} சதவீதம், காற்று {wind} கிலோமீட்டர் {dir} திசையில்.",
    "bn": "{place}: {cond}, তাপমাত্রা {temp} ডিগ্রি সেলসিয়াস, আর্দ্রতা {hum} শতাংশ, বাতাস {wind} কিলোমিটার প্রতি ঘণ্টা, {dir} দিক থেকে।",
}


class RuleAgent:
    """Deterministic router. No model, no key, still useful."""

    def _pick_tool(self, text: str) -> tuple[str, dict]:
        low = text.lower()
        for tool, words in KEYWORDS.items():
            if any(w in low for w in words):
                args: dict[str, Any] = {}
                if tool == "get_sector_advisory":
                    args["sector"] = next(
                        (s for s, hints in SECTOR_HINTS.items() if any(h in low for h in hints)),
                        "agriculture",
                    )
                if tool == "compare_historical_climate":
                    args["variable"] = "temperature" if "temp" in low else "rainfall"
                if tool == "get_forecast":
                    args["days"] = 7 if "week" in low else 3
                place = self._place(text)
                if place:
                    args["place"] = place
                return tool, args
        args = {}
        place = self._place(text)
        if place:
            args["place"] = place
        return "get_current_weather", args

    # Words that follow "in/at/for" but are never part of a place name.
    _STOP = {
        "the", "my", "our", "this", "today", "tomorrow", "tonight", "now",
        "morning", "evening", "afternoon", "night", "week", "weekend", "month",
        "year", "field", "farm", "crop", "crops", "home", "here", "there",
        "me", "us", "travel", "travelling", "traveling", "driving", "work",
        "rain", "raining", "weather", "temperature", "forecast", "next",
        "to", "with", "from", "by", "compare", "average", "normal", "last",
    }

    @classmethod
    def _place(cls, text: str) -> str | None:
        """Pull a place name out of free text.

        Case-insensitive on purpose: people type "in pune", not "in Pune".
        Anything that survives goes to the geocoder, which is the real
        validator - if it is not a place, _resolve falls back to coordinates.
        """
        m = re.search(
            r"\b(?:in|at|for|near|around|over|of)\s+"
            r"([\w'\u2019.-]+(?:\s+[\w'\u2019.-]+){0,2})",
            text,
            re.IGNORECASE,
        )
        if not m:
            return None
        words = [w.strip("?.,!;:") for w in m.group(1).split()]
        # Stop at the point the sentence stops naming a place:
        # "maharashtra vs 10 year average" -> "maharashtra".
        cut = {"vs", "versus", "compared", "against", "and", "or", "than"}
        kept = []
        for w in words:
            if w.lower() in cut or w.isdigit():
                break
            kept.append(w)
        words = kept
        # Drop trailing filler: "pune tomorrow" -> "pune".
        while words and words[-1].lower() in cls._STOP:
            words.pop()
        # Drop leading filler: "the nashik area" -> "nashik area".
        while words and words[0].lower() in cls._STOP:
            words.pop(0)
        return " ".join(words) or None

    async def stream(self, req: ChatRequest) -> AsyncGenerator[dict, None]:
        tool, args = self._pick_tool(req.message)
        yield {"type": "tool", "name": tool, "args": args}
        try:
            _, card = await execute_tool(tool, args, req)
        except WeatherServiceError as exc:
            yield {"type": "token", "text": str(exc)}
            yield {"type": "done", "tools_used": [tool]}
            return
        if card:
            yield {"type": "card", "card": card.model_dump()}
            for piece in _chunk(self._narrate(tool, card, req.language)):
                yield {"type": "token", "text": piece}
        yield {"type": "done", "tools_used": [tool]}

    @staticmethod
    def _narrate(tool: str, card: ChatCard, lang: str) -> str:
        d = card.data
        if tool == "get_current_weather":
            tpl = PHRASEBOOK.get(lang, PHRASEBOOK["en"])
            return tpl.format(
                place=d["location"]["name"],
                cond=d.get("condition") or "—",
                temp=round(d.get("temperature_c") or 0),
                hum=round(d.get("humidity_pct") or 0),
                wind=round(d.get("wind_speed_kmh") or 0),
                dir=d.get("wind_direction_cardinal") or "—",
            )
        if tool == "check_extreme_weather":
            if not d["alerts"]:
                return f"No hazard thresholds are being crossed at {d['location']['name']} right now."
            a = d["alerts"][0]
            return f"{a['headline']} for {d['location']['name']}. {a['detail']} {a['action']}"
        if tool == "get_sector_advisory":
            head = f"{d['headline']} for {d['location']['name']}. "
            return head + " ".join(i["guidance"] for i in d["items"][:2])
        if tool == "compare_historical_climate":
            return d["verdict"]
        if tool == "get_forecast":
            if d["daily_dates"]:
                return (
                    f"Next few days at {d['location']['name']}: highs around "
                    f"{round(max(d['daily_max_c']))} degrees, lows around "
                    f"{round(min(d['daily_min_c']))}, with about "
                    f"{round(sum(d['daily_rain_mm']))} millimetres of rain in total."
                )
        return "Here is what the data shows."


_REQUIRED_KEY = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "ollama": None,  # local, no key
}


def get_agent():
    """Return the LLM agent if it can actually be constructed, else the router.

    The default provider is Groq/Llama 3.3, but a fresh clone has no key and
    may not have the provider package installed. Rather than 500 on the first
    message, fall back to the deterministic agent and say so in the log.
    """
    provider = settings.LLM_PROVIDER
    if provider == "none":
        return RuleAgent()

    key_name = _REQUIRED_KEY.get(provider)
    if key_name and not getattr(settings, key_name, ""):
        log.warning(
            "LLM_PROVIDER=%s but %s is empty. Using the rule-based agent. "
            "Get a free Groq key at https://console.groq.com/keys",
            provider, key_name,
        )
        return RuleAgent()

    try:
        build_llm()
    except ImportError as exc:
        pkg = {
            "groq": "langchain-groq",
            "gemini": "langchain-google-genai",
            "openai": "langchain-openai",
            "ollama": "langchain-ollama",
        }.get(provider, "the provider package")
        log.warning(
            "LLM_PROVIDER=%s but %s is not installed (%s). Using the "
            "rule-based agent. Run: pip install %s",
            provider, pkg, exc, pkg,
        )
        return RuleAgent()
    except Exception as exc:  # noqa: BLE001 - bad key, bad URL, unreachable host
        log.warning(
            "Could not start the %s model (%s). Using the rule-based agent.",
            provider, exc,
        )
        return RuleAgent()

    return LLMAgent()
