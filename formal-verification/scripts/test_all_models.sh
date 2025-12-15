#!/bin/bash

# Test configurations mapping
declare -A configs=(
    ["Diamond4_Mono_Ex"]="SimpleFlow"
    ["Diamond4_Mono_ConcEx"]="SimpleConcurrentFlow"
    ["EventLoopBasicEx"]="EventLoopBasicEx"
    ["EventLoopEx"]="EventLoopEx"
    ["Linear2_StreamToMono_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Linear2_Stream_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Linear2_Stream_CyclicStreamConcEx"]="CyclicConcurrentStreamingFlow"
    ["FanIn3_Mono_CyclicStreamEx"]="CyclicStreamingFlow"
    ["FanIn3_Stream_CyclicStreamEx"]="CyclicStreamingFlow"
    ["FanOut3_Mono_CyclicStreamEx"]="CyclicStreamingFlow"
    ["FanOut3_Stream_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Diamond4_Mono_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Diamond4_Stream_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Diamond4_TopStream_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Diamond4_BotStream_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Diamond4_LeftStream_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Triangle3_Mono_CyclicEx"]="CyclicMonoFlow"
    ["Triangle3_Stream_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Triangle3_Mixed_BreakMono_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Triangle3_Mixed_BreakStream_CyclicStreamEx"]="CyclicStreamingFlow"
    ["Triangle3_Mixed_BreakStream_CyclicStreamConcEx"]="CyclicConcurrentStreamingFlow"
    ["Triangle3_Mono_AlgoCyclicEx"]="AlgorithmicCyclicMonoFlow"
    ["Triangle3_Mono_CyclicConcEx"]="CyclicConcurrentMonoFlow"
    ["Triangle3_Stream_CyclicStreamConcEx"]="CyclicConcurrentStreamingFlow"
    ["Triangle3_Mono_AlgoCyclicConcEx"]="AlgorithmicCyclicConcurrentMonoFlow"
    ["Complex4_Mono_CyclicEx"]="CyclicMonoFlow"
    ["Complex4_Mono_AlgoCyclicEx"]="AlgorithmicCyclicMonoFlow"
    ["Complex4_Mono_CyclicConcEx"]="CyclicConcurrentMonoFlow"
    ["Complex4_Mono_AlgoCyclicConcEx"]="AlgorithmicCyclicConcurrentMonoFlow"
)

total=0
passed=0
failed=0

for model_file in *.tla; do
    model_name="${model_file%.tla}"
    config_name="${configs[$model_name]}"
    
    if [ -z "$config_name" ]; then
        echo "SKIP: $model_name (no config mapping)"
        continue
    fi
    
    total=$((total + 1))
    config_file="../model-tests/${config_name}.cfg"
    
    if [ ! -f "$config_file" ]; then
        echo "FAIL: $model_name - Config file not found: $config_file"
        failed=$((failed + 1))
        continue
    fi
    
    echo "Testing: $model_name with $config_name.cfg..."
    timeout 120 java -XX:+UseParallelGC -Xmx8g -cp ../../tla2tools.jar:../modules:. tlc2.TLC -workers 32 -config "$config_file" "$model_file" > /tmp/tlc_${model_name}.raw.log 2>&1
    exit_code=$?
    
    # Filter out Progress lines from the log
    grep -v "^Progress(" /tmp/tlc_${model_name}.raw.log > /tmp/tlc_${model_name}.log

    if [ $exit_code -eq 0 ]; then
        # Extract state count
        states=$(grep "distinct states found" /tmp/tlc_${model_name}.log | awk '{print $1}')
        echo "PASS: $model_name ($states states)"
        passed=$((passed + 1))
    elif [ $exit_code -eq 124 ]; then
        echo "TIMEOUT: $model_name (exceeded 120s)"
        failed=$((failed + 1))
    else
        echo "FAIL: $model_name"
        failed=$((failed + 1))
        tail -5 /tmp/tlc_${model_name}.log
    fi
done

echo ""
echo "========================================="
echo "Summary: $passed passed, $failed failed out of $total tests"
echo "========================================="
