import pytest
import threading
import time
from flowno import FlowHDL, node, AsyncQueue, sleep, Stream
from flowno.core.event_loop.event_loop import EventLoop

@node(stream_in=["response_chunks"])
async def SendToGUI(response_chunks: Stream[str]):
    if response_chunks:
        async for chunk in response_chunks:
            print(f"[FlownoApp] Sending chunk to GUI: {chunk}")
            # nodejs_callback_bridge.send_message({"type": "chunk", "content": chunk})


class DummyApp:
    def __init__(self):
        self.prompt_queue = AsyncQueue[str]()
        self.f: FlowHDL | None = None

    def run(self):
        @node
        async def ReceiveUserInput():
            print("[DummyApp] Waiting for user input...")
            prompt = await self.prompt_queue.get()
            print(f"[DummyApp] Received user input: {prompt}")
            return prompt

        @node
        async def DummyInference(prompt: str):
            print(f"[DummyApp] Processing prompt: {prompt}")
            yield "thinking... "
            for word in prompt.split():
                # Simulate some processing time
                await sleep(0.1)
                yield word.capitalize()

        with FlowHDL() as f:
            f.receive_user_input = ReceiveUserInput()
            f.dummy_inference = DummyInference(f.receive_user_input)
            f.send_to_gui = SendToGUI(f.dummy_inference)

        self.f = f
        self.f.run_until_complete()

    async def enqueue_prompt(self, prompt: str):
        print(f"[DummyApp] Enqueuing prompt: {prompt}")
        await self.prompt_queue.put(prompt)

    def handle_message(self, message: str):
        print(f"[DummyApp] Received message: {message}")
        if self.f is None:
            raise RuntimeError("FlowHDL not initialized - call run() first")
        _ = self.f.create_task(
            self.enqueue_prompt(message)
        )

def test_task_removal_error():
    """Test that reproduces KeyError when removing tasks from event loop."""
    loop = EventLoop()
    app = DummyApp()
    
    # Run the flow in main thread
    main_thread = threading.Thread(target=app.run)
    main_thread.start()
    
    # Give it a moment to start
    time.sleep(0.1)
    app.handle_message("test message")
    
    # Simulate message handling from another thread
    # threading.Thread(target=app.handle_message, args=("test message",)).start()
    
    # This should trigger the KeyError when the event loop tries to remove the task
    main_thread.join()