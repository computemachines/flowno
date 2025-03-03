.. role:: python(code)
   :language: python

***************************
Tutorial: Streaming Chatbot
***************************

.. warning::

    This tutorial is a work in progress. 

Let's walk through building a chatbot that streams responses in real-time.
We'll create a simple terminal chat interface that connects to an
OpenAI-compatible API (I've tested Groq and llama.cpp). A dataflow framework is
overkill for something so simple, but the same principles apply to more complex
programs. My goal here is to show you the process of going from a vague idea to
a concrete dataflow, including the easy mistakes when building something real.


.. code-block:: text

    > Hello
    Hi! How can I assist you today?
    > How many R letters are in "strawberry"?
    There are two "r"s in the word "strawberry".
    >

.. contents:: Flowno Design Process
   :local:
   :depth: 1


Planning the Flow
=================

This is a simple enough problem that we can be confident in fully specifying
the flow just by the ordering of events in the program:

1. Accept user input from the terminal.
2. Send that input along with a chat history to an LLM API.
3. Display the AI’s response as it streams back.
4. Store the AI’s total response in the chat history.
5. Loop back to step (1).

We need to convert our crude plan into a concrete *flow*. It is tempting, from
a procedural perspective, to try to choose and order nodes based on the actions
they perform. This is the sort of *activity diagram*\ [#f1]_ you would make in
traditional no-code flowchart/workflow editors:


Naive Flow
^^^^^^^^^^

.. uml::

    @startuml
    component [Receive Input] as input <<TerminalInput>> 
    component [Print Output] as output <<TerminalOutput>>
    component [Accumulate Messages] as history <<History>> <<Stateful Node>> 
    component [LLM API] as inference <<Inference>>

    output -left-> input #red
    input -down-> history: prompt
    history -> inference: messages
    inference .up.> output: response
    inference -left-> history: response

However! Flowno only considers  explicit *data dependencies* between node when
picking the next node to execute. The :py:class:`TerminalInput` has no
explicit, direct data dependency on the :py:class:`TerminalOutput`. We *could*
add a dummy value as a dependency to ensure :py:class:`TerminalInput` runs
after :py:class:`TerminalOutput` finishes, but we have two better options.

.. admonition:: Future

   I'm considering adding an :py:meth:`.after` method to :py:class:`DraftNode`
   that would allow marking one node 'depends' on another without an actual
   data dependency.

.. _merged_node_flow:

Merged Node Flow
^^^^^^^^^^^^^^^^
Combine :py:func:`TerminalInput` and :py:class:`TerminalOutput` into a single
node, :py:func:`TerminalChat`, that handles both input and output. In the very
simplest of flows, this is the best choice. To start with, I'm going to do
this. Later on, once we have a simple proof of concept, I'll use separate nodes
but eliminate the explicit dependency between them.

.. uml::

    @startuml
    component [Print Output //then// Receive Input] as terminal <<TerminalChat>> 
    component [Accumulate Messages] as history <<History>> <<Stateful Node>> 
    component [LLM API] as inference <<Inference>>
    terminal -> history: prompt
    history -> inference: messages
    inference -> history: response
    inference ..> terminal: response
    @enduml

Independent I/O Nodes
^^^^^^^^^^^^^^^^^^^^^
If I add a GUI frontend, it would be nice to have independent I/O nodes
that send and receive messages from the frontend. This approach allows the user
to enter and submit new prompts even while the previous response is still
streaming to the GUI, without enforcing a sequential dependency.

.. uml::

    @startuml
    component [Receive Input] as input <<GUIInput>> 
    component [Print Output] as output <<GUIOutput>>
    component [Accumulate Messages] as history <<History>> <<Stateful Node>> 
    component [LLM API] as inference <<Inference>>

    input -down-> history: prompt
    history -> inference: messages
    inference .up.> output: response
    inference -left-> history: response
    @enduml

This flow eliminates the dummy dependency by having the output node simply
display whatever responses arrive, while the input node independently waits for
user prompts. 


Sketch Out the Nodes
====================

Let's start by sketching out the signatures of the :ref:`merged_node_flow`.
Later we'll revise this with the minimum default arguments to fix the
:py:exc:`MissingDefaultError` caused by the cyclic dependencies.

.. py:function:: TerminalChat(response: Stream[str])
    :async:

    :decorator: :py:deco:`~flowno.node`

    Print each chunk as it arrives, *then* call ``input("> ")``.

    :param response: The streamed response from the last interaction.
    :type response: Stream[str]
    :return: The user entered prompt.
    :rtype: str

The :py:class:`ChatHistory` node is a :ref:`Stateful Node <stateful_nodes>` so
should be a class.


.. py:class:: ChatHistory

    :decorator: :py:deco:`~flowno.node`

    .. py:attribute:: messages
        
        The accumulated message history.

        :type: Messages
        :value: [Message("system", "You are a helpful assistant.")]

    .. py:method:: call(self, prompt: str, last_response: str)
        :async:

        Under role, "assistant", append the last_response to messages and under
        role "user" append prompt. Return messages.

        .. note::
            
            It should be obvious that last_response should have a default
            value. The first time through the flow, there is no
            'last_response'. When we try to run the flow, we will see a
            :py:exc:`MissingDefaultError` that lists the last_response argument
            as one potential fix.

        :param prompt: The user entered prompt.
        :type prompt: str
        :param last_response: The response to the last prompt.
        :type last_response: str

        :rtype: Messages
        :return: The accumulated list of messages.

This class used the :py:type:`Messages` and :py:class:`Message` utility types. 


.. py:class:: Message(role: typing.Literal["system", "user", "assistant"], content: str)

        
.. py:type:: Messages
    :canonical: list[Message, ...]


.. py:function:: Inference(messages: Messages)
    :async:

    :decorator: :py:deco:`~flowno.node`
    
    Sends the chat history to a chat-completion API and stream back the
    response.

    :param messages: The list of messages.
    :type messages: :py:type:`Messages`
    :yields: The streamed text chunks from the API endpoint.
    :rtype: ~flowno.Stream[str]
    

Implementing the Nodes
======================


LLM API Node
^^^^^^^^^^^^

We are going to use an OpenAI compatible "chat completion" API. I'm using `groq
<https://groq.com/>`_, but you can use whatever or set up a local inference server
like `llama.cpp <https://github.com/ggerganov/llama.cpp>`_ if you prefer. The
:py:func:`Inference` node will send the chat history to the API and stream back
the response.

Flowno provides an async :py:class:`flowno.io.HTTPClient` class, compatible
with the flowno event loop, that replaces some of the functionality of the
blocking `requests <https://requests.readthedocs.io/en/latest/>`_ or asyncio
`aiohttp <https://docs.aiohttp.org/en/stable/>`_ libraries. The
:py:class:`~flowno.io.HTTPClient` class is designed to work with Flowno's
custom event loop. Because Flowno uses a custom event loop, and not threads or
Asyncio, any blocking calls will block the entire flow, and awaiting
incompatible asyncio primitives will do nothing.

.. admonition:: Future

   I'm considering replacing the flowno event loop with asyncio or adding
   compatibility with asyncio.

.. code-block:: python

    from flowno import node
    from flowno.io import HttpClient, Headers, streaming_response_is_ok
    from json import JSONEncoder
    import os

    API_URL = "https://api.groq.com/openai/v1/chat/completions"
    TOKEN = os.environ["GROQ_API_KEY"]

    headers = Headers()
    headers.set("Authorization", f"Bearer {TOKEN}")

    client = HttpClient(headers=headers)

    class MessageJSONEncoder(JSONEncoder):
        @override
        def default(self, o: Any):
            if isinstance(o, Message):
                return {
                    "role": o.role,
                    "content": o.content,
                }
            return super().default(o)

    client.json_encoder = MessageJSONEncoder()

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

.. admonition:: Future

   I'm going to add a fleshed out version of the inference node to the list of
   pre-built nodes.

Here are the key parts of the node:

* :python:`@node async def Inference(...):`: The :ref:`stateless node
  <stateless_nodes>` definition MUST be an :python:`async def`. The
  :py:deco:`~flowno.node` decorator transforms the function into a *node
  factory*.

.. warning::

   The :python:`async` keyword is required, even if you don't use any
   async/await features.

* The :py:meth:`HttpClient.stream_post` method initiates a POST request to the
  API. Instead of waiting for the complete response, it immediately returns an
  async generator of deserialized Server-Sent-Events. Objects passed in with the
  :python:`json=` keyword argument are serialized with
  :py:attr:`HttpClient.json_encoder`. 

* The :python:`async for` loop is the async analog of the regular :python:`for`
  loop. It awaits the next value in the async generator :python:`response`,
  possibly suspending. Control is returned when the client recieves another
  streamed chunk. 

* The :python:`yield` statement is what makes this a :ref:`Streaming Node
  <streaming_nodes>` rather than a :ref:`Mono Node<mono_nodes>`. Each time we
  receive a piece of data through our async for loop, we immediately pass it on
  to downstream nodes yielding control to the event loop, rather than waiting
  for all data to arrive first.

* If we wanted, we could return an accumulated :python:`final_result` after
  ending the stream by manually raising a :py:exc:`StopAsyncIteration`
  exception. Sadly, Python doesn't allow mixing :python:`return` and
  :python:`yield` in :py:class:`~collections.abc.AsyncGenerator` types. If you
  want to explicitly return a final value, you need to explicitly call
  :python:`raise StopAsyncIteration(return_value)`. This value will be passed
  to any connect downstream nodes that did not set
  :python:`@node(stream_in=[...])`. Instead in this example, I'm taking advantage
  of implicit accumulation of :python:`Stream[str]` values when sending the
  complete response to the downstream :py:class:`ChatHistory` node.

.. tip:: 

    Flowno will automatically accumulate string values and provide them to downstream nodes that can not accept a :python:`Stream[str]`. I'll point out this magic behavior when we make the node connections.

Terminal Chat Node
^^^^^^^^^^^^^^^^^^
Next up is the :py:func:`TerminalChat` :ref:`stateless <stateless_nodes>`, :ref:`stream-in <streaming_inputs>`, :ref:`mono <mono_nodes>` node.

.. code-block:: python

    from flowno import node

    @node(stream_in=["response_chunks"])
    async def TerminalChat(response_chunks: Stream[str]):
        async for chunk in response_chunks:
            print(chunk, end="", flush=True)
        return input("> ")

**Key points:**

1. :python:`@node(stream_in=["response_chunks"])`: By passing in
   :python:`stream_in` to the :py:deco:`~flowno.node` decorator, we say that
   this node can receive a stream of data in the given input, rather than a
   single value. If you forget this Flowno will wait until the upstream node
   (:py:func:`Inference` in this :ref:`case <merged_node_flow>`) has ended its stream and pass the full
   string to :py:func:`TerminalChat`.
2. :python:`async def TerminalOutput(response_chunks: Stream[str]):`: The argument :python:`response_chunks` is annotated with the generic type :py:class:`~flowno.Stream`. This type annotation is completely optional, but it is useful for static typechecking. :py:class:`Stream` is an :py:class:`~collections.abc.AsyncIterator` like the value of :python:`client.stream_post(...)` in the :py:class:`Inference` node body. 

.. warning::

   If you forget to use :py:deco:`~flowno.node`\ 's :python:`stream_in=[...]` argument, flowno will pass in a :py:class:`str` value instead of the desired :python:`Stream[str]`.

3. :python:`async for chunk in response_chunks:`: Like before, :python:`await` values from the async iterator. This time the iterator is a :python:`Stream[str]` type. The typechecker can infer that :python:`chunk` is a :py:class:`str`. When the connected :ref:`Streaming Node <streaming_nodes>` does not have fresh data, this :python:`async for` statement suspends until the upstream node has yielded more data.

Chat History Node
^^^^^^^^^^^^^^^^^

.. code-block:: python

    from dataclasses import dataclass
    from typing import Literal

    @dataclass
    class Message:
        role: Literal["system", "user", "assistant"]
        content: str

    @node
    class ChatHistory:
        messages = [Message("system", "You are a helpful assistant.")]

        async def call(self, prompt: str, response: str):
            self.messages.append(Message("user", prompt))
            self.messages.append(Message("assistant", response))
            return self.messages

Step 4: Designing the Flow Graph
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    with FlowHDL() as f:
        f.terminal_input = TerminalChat()

        f.history = ChatHistory(f.terminal_input, f.inference)

        f.inference = GroqInference(f.history)

        f.terminal_output = TerminalChat(f.inference)

Step 5: Handling Cycles
~~~~~~~~~~~~~~~~~~~~~~~~

If you attempt to run the flow as-is:

.. code-block:: python

    f.run_until_complete()

You will get a ``MissingDefaultError`` due to the cycle between ``ChatHistory`` and ``GroqInference``. 

Solution 1: Add a default value to ``ChatHistory``:

.. code-block:: python

    @node
    class ChatHistory:
        async def call(self, new_prompt: str, last_response: str = ""):
            ...

Solution 2: Add a default value to ``GroqInference``:

.. code-block:: python

    @node
    async def GroqInference(messages: list[Message] | None = None):
        if messages is None:
            # Handle initial run
            ...

.. rubric:: Read More

.. [#f1] https://en.wikipedia.org/wiki/Activity_diagram
