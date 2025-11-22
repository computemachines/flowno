#!/usr/bin/env python3
"""Analyze the consumer behavior during the hang."""

import subprocess
import sys

# Run the test and capture output
result = subprocess.run(
    ["uv", "run", "pytest", "tests/test_streaming.py::test_stream_multiple_chunks_delayed_consumption",
     "-v", "--timeout=5", "-s"],
    capture_output=True,
    text=True,
    timeout=10
)

output = result.stdout + result.stderr

# Track what each consumer saw
consumer1_consumptions = []
consumer2_consumptions = []
consumer1_generations = []
consumer2_generations = []

for line in output.split('\n'):
    if 'Consumer1#0.input(0), last_consumed=' in line and 'consumed data' in line:
        # Extract generation and data
        if 'last_consumed=(' in line:
            gen_start = line.find('last_consumed=(') + len('last_consumed=(')
            gen_end = line.find(')', gen_start)
            generation = line[gen_start:gen_end]

            data_start = line.find("consumed data '") + len("consumed data '")
            data_end = line.find("'", data_start)
            data = line[data_start:data_end]

            consumer1_consumptions.append((generation, data))

    elif 'Consumer2#0.input(0), last_consumed=' in line and 'consumed data' in line:
        if 'last_consumed=(' in line:
            gen_start = line.find('last_consumed=(') + len('last_consumed=(')
            gen_end = line.find(')', gen_start)
            generation = line[gen_start:gen_end]

            data_start = line.find("consumed data '") + len("consumed data '")
            data_end = line.find("'", data_start)
            data = line[data_start:data_end]

            consumer2_consumptions.append((generation, data))

    elif 'Consumer1#0 advanced to generation' in line:
        gen_start = line.find('generation (') + len('generation (')
        gen_end = line.find(')', gen_start)
        generation = line[gen_start:gen_end]
        consumer1_generations.append(generation)

    elif 'Consumer2#0 advanced to generation' in line:
        gen_start = line.find('generation (') + len('generation (')
        gen_end = line.find(')', gen_start)
        generation = line[gen_start:gen_end]
        consumer2_generations.append(generation)

print("=" * 70)
print("CONSUMER1 STREAM CONSUMPTIONS:")
print("=" * 70)
for i, (gen, data) in enumerate(consumer1_consumptions, 1):
    print(f"{i}. Generation ({gen}): '{data}'")

print(f"\nTotal stream values consumed: {len(consumer1_consumptions)}")

print("\n" + "=" * 70)
print("CONSUMER1 RUN-LEVEL-0 COMPLETIONS:")
print("=" * 70)
for i, gen in enumerate(consumer1_generations, 1):
    print(f"{i}. Advanced to generation ({gen})")

print(f"\nTotal times run: {len(consumer1_generations)}")

print("\n" + "=" * 70)
print("CONSUMER2 STREAM CONSUMPTIONS:")
print("=" * 70)
for i, (gen, data) in enumerate(consumer2_consumptions, 1):
    print(f"{i}. Generation ({gen}): '{data}'")

print(f"\nTotal stream values consumed: {len(consumer2_consumptions)}")

print("\n" + "=" * 70)
print("CONSUMER2 RUN-LEVEL-0 COMPLETIONS:")
print("=" * 70)
for i, gen in enumerate(consumer2_generations, 1):
    print(f"{i}. Advanced to generation ({gen})")

print(f"\nTotal times run: {len(consumer2_generations)}")
