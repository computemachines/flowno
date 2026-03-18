from time import sleep

def my_sleeper(message: str):
    print("starting sleeper")
    sleep(1)
    print("done sleeping")
    print(f"message: {message}")

def main():
    thing = 1
    my_sleeper("hello")
    thing = thing + 1
    my_sleeper(str(thing))

