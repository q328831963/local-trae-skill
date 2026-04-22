#!/bin/bash

echo "============================================"
echo "个人私有文档 Skill 系统启动脚本"
echo "============================================"

echo ""
echo "[1/4] 检查 Python 环境..."
python3 --version
if [ $? -ne 0 ]; then
    echo "错误: 未找到 Python，请先安装 Python 3.10+"
    exit 1
fi

echo ""
echo "[2/4] 安装后端依赖..."
cd backend
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "错误: 依赖安装失败"
    exit 1
fi
cd ..

echo ""
echo "[3/4] 启动后端服务..."
cd backend
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!
cd ..

echo "后端服务 PID: $BACKEND_PID"
sleep 5

echo ""
echo "[4/4] 启动前端服务..."
cd frontend
npm install
npm run dev &
FRONTEND_PID=$!
cd ..

echo "前端服务 PID: $FRONTEND_PID"

echo ""
echo "============================================"
echo "启动完成！"
echo "后端服务: http://127.0.0.1:8000"
echo "前端服务: http://localhost:3000"
echo "API 文档: http://127.0.0.1:8000/docs"
echo ""
echo "按 Ctrl+C 停止所有服务"
echo "============================================"

trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT TERM
wait
