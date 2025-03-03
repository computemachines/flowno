#!/usr/bin/env python
"""
Terminal Chat example using Flowno.

This script implements a terminal-based chat interface that streams responses
from an OpenAI-compatible API. This example is based on the tutorial at
https://flowno.net/docs/user_guide/tutorial.html.

Usage:
  terminal_chat.py [--local | --groq]

Options:
  --local     Use local development server.
  --groq      Use Groq production API [default].
"""

import logging
import os
from dataclasses import dataclass
from json import JSONEncoder
from typing import Any, Literal, Optional

import docopt
from flowno import FlowHDL, Stream, node
from flowno.core.event_loop.instrumentation import (
    LogInstrument as EventLoopLogInstrument,
)
from flowno.core.flow.instrumentation import LogInstrument as FlowLogInstrument
from flowno.io import Headers, HttpClient
from flowno.io.http_client import HTTPException, streaming_response_is_ok

# Load environment variables from .env file if available.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Parse command line arguments using the fantastic docopt library
args = docopt.docopt(__doc__)

# Set API URL based on command line option.
if args.get("--local"):
    API_URL = "http://localhost:5000/v1/chat/completions"
else:
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

# ---------------------------------------------------------------------
# HTTP Client Setup
# ---------------------------------------------------------------------


# Define the message structure.
@dataclass
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


# JSON encoder for Message objects.
class MessageJSONEncoder(JSONEncoder):
    def default(self, o: Any):
        if isinstance(o, Message):
            return {"role": o.role, "content": o.content}
        return super().default(o)


# Alias for a list of Message objects.
Messages = list[Message]

# Get the API token from environment variables.
TOKEN = os.environ["GROQ_API_KEY"]

headers = Headers()
headers.set("Authorization", f"Bearer {TOKEN}")

client = HttpClient(headers=headers)
# If you didn't use the specialized Message class, this is unnecessary
client.json_encoder = MessageJSONEncoder()

# ---------------------------------------------------------------------
# Node Definitions
# ---------------------------------------------------------------------


@node(stream_in=["response_chunks"])
async def TerminalChat(response_chunks: Optional[Stream[str]] = None) -> str:
    """
    If provided with a stream of response chunks, print them as they are
    produced, then prompt the user for input.
    """
    if response_chunks:
        async for chunk in response_chunks:
            print(chunk, end="", flush=True)
        print()  # Newline after streaming is complete.
    return input("> ")


@node
class ChatHistory:
    """
    Maintains the chat history. The initial system message seeds the conversation.
    """

    messages: Messages = [Message("system", "You are a helpful assistant.")]

    async def call(self, new_prompt: str, last_response: str = "") -> Messages:
        if last_response:
            self.messages.append(Message("assistant", last_response))
        self.messages.append(Message("user", new_prompt))
        return self.messages


@node(stream_in=["input"])
async def ChunkSentences(input: Stream[str]):
    sentence = ""
    async for word in input:
        sentence += word
        if "." in sentence:
            yield sentence
            sentence = ""


@node
async def Inference(messages: Messages):
    """
    Streams the LLM API response.
    """
    response = await client.stream_post(
        API_URL,
        json={
            "messages": messages,
            "model": "llama-3.3-70b-versatile",
            "stream": True,
        },
    )

    if not streaming_response_is_ok(response):
        logger.error("Response Body: %s", response.body)
        raise HTTPException(response.status, response.body)

    async for response_stream_json in response.body:
        try:
            choice = response_stream_json["choices"][0]
            # If finish_reason is set, skip this chunk.
            if choice.get("finish_reason"):
                continue
            # by adding a type here, the typechecker now knows Inference
            # produces a Stream[str]
            chunk: str = choice["delta"]["content"]
            yield chunk

        except KeyError:
            raise ValueError(response_stream_json)


# ---------------------------------------------------------------------
# Flow Construction and Execution
# ---------------------------------------------------------------------


def main():
    with FlowHDL() as f:
        # These statements can be put in any order
        # Notice how f.history is used before it is defined
        f.inference = Inference(f.history)
        f.terminal_chat = TerminalChat(ChunkSentences(f.inference))
        f.history = ChatHistory(f.terminal_chat, f.inference)

    # Run the flow with instrumentation for debug logging.
    with FlowLogInstrument():
        with EventLoopLogInstrument():
            f.run_until_complete()


if __name__ == "__main__":
    main()
