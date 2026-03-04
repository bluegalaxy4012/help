import os
import json
import requests
import re
import streamlit as st
from openai import OpenAI

API_URL = os.environ.get("GRAPHQL_API_URL", "http://graphql_api:8888/graphql")
LLM_API_KEY = os.environ.get("LLM_API_KEY")

# use openai client with GPT-OSS-120B for now
client = OpenAI(api_key=LLM_API_KEY, base_url="https://api.groq.com/openai/v1")

# we have info just for a few tickers in our local db for now
TICKER_MAP = {
    "apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "amazon": "AMZN",
    "gold": "GLD", "silver": "SLV", "oil": "USO", "natgas": "UNG", "cocoa": "HSY",
    "bitcoin": "IBIT", "btc": "IBIT", "ethereum": "ETHA", "eth": "ETHA", "tesla": "TSLA"
}

st.set_page_config(page_title="AI Trading Helper", layout="wide")
st.title("AI Trading Helper")


SYSTEM_PROMPT = """You are an elite quantitative analyst AI powered by the GPT-OSS-120B architecture.
You have access to a highly-secure local database via the `fetch_local_database` tool, and the live internet via your native `browser_search`.

CRITICAL FORMATTING RULES:
1. NEVER output raw citation brackets like 【4†source】 or anything similar. Weave your sources naturally into your sentences.
2. NEVER use Markdown tables to present stock prices or data. Present your analysis using professional, flowing paragraphs or clean bullet points.
3. Speak like a brilliant, articulate hedge-fund manager giving a live briefing to their team.

Always use `fetch_local_database` first to check internal prices and semantic news. If the internal data is insufficient, use your native browser tool."""


if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": "I am online, powered by OpenAI's GPT-OSS-120B. I have native web browsing and access to most recent news. What are we analyzing today?"}
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
        res = requests.post(API_URL, json={"query": news_query, "variables": {"q": search_query}})
        news = res.json().get("data", {}).get("askAiNews", [])
        if news:
            context_string += f"NEWS FOR '{search_query}':\n" + "\n".join([f"- {a['headline']} : {a['summary']}" for a in news]) + "\n\n"
    except Exception as e:
        context_string += f"News Error: {e}\n"

    # there may be multiple symbols mentioned
    for sym in symbols:
        price_query = """query GetPrices($sym: String!) { getLatestPrices(symbol: $sym, limit: 5) { time, price, volume } }"""
        try:
            res = requests.post(API_URL, json={"query": price_query, "variables": {"sym": sym}})
            prices = res.json().get("data", {}).get("getLatestPrices", [])
            if prices:
                context_string += f"LAST PRICES FOR {sym}:\n" + "\n".join([f"- {p['time']} | ${p['price']} | Vol: {p['volume']}" for p in prices]) + "\n\n"
        except Exception:
            pass
            
    return context_string if context_string else "No specific data found in local DB"


# how exactly our llm can call the function
TOOLS = [
    {"type": "browser_search"},
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
if prompt := st.chat_input("Ask about macroeconomics, multiple stocks, or live news..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Assistant loading tools..."):
            
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=st.session_state.messages,
                tools=TOOLS,
                temperature=0.65
            )
            
            response_message = response.choices[0].message
            # save the state so we can create a pop-up, just for fun
            st.session_state.messages.append(response_message.model_dump(exclude_none=True))



            if response_message.tool_calls:
                for tool_call in response_message.tool_calls:
                    if tool_call.function.name == "fetch_local_database":
                        args = json.loads(tool_call.function.arguments)
                        
                        st.toast(f"Assistant requested DB fetch for: {args.get('symbols')} & '{args.get('search_query')}'")
                        db_results = fetch_local_database(args.get("symbols", []), args.get("search_query", prompt))
                        
                        # we inject this as a message but it will not be visible since its role is "tool"
                        st.session_state.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": db_results
                        })
                
                # after getting the db results, we redo a prompt to use the info
                with st.spinner("Analyzing retrieved database context..."):
                    second_response = client.chat.completions.create(
                        model="openai/gpt-oss-120b",
                        messages=st.session_state.messages,
                        tools=[{"type": "browser_search"}],
                        temperature=0.65
                    )
                    raw_answer = second_response.choices[0].message.content
                    
                    # it sometimes hallucinates source/reference brackets
                    clean_answer = re.sub(r'【.*?】', '', raw_answer)
                    
                    st.markdown(clean_answer)
                    st.session_state.messages.append({"role": "assistant", "content": clean_answer})
            else:
                raw_answer = response_message.content
                if raw_answer:
                    clean_answer = re.sub(r'【.*?】', '', raw_answer)

                    st.markdown(clean_answer)
                    st.session_state.messages.append({"role": "assistant", "content": clean_answer})