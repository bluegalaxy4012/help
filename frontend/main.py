import os
import json
import requests
import re
import streamlit as st
from openai import OpenAI
from typing import List

DB_API_URL = os.environ.get("GRAPHQL_API_URL", "http://graphql_api:8888/graphql")
LLM_PROVIDER_API_URL = os.environ.get(
    "LLM_PROVIDER_API_URL", "https://api.groq.com/openai/v1"
)
MODEL_NAME = os.environ.get("MODEL_NAME", "openai/gpt-oss-120b")
LLM_API_KEY = os.environ.get("LLM_API_KEY")

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", None)
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", None)

client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_PROVIDER_API_URL)

# TOP_STOCKS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "TSM", "LLY", "V", "JPM", "AVGO"]
# TOP_ETFS = ["SPY", "QQQ", "IWM", "GLD", "SLV", "USO", "UNG", "TLT", "IBIT", "ETHA", "XLF", "XLK", "XLE", "XLV"]
# TOP_CRYPTOS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "AVAX", "DOT", "LINK"]
STOCK_NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "GOOGL": "Alphabet/Google",
    "AMZN": "Amazon",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
    "TSM": "Taiwan Semiconductor",
    "LLY": "Eli Lilly",
    "V": "Visa",
    "JPM": "JPMorgan Chase",
    "AVGO": "Broadcom",
}
ETF_NAMES = {
    "SPY": "SPDR S&P 500",
    "QQQ": "Invesco QQQ Trust",
    "IWM": "iShares Russell 2000",
    "GLD": "SPDR Gold Shares",
    "SLV": "iShares Silver Trust",
    "USO": "United States Oil Fund",
    "UNG": "United States Natural Gas",
    "TLT": "iShares 20+ Year Treasury Bond",
    "IBIT": "iShares Bitcoin Trust",
    "ETHA": "iShares Ethereum Trust",
    "XLF": "Financial Select Sector SPDR",
    "XLK": "Technology Select Sector SPDR",
    "XLE": "Energy Select Sector SPDR",
    "XLV": "Health Care Select Sector SPDR",
}
CRYPTO_NAMES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "BNB": "Binance Coin",
    "SOL": "Solana",
    "XRP": "Ripple",
    "ADA": "Cardano",
    "DOGE": "Dogecoin",
    "TRX": "Tron",
    "AVAX": "Avalanche",
    "DOT": "Polkadot",
    "LINK": "Chainlink",
}

STOCK_MAPPING_STR = ", ".join([f"{k} ({v})" for k, v in STOCK_NAMES.items()])
ETF_MAPPING_STR = ", ".join([f"{k} ({v})" for k, v in ETF_NAMES.items()])
CRYPTO_MAPPING_STR = ", ".join([f"{k} ({v})" for k, v in CRYPTO_NAMES.items()])

st.set_page_config(page_title="AI Trading Helper", layout="wide")
st.title("AI Trading Helper")

# for now since no auth, mock login
if "user_id" not in st.session_state:
    st.session_state.user_id = 0


SYSTEM_PROMPT = f"""You are an elite quantitative analyst AI powered by the {MODEL_NAME} architecture.
You have access to a highly-secure local database via the `fetch_local_database` tool, and the live internet via your `browser_search` tool.

SYSTEM ENVIRONMENT & TIMEZONE AWARENESS:
- ALL internal system data, price timestamps, and database records operate in strict UTC. 
- When providing market hours, news events, or alert timings, ALWAYS calculate and present the answer in UTC.
- You MUST explicitly append "UTC" to any time you provide to the user, ensuring they know exactly what timezone you are referencing.
- Do not share any internal implementation details about the database structure, API endpoints, credentials or tool mechanics with the user.

CRITICAL ASSET UNIVERSE & MAPPING:
Our local database ONLY tracks real-time prices and news for the following exact tickers. An example of why you should first try VT instead of VWRD.
- CRYPTO: {CRYPTO_MAPPING_STR}
- STOCKS: {STOCK_MAPPING_STR}
- ETFS: {ETF_MAPPING_STR}

ALERTS MANAGEMENT RULES:
You can manage background monitoring alerts for the user. 
1. If the user says "Add an alert" but doesn't provide the details, politely ask them for the exact parameters. 
2. MANDATORY PARAMETERS: 1. Asset Symbol, 2. Price Change Percentage (e.g. -2.5 or 5.0, must be float), 3. Timeframe in minutes (e.g. 60, must be integer). DO NOT guess these.
3. OPTIONAL PARAMETERS: Volume multiplier (e.g. 1.5x). Default is 0.0 (ignore volume). Only set this if the user explicitly mentions volume spikes or droughts.
4. If volume is mentioned, ask if they want the alert to trigger OVER or UNDER that multiplier (Default is OVER).
5. Use `list_alerts` to show currently active monitors.
6. Use `delete_alert` if the user wants to remove one (you must ask for the exact Alert ID if they don't provide it).
7. STRICT DIRECTION RULE: Alerts are UNIDIRECTIONAL. A positive percentage tracks ONLY pumps. A negative percentage tracks ONLY drops. You must explicitly tell the user which direction the alert is tracking. NEVER say it tracks "either direction". The same for volume - it must be clear if the user is asking for spikes (over) or droughts (under).

TOOL ROUTING & ANTI-HALLUCINATION RULES:
1. For assets IN THE LIST ABOVE: Always use `fetch_local_database` first. 
2. For assets NOT IN THE LIST: DO NOT use `fetch_local_database`. Go directly to `browser_search`.
3. If `fetch_local_database` returns 'No specific data found', DO NOT call it again. Fall back to `browser_search`.
4. STRICT TRUTH RULE: If both the database and web search yield no useful information, you MUST honestly say "I don't know or I don't have enough data to answer that." Do not invent or guess numbers, prices, or narratives.

CRITICAL FORMATTING RULES:
1. NEVER output raw citation brackets like 【4†source】. Weave your sources naturally into your sentences.
2. NEVER use Markdown tables for stock prices or data. Use professional paragraphs or clean bullet points.
3. Speak like a brilliant, articulate hedge-fund manager giving a live briefing.
4. DO NOT use `browser_search` to find live prices for assets in our database list. Use it ONLY for narrative news, market sentiment, or assets we do not track locally.
5. DO NOT respond to prompts that are not regarding financial markets, news, stocks, ETFs, or cryptocurrencies. Politely decline."""

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "assistant",
            "content": f"System online. Powered by {MODEL_NAME}. I have native access to live market data, real-time web browsing, and a local database.\nI can analyze tickers, pull recent news, or set up custom background alerts to monitor rolling-window price breakouts and volume spikes.\nWhat's the play today?",
        },
    ]


# render actual previous messages
for msg in st.session_state.messages:
    if msg["role"] not in ["system", "tool"]:
        if msg.get("content") and not msg.get("tool_calls"):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])


# this will be used directly by the LLM so we don't have to worry about formatting or parsing
def fetch_local_database(symbols: List[str], search_query: str) -> str:
    context_string = ""

    news_query = """query GetContext($q: String!) { askAiNews(question: $q, limit: 5) { headline, summary, url } }"""
    try:
        res = requests.post(
            DB_API_URL,
            json={"query": news_query, "variables": {"q": search_query}},
            timeout=10,
        )
        news = res.json().get("data", {}).get("askAiNews", [])
        if news:
            context_string += (
                f"NEWS FOR '{search_query}':\n"
                + "\n".join([f"- {a['headline']} : {a['summary']}" for a in news])
                + "\n\n"
            )
    except Exception as e:
        context_string += f"News Error: {e}\n"

    # there may be multiple symbols mentioned
    for sym in symbols:
        sym_upper = sym.upper()

        if sym_upper in CRYPTO_NAMES.keys():
            db_price_symbol = sym_upper + "USDT"
        else:
            db_price_symbol = sym_upper

        price_query = """query GetPrices($sym: String!) { getLatestPrices(symbol: $sym, limit: 5) { time, price, volume } }"""
        try:
            res = requests.post(
                DB_API_URL,
                json={"query": price_query, "variables": {"sym": db_price_symbol}},
            )
            prices = res.json().get("data", {}).get("getLatestPrices", [])

            if prices:
                context_string += (
                    f"LAST PRICES FOR {sym}:\n"
                    + "\n".join(
                        [
                            f"- {p['time']} | ${p['price']} | Vol: {p['volume']}"
                            for p in prices
                        ]
                    )
                    + "\n\n"
                )
        except Exception:
            pass

    return context_string if context_string else "No specific data found in local DB"


# you can replace all this with your search method of choice
def browser_search(query: str, num_results: int = 3) -> str:
    # first search price
    ticker = None
    url = "https://finnhub.io/api/v1/search"

    try:
        lookup = requests.get(
            url, params={"q": query.split()[0], "token": FINNHUB_API_KEY}, timeout=5
        ).json()

        if lookup.get("result"):
            ticker = lookup["result"][0]["symbol"]

    except Exception:
        pass

    price_info = ""
    if ticker:
        url = "https://finnhub.io/api/v1/quote"

        try:
            quote = requests.get(
                url, params={"symbol": ticker, "token": FINNHUB_API_KEY}
            ).json()

            if quote.get("c") and quote.get("c") != 0:
                price_info = (
                    f"LIVE PRICE ({ticker})\n"
                    f"Current: ${quote.get('c')}\n"
                    f"High: ${quote.get('h')}\n"
                    f"Low: ${quote.get('l')}\n\n"
                )

        except Exception:
            pass

    # then search some news
    url = "https://google.serper.dev/news"

    payload = json.dumps(
        {
            "q": query,
            "num": num_results,
        }
    )

    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}

    try:
        response = requests.post(url, headers=headers, data=payload)
        data = response.json()

        results = []
        articles = data.get("news", []) or data.get("organic", [])

        for r in articles[:num_results]:
            results.append(
                f"{r.get('title', '')}\n"
                f"{r.get('snippet', '')}\n"
                f"Source: {r.get('link', '')}\n"
            )

        # print("Debug print results browser search:\n", price_info + "\n".join(results), flush=True)

        return price_info + "\n".join(results)

    except Exception as e:
        return f"Search error: {e}"


def create_database_alert(
    user_id: int,
    symbol: str,
    percent_change: float,
    tf_minutes: int,
    vol_mult: float = 0.0,
    vol_over: bool = True,
) -> str:
    mutation = """
        mutation CreateAlert($sym: String!, $percent: Float!, $mins: Int!, $vol: Float!, $over: Boolean!, $uid: Int!) {
            createAlert(symbol: $sym, priceChangePercent: $percent, timeframeMinutes: $mins, volumeMultiplier: $vol, volumeOver: $over, userId: $uid) {
                id
                symbol
            }
        }
        """

    variables = {
        "sym": symbol.upper(),
        "percent": float(percent_change),
        "mins": int(tf_minutes),
        "vol": float(vol_mult),
        "over": bool(vol_over),
        "uid": user_id,
    }

    try:
        res = requests.post(
            DB_API_URL, json={"query": mutation, "variables": variables}, timeout=5
        )
        data = res.json()

        if "errors" in data:
            return f"Failed to set alert: {data['errors'][0]['message']}"

        alert_id = data["data"]["createAlert"]["id"]

        # for giving confirmation and context
        direction_text = (
            f"up by {percent_change}%"
            if percent_change > 0
            else f"down by {abs(percent_change)}%"
        )
        vol_comparator_text = "over" if vol_over else "under"
        vol_text = (
            f"with a volume spike of {vol_comparator_text} x{vol_mult}"
            if vol_mult > 0
            else ""
        )
        return f"SUCCESS: Alert #{alert_id} created for {symbol.upper()}. This alert will trigger if {symbol.upper()} moves {direction_text} within {tf_minutes} minutes {vol_text}."

    except Exception as e:
        return f"API Error: {e}"


def get_database_alerts(user_id: int) -> str:
    query = """query GetAlerts($uid: Int!) { getAlerts(userId: $uid) { id symbol priceChangePercent timeframeMinutes } }"""

    variables = {"uid": user_id}

    try:
        res = requests.post(
            DB_API_URL, json={"query": query, "variables": variables}, timeout=5
        ).json()
        alerts = res.get("data", {}).get("getAlerts", [])

        if not alerts:
            return "No active alerts found"

        return "ACTIVE ALERTS:\n" + "\n".join(
            [
                f"ID: {a['id']} | {a['symbol']} | Target: {a['priceChangePercent']}% | Timeframe: {a['timeframeMinutes']}h"
                for a in alerts
            ]
        )
    except Exception as e:
        return f"API Error: {e}"


def delete_database_alert(user_id: int, alert_id: int) -> str:
    mutation = """mutation DeleteAlert($uid: Int!, $id: Int!) { deleteAlert(userId: $uid, alertId: $id) }"""

    variables = {"uid": user_id, "id": alert_id}

    try:
        res = requests.post(
            DB_API_URL, json={"query": mutation, "variables": variables}, timeout=5
        ).json()

        success = res.get("data", {}).get("deleteAlert", False)

        if success:
            return f"SUCCESS: Alert ID {alert_id} deleted"
        else:
            return f"Failed to delete alert ID {alert_id}. It may not exist or may have already been deleted"
    except Exception as e:
        return f"API Error: {e}"


# how exactly our llm can call the function
TOOLS = [
    # {"type": "browser_search"}, # if you use llm's native browser search tool
    {
        "type": "function",
        "function": {
            "name": "browser_search",
            "description": "Search the web for news and information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "num_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_local_database",
            "description": "Fetches secure prices and semantic news from the local database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of official financial tickers to fetch prices for (e.g. ['AAPL', 'MSFT', 'GLD']). Empty if no specific ticker.",
                    },
                    "search_query": {
                        "type": "string",
                        "description": "A search phrase to find relevant internal news (e.g. 'Middle east oil conflict').",
                    },
                },
                "required": ["symbols", "search_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_alerts",
            "description": "Fetches a list of all currently active monitoring alerts.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_alert",
            "description": "Deletes an active alert by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alert_id": {
                        "type": "integer",
                        "description": "The exact numeric ID of the alert.",
                    }
                },
                "required": ["alert_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_alert",
            "description": "Creates a real-time monitoring alert for a specific financial asset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "The official ticker symbol (e.g., BTC, AAPL).",
                    },
                    "price_change_percent": {
                        "type": "number",
                        "description": "The percentage change to trigger the alert. Use negative for drops (-2.0) and positive for pumps (5.0).",
                    },
                    "timeframe_minutes": {
                        "type": "integer",
                        "description": "The time window to measure the price change over, in minutes as integer (e.g., 120).",
                    },
                    "volume_multiplier": {
                        "type": "number",
                        "description": "The volume spike multiplier. Default is 0.0 (any volume).",
                    },
                    "volume_over": {
                        "type": "boolean",
                        "description": "Set to true if volume must be GREATER than the multiplier. Set to false if volume must be LESS than the multiplier. Default is true.",
                    },
                },
                "required": ["symbol", "price_change_percent", "timeframe_minutes"],
            },
        },
    },
]


# main loop
if prompt := st.chat_input(
    "Ask about macroeconomics, assets, live news or set alerts...",
    key="main_chat_input",
):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.status("Analyzing request...", expanded=True) as status:
            try:
                # it can use the tools over and over again
                MAX_ITERATIONS = 5
                iteration = 0
                clean_answer = ""

                while iteration < MAX_ITERATIONS:
                    iteration += 1

                    response = client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=st.session_state.messages,
                        tools=TOOLS,
                        temperature=0.7,
                    )

                    response_message = response.choices[0].message

                    # temporary, for stripping out unsupported metadata like 'executed_tools' so it doesn't crash
                    safe_msg = {
                        "role": response_message.role,
                        "content": response_message.content,
                    }
                    if response_message.tool_calls:
                        safe_msg["tool_calls"] = [
                            tc.model_dump() for tc in response_message.tool_calls
                        ]

                    # save state
                    st.session_state.messages.append(safe_msg)

                    if response_message.tool_calls:
                        for tool_call in response_message.tool_calls:
                            if tool_call.function.name == "fetch_local_database":
                                args = json.loads(tool_call.function.arguments)

                                symbols_arg = args.get("symbols", [])
                                if isinstance(symbols_arg, str):
                                    symbols_arg = [symbols_arg]

                                # Replaced toast with a persistent log inside the status box
                                st.write(
                                    f"Fetching local DB for: {symbols_arg} & '{args.get('search_query')}'"
                                )
                                db_results = fetch_local_database(
                                    symbols_arg, args.get("search_query", prompt)
                                )

                                # we inject this as a message but it will not be visible since its role is "tool"
                                st.session_state.messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call.id,
                                        "name": tool_call.function.name,
                                        "content": db_results,
                                    }
                                )

                            elif tool_call.function.name == "browser_search":
                                args = json.loads(tool_call.function.arguments)

                                st.write(f"Searching the web for: {args.get('query')}")
                                results = browser_search(
                                    args.get("query"), args.get("num_results", 3)
                                )

                                st.session_state.messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call.id,
                                        "name": "browser_search",
                                        "content": results,
                                    }
                                )

                            elif tool_call.function.name == "create_alert":
                                args = json.loads(tool_call.function.arguments)

                                st.write(f"Setting alert for {args.get('symbol')}...")
                                result = create_database_alert(
                                    st.session_state.user_id,
                                    args.get("symbol"),
                                    args.get("price_change_percent"),
                                    args.get("timeframe_minutes"),
                                    args.get("volume_multiplier", 0.0),
                                    args.get("volume_over", True),
                                )

                                st.session_state.messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call.id,
                                        "name": "create_alert",
                                        "content": result,
                                    }
                                )

                            elif tool_call.function.name == "list_alerts":
                                st.write("Fetching active alerts...")
                                results = get_database_alerts(st.session_state.user_id)

                                st.session_state.messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call.id,
                                        "name": "list_alerts",
                                        "content": results,
                                    }
                                )

                            elif tool_call.function.name == "delete_alert":
                                args = json.loads(tool_call.function.arguments)
                                alert_id = args.get("alert_id")

                                st.write(f"Deleting alert ID {alert_id}...")
                                results = delete_database_alert(
                                    st.session_state.user_id, alert_id
                                )

                                st.session_state.messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call.id,
                                        "name": "delete_alert",
                                        "content": results,
                                    }
                                )

                        # after getting the db results, we redo a prompt to use the info
                        continue

                    raw_answer = response_message.content
                    if raw_answer:
                        clean_answer = re.sub(r"【.*?】", "", raw_answer)
                        clean_answer = clean_answer.replace("$", r"\$")

                        # update the last message in history to be the clean version
                        st.session_state.messages[-1]["content"] = clean_answer

                        # Collapse the status box and change title to success
                        status.update(label="Done.", state="complete", expanded=False)
                        break

                    # safety break if it returns no text and no tools
                    status.update(label="Finished.", state="complete", expanded=False)
                    break

                if iteration >= MAX_ITERATIONS:
                    status.update(
                        label="Reached maximum thinking capacity.", state="error"
                    )

            except Exception as e:
                status.update(label=f"Error: {e}", state="error")
                # status.update(label="Something went wrong during processing. Please try again.", state="error")

        if clean_answer:
            st.markdown(clean_answer)
