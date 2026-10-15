#!/bin/bash
# PTG Two-Stage Translation Stress Test Script

cd /home/guoshibo/force-riscv
source setenv.bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAFE_RUN="$SCRIPT_DIR/safe_run.sh"

echo "=========================================="
echo "PTG Two-Stage Translation Stress Test"
echo "=========================================="

PASS=0
FAIL=0
TOTAL=10

for i in $(seq 1 $TOTAL); do
    echo ""
    echo "=== Iteration $i/$TOTAL ==="
    
    # Run test with safe_run.sh (dead loop protection)
    OUTPUT=$($SAFE_RUN bin/friscv -t tests/riscv/ptg_two_stage_random_force.py --cfg config/riscv_rv64_twostage.config 2>&1)
    EXIT_CODE=$?
    
    # Check result
    if [ $EXIT_CODE -eq 0 ]; then
        if echo "$OUTPUT" | grep -q "Stress test completed"; then
            echo "✓ PASS"
            PASS=$((PASS + 1))
        else
            echo "✗ FAIL (no completion message)"
            FAIL=$((FAIL + 1))
        fi
    elif [ $EXIT_CODE -eq 1 ]; then
        if echo "$OUTPUT" | grep -q "ERROR:.*终止进程"; then
            echo "✗ FAIL (dead loop detected and terminated)"
            FAIL=$((FAIL + 1))
        else
            echo "✗ FAIL (exit code: $EXIT_CODE)"
            FAIL=$((FAIL + 1))
        fi
    else
        echo "✗ FAIL (exit code: $EXIT_CODE)"
        FAIL=$((FAIL + 1))
    fi
    
    # Show seed
    SEED=$(echo "$OUTPUT" | grep "Random seed:" | head -1)
    if [ -n "$SEED" ]; then
        echo "  $SEED"
    fi
    
    # Check for FAULT
    if echo "$OUTPUT" | grep -q "FAULT"; then
        echo "  FAULT detected:"
        echo "$OUTPUT" | grep "FAULT" | head -3 | sed 's/^/    /'
    fi
done

echo ""
echo "=========================================="
echo "Results: $PASS passed, $FAIL failed (total: $TOTAL)"
echo "=========================================="

if [ $FAIL -eq 0 ]; then
    echo "✓ All tests passed!"
    exit 0
else
    echo "✗ Some tests failed"
    exit 1
fi
