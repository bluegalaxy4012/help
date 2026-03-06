import os
import json
import requests
import re
import streamlit as st
from openai import OpenAI

DB_API_URL = os.environ.get("GRAPHQL_API_URL", "http://graphql_api:8888/graphql")
LLM_PROVIDER_API_URL = os.environ.get("LLM_PROVIDER_API_URL", "https://api.groq.com/openai/v1")
MODEL_NAME = os.environ.get("MODEL_NAME", "openai/gpt-oss-120b")
LLM_API_KEY = os.environ.get("LLM_API_KEY")

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", None)
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", None)

client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_PROVIDER_API_URL)

TOP_STOCKS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "TSM", "LLY", "V", "WMT", "JPM", "AVGO", "NVO", "JNJ"]
TOP_ETFS = ["SPY", "QQQ", "IWM", "GLD", "SLV", "USO", "UNG", "TLT", "IBIT", "ETHA", "XLF", "XLK", "XLE", "XLV", "VNQ"]
TOP_CRYPTOS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "AVAX", "DOT", "LINK", "SHIB", "BCH", "LTC", "NEAR"]


st.set_page_config(page_title="AI Trading Helper", layout="wide")
st.title("AI Trading Helper")


SYSTEM_PROMPT = f"""You are an elite quantitative analyst AI powered by the {MODEL_NAME} architecture.
You have access to a highly-secure local database via the `fetch_local_database` tool, and the live internet via your `browser_search` tool.

CRITICAL ASSET UNIVERSE & MAPPING:
Our local database ONLY tracks real-time prices and news for the following exact tickers. An example of why you should first try VT instead of VWRD.
- CRYPTO: {', '.join(TOP_CRYPTOS)}
- STOCKS: {', '.join(TOP_STOCKS)}
- ETFS: {', '.join(TOP_ETFS)}

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
        {"role": "assistant", "content": f"I am online, powered by {MODEL_NAME}. I have native web browsing and access to most recent news. What are we analyzing today?"}
    ]



# render actual previous messages
for msg in st.session_state.messages:
    if msg["role"] not in ["system", "tool"]:
        if msg.get("content"):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])


# this will be used directly by the LLM so we don't have to worry about formatting or parsing
def fetch_local_database(symbols, search_query):
    context_string = ""
    

    news_query = """query GetContext($q: String!) { askAiNews(question: $q, limit: 5) { headline, summary, url } }"""
    try:
        res = requests.post(DB_API_URL, json={"query": news_query, "variables": {"q": search_query}}, timeout=10)
        news = res.json().get("data", {}).get("askAiNews", [])
        if news:
            context_string += f"NEWS FOR '{search_query}':\n" + "\n".join([f"- {a['headline']} : {a['summary']}" for a in news]) + "\n\n"
    except Exception as e:
        context_string += f"News Error: {e}\n"

    # there may be multiple symbols mentioned
    for sym in symbols:
        sym_upper = sym.upper()
        
        if sym_upper in TOP_CRYPTOS:
            db_price_symbol = sym_upper + "USDT"
        else:
            db_price_symbol = sym_upper

        price_query = """query GetPrices($sym: String!) { getLatestPrices(symbol: $sym, limit: 5) { time, price, volume } }"""
        try:
            res = requests.post(DB_API_URL, json={"query": price_query, "variables": {"sym": db_price_symbol}})
            prices = res.json().get("data", {}).get("getLatestPrices", [])

            if prices:
                context_string += f"LAST PRICES FOR {sym}:\n" + "\n".join([f"- {p['time']} | ${p['price']} | Vol: {p['volume']}" for p in prices]) + "\n\n"
        except Exception:
            pass
            
    return context_string if context_string else "No specific data found in local DB"


# you can replace all this with your search method of choice
def browser_search(query, num_results=3):
    # first search price
    ticker = None
    url = "https://finnhub.io/api/v1/search"

    try:
        lookup = requests.get(
            url,
            params={
                "q": query.split()[0],
                "token": FINNHUB_API_KEY
            },
            timeout=5
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
                url,
                params={
                    "symbol": ticker,
                    "token": FINNHUB_API_KEY
                }
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

    payload = json.dumps({
        "q": query,
        "num": num_results,
    })

    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }


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

        print("Debug print results browser search:\n", price_info + "\n".join(results), flush=True)

        return price_info + "\n".join(results)

    except Exception as e:
        return f"Search error: {e}"



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
                    "num_results": {"type": "integer"}
                },
                "required": ["query"]
            }
        }
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
                        "description": "List of official financial tickers to fetch prices for (e.g. ['AAPL', 'MSFT', 'GLD']). Empty if no specific ticker."
                    },
                    "search_query": {
                        "type": "string",
                        "description": "A search phrase to find relevant internal news (e.g. 'Middle east oil conflict')."
                    }
                },
                "required": ["symbols", "search_query"]
            }
        }
    }
]




# main loop
if prompt := st.chat_input("Ask about macroeconomics, multiple stocks, or live news...", key="main_chat_input"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Assistant using tools..."):
            try:
                # it can use the tools over and over again
                MAX_ITERATIONS = 5
                iteration = 0
                
                while iteration < MAX_ITERATIONS:
                    iteration += 1
                    
                    response = client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=st.session_state.messages,
                        tools=TOOLS,
                        temperature=0.65
                    )
                    
                    response_message = response.choices[0].message
                    
                    # temporary, for stripping out unsupported metadata like 'executed_tools' so it doesn't crash
                    safe_msg = {
                        "role": response_message.role,
                        "content": response_message.content
                    }
                    if response_message.tool_calls:
                        safe_msg["tool_calls"] = [tc.model_dump() for tc in response_message.tool_calls]
                    
                    # save state
                    st.session_state.messages.append(safe_msg)

                    if response_message.tool_calls:
                        for tool_call in response_message.tool_calls:
                            if tool_call.function.name == "fetch_local_database":
                                args = json.loads(tool_call.function.arguments)

                                symbols_arg = args.get("symbols", [])
                                if isinstance(symbols_arg, str):
                                    symbols_arg = [symbols_arg]
                                
                                st.toast(f"Assistant requested DB fetch for: {args.get('symbols')} & '{args.get('search_query')}'")
                                db_results = fetch_local_database(symbols_arg, args.get("search_query", prompt))
                                
                                # we inject this as a message but it will not be visible since its role is "tool"
                                st.session_state.messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": tool_call.function.name,
                                    "content": db_results
                                })
                            elif tool_call.function.name == "browser_search":
                                # args will have 'query' and 'num_results' fields based on our tool definition
                                args = json.loads(tool_call.function.arguments)

                                st.toast(f"Assistant searching web for: {args.get('query')}")
                                results = browser_search(args.get("query"), args.get("num_results", 3))

                                st.session_state.messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": "browser_search",
                                    "content": results
                                })
                        
                        # after getting the db results, we redo a prompt to use the info
                        # the loop restarts here so the AI can read the injected tool messages
                        continue 
                    
                    raw_answer = response_message.content
                    if raw_answer:
                        # it sometimes hallucinates source/reference brackets and also escape $ so we don't start latex mode

                        clean_answer = re.sub(r'【.*?】', '', raw_answer)
                        clean_answer = clean_answer.replace('$', r'\$')

                        st.markdown(clean_answer)
                        
                        # update the last message in history to be the clean version so we don't give garbage back to model
                        st.session_state.messages[-1]["content"] = clean_answer
                        
                        # break the loop because we got our final text answer
                        break 
                    
                    # safety break if it returns no text and no tools
                    break 
                    
                if iteration >= MAX_ITERATIONS:
                    st.warning("Assistant reached maximum thinking capacity")
            
            except Exception as e:
                # global catch for any weird api errors, connection drops, or rate limits
                st.error(f"Something went wrong: {e}")
                # st.error(f"Something went wrong")