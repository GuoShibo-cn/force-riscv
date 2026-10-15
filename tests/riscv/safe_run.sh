#!/bin/bash
# 安全运行脚本，自动检测死循环并终止
# 用法: ./safe_run.sh <command> [args...]

set -e

# 配置参数
MAX_RUNTIME=300        # 最大运行时间 5 分钟
MAX_OUTPUT_SIZE=10485760  # 最大输出 10MB
CHECK_INTERVAL=3       # 每 3 秒检查一次
MAX_REPEATS=3          # 重复 3 次终止

if [ $# -eq 0 ]; then
    echo "用法: $0 <command> [args...]"
    echo "示例: $0 bin/friscv -t test.py --cfg config.config"
    exit 1
fi

OUTPUT_FILE=$(mktemp)
START_TIME=$(date +%s)

# 运行命令
"$@" > "$OUTPUT_FILE" 2>&1 &
PID=$!

LAST_SIZE=0
LAST_HASH=""
REPEAT_COUNT=0
NO_GROW_COUNT=0

echo "启动进程 PID=$PID，最大运行时间 ${MAX_RUNTIME}s"

while kill -0 $PID 2>/dev/null; do
    sleep $CHECK_INTERVAL
    
    # 检查运行时间
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    if [ $ELAPSED -gt $MAX_RUNTIME ]; then
        echo ""
        echo "=========================================="
        echo "ERROR: 超过最大运行时间 ${MAX_RUNTIME}s，终止进程"
        echo "=========================================="
        kill -9 $PID 2>/dev/null || true
        wait $PID 2>/dev/null || true
        echo ""
        echo "最后 50 行输出："
        tail -50 "$OUTPUT_FILE"
        rm -f "$OUTPUT_FILE"
        exit 1
    fi
    
    # 检查输出大小
    OUTPUT_SIZE=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null || echo 0)
    if [ $OUTPUT_SIZE -gt $MAX_OUTPUT_SIZE ]; then
        echo ""
        echo "=========================================="
        echo "ERROR: 输出超过 ${MAX_OUTPUT_SIZE} bytes，终止进程"
        echo "=========================================="
        kill -9 $PID 2>/dev/null || true
        wait $PID 2>/dev/null || true
        echo ""
        echo "最后 50 行输出："
        tail -50 "$OUTPUT_FILE"
        rm -f "$OUTPUT_FILE"
        exit 1
    fi
    
    # 检查文件是否增长
    if [ $OUTPUT_SIZE -eq $LAST_SIZE ]; then
        NO_GROW_COUNT=$((NO_GROW_COUNT + 1))
        if [ $NO_GROW_COUNT -ge $MAX_REPEATS ]; then
            echo ""
            echo "=========================================="
            echo "ERROR: 文件停止增长超过 $MAX_REPEATS 次，疑似进程卡死，终止进程"
            echo "=========================================="
            kill -9 $PID 2>/dev/null || true
            wait $PID 2>/dev/null || true
            echo ""
            echo "最后 50 行输出："
            tail -50 "$OUTPUT_FILE"
            rm -f "$OUTPUT_FILE"
            exit 1
        fi
    else
        NO_GROW_COUNT=0
        
        # 检查重复输出（检测死循环）
        # 使用文件开头的内容作为指纹（死循环会重复输出相同内容）
        # 只有当文件大于 1000 字节时才开始检测（避免文件增长过程中的误判）
        if [ $OUTPUT_SIZE -ge 1000 ]; then
            CURRENT_HASH=$(head -c 1000 "$OUTPUT_FILE" | md5sum | cut -d' ' -f1)
            
            if [ -n "$LAST_HASH" ] && [ "$CURRENT_HASH" = "$LAST_HASH" ]; then
                REPEAT_COUNT=$((REPEAT_COUNT + 1))
                echo "WARNING: 检测到重复输出 ($REPEAT_COUNT/$MAX_REPEATS)，已运行 ${ELAPSED}s"
                if [ $REPEAT_COUNT -ge $MAX_REPEATS ]; then
                    echo ""
                    echo "=========================================="
                    echo "ERROR: 重复输出超过 $MAX_REPEATS 次，疑似死循环，终止进程"
                    echo "=========================================="
                    kill -9 $PID 2>/dev/null || true
                    wait $PID 2>/dev/null || true
                    echo ""
                    echo "最后 50 行输出："
                    tail -50 "$OUTPUT_FILE"
                    rm -f "$OUTPUT_FILE"
                    exit 1
                fi
            else
                REPEAT_COUNT=0
                LAST_HASH="$CURRENT_HASH"
            fi
        fi
    fi
    
    LAST_SIZE=$OUTPUT_SIZE
done

wait $PID
EXIT_CODE=$?

# 输出结果
cat "$OUTPUT_FILE"
rm -f "$OUTPUT_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "SUCCESS: 命令正常完成"
    echo "=========================================="
else
    echo ""
    echo "=========================================="
    echo "FAILED: 命令退出码 $EXIT_CODE"
    echo "=========================================="
fi

exit $EXIT_CODE
