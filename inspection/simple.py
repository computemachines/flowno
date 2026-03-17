from flowno import EventLoop, sleep

async def my_sleeper(message: str):
    print("starting sleeper")
    _ = await sleep(1)
    print("done sleeping")
    print(f"message: {message}")

async def main():
    await my_sleeper("hello")

el = EventLoop()
el.run_until_complete(main())
