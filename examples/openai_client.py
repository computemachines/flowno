#!/usr/bin/env python
"""
Usage:
  openai_client.py [--local | --groq]

Options:
  --local     Use local development server.
  --groq      Use Groq production API [default].

This example demonstrates using Flowno's custom event loop outside the
dataflow framework.
"""

import logging
import os

import docopt
import dotenv
from flowno import EventLoop
from flowno.core.event_loop.instrumentation import PrintInstrument
from flowno.io import HttpClient
from flowno.io.headers import Headers
from flowno.io.http_client import streaming_response_is_ok

dotenv.load_dotenv()
logger = logging.getLogger(__name__)

args = docopt.docopt(__doc__)

if args.get("--local"):
    API_URL = "http://localhost:5000/v1/chat/completions"
else:
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

TOKEN = os.environ["GROQ_API_KEY"]

headers = Headers()
headers.set("Authorization", f"Bearer {TOKEN}")


async def main():
    client = HttpClient(headers=headers)
    print("[LOG] Making request")
    response = await client.stream_post(
        API_URL,
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "Respond with 'ok'."}],
            "stream": True,
        },
    )
    print("[LOG] Started request")
    if streaming_response_is_ok(response):
        print("[LOG] Streaming and parsing results")
        async for chunk in response.body:
            print(chunk)
    else:
        print("[ERROR] Request failed")
        print(response)


def main_wrapper():
    loop = EventLoop()
    with PrintInstrument():
        loop.run_until_complete(main())


if __name__ == "__main__":
    main_wrapper()
