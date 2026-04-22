#!/bin/bash

set -e

echo "============================================"
echo "BGE 模型下载脚本"
echo "============================================"
echo

MODEL_DIR="$(pwd)/models/bge-large-zh-v1.5"
echo "模型将下载到: $MODEL_DIR"
echo

if [ ! -d "$MODEL_DIR" ]; then
    mkdir -p "$MODEL_DIR"
fi

echo "正在下载模型文件..."
echo

echo "[1/8] 下载 config.json..."
curl -L "https://huggingface.co/BAAI/bge-large-zh-v1.5/resolve/main/config.json" -o "$MODEL_DIR/config.json"

echo
echo "[2/8] 下载 config_sentence_transformers.json..."
curl -L "https://huggingface.co/BAAI/bge-large-zh-v1.5/resolve/main/config_sentence_transformers.json" -o "$MODEL_DIR/config_sentence_transformers.json"

echo
echo "[3/8] 下载 model.safetensors (约 1.2GB，请耐心等待)..."
curl -L "https://huggingface.co/BAAI/bge-large-zh-v1.5/resolve/main/model.safetensors" -o "$MODEL_DIR/model.safetensors"

echo
echo "[4/8] 下载 tokenizer.json..."
curl -L "https://huggingface.co/BAAI/bge-large-zh-v1.5/resolve/main/tokenizer.json" -o "$MODEL_DIR/tokenizer.json"

echo
echo "[5/8] 下载 tokenizer_config.json..."
curl -L "https://huggingface.co/BAAI/bge-large-zh-v1.5/resolve/main/tokenizer_config.json" -o "$MODEL_DIR/tokenizer_config.json"

echo
echo "[6/8] 下载 special_tokens_map.json..."
curl -L "https://huggingface.co/BAAI/bge-large-zh-v1.5/resolve/main/special_tokens_map.json" -o "$MODEL_DIR/special_tokens_map.json"

echo
echo "[7/8] 下载 vocab.txt..."
curl -L "https://huggingface.co/BAAI/bge-large-zh-v1.5/resolve/main/vocab.txt" -o "$MODEL_DIR/vocab.txt"

echo
echo "[8/8] 下载 modeling.py..."
curl -L "https://huggingface.co/BAAI/bge-large-zh-v1.5/resolve/main/modeling.py" -o "$MODEL_DIR/modeling.py"

echo
echo "============================================"
echo "模型下载完成！"
echo "============================================"
echo
echo "检查下载的文件..."
ls -la "$MODEL_DIR"
echo
echo "下一步："
echo "1. 修改 .env 中的 EMBEDDING_MODEL 为本地路径"
echo "2. 重启后端服务"
echo