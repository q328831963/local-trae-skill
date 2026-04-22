"""
对话服务 - 与 LLM API 交互，同时支持私有文档 Skill
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import json
from app.services.rag_service import rag_service
from app.services.storage import skill_config_storage
from app.utils.logger import logger

router = APIRouter(prefix="/chat", tags=["chat"])

LLM_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    use_skill: bool = True
    knowledge_base_name: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2000
    stream: bool = False


class ChatResponse(BaseModel):
    code: int
    message: str
    data: Optional[Dict[str, Any]]


def _get_llm_config() -> Dict[str, Any]:
    """获取 LLM 配置"""
    config = skill_config_storage.get("llm_config")
    if not config:
        return {
            "api_url": LLM_API_URL,
            "api_key": "",
            "model": DEFAULT_MODEL
        }
    return config


def _save_llm_config(config: Dict[str, Any]):
    """保存 LLM 配置"""
    skill_config_storage.set("llm_config", config)


@router.get("/config")
async def get_chat_config():
    """获取对话配置"""
    config = _get_llm_config()
    return {
        "code": 200,
        "message": "success",
        "data": config
    }


@router.put("/config")
async def update_chat_config(
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None
):
    """更新对话配置"""
    config = _get_llm_config()
    if api_url:
        config["api_url"] = api_url
    if api_key is not None:
        config["api_key"] = api_key
    if model:
        config["model"] = model

    _save_llm_config(config)
    return {
        "code": 200,
        "message": "配置更新成功",
        "data": config
    }


@router.post("/chat")
async def chat(
    request: ChatRequest
):
    """对话接口 - 支持可选使用私有文档 Skill，支持流式响应"""
    try:
        llm_config = _get_llm_config()

        if not llm_config.get("api_key"):
            raise HTTPException(status_code=400, detail="请先配置 LLM API Key")

        messages = request.messages.copy()

        logger.info(f"聊天请求参数: use_skill={request.use_skill}, knowledge_base_name={request.knowledge_base_name}, messages_count={len(messages)}")

        if request.use_skill and len(messages) > 0:
            last_user_message = messages[-1].content if hasattr(messages[-1], 'content') else messages[-1].get('content', '')

            logger.info(f"正在检索相关文档，问题: {last_user_message}, 知识库: {request.knowledge_base_name}")

            retrieval_results = rag_service.retrieve(
                query=last_user_message,
                knowledge_base_name=request.knowledge_base_name,
                top_k=5
            )

            logger.info(f"检索结果数量: {len(retrieval_results) if retrieval_results else 0}")
            if retrieval_results:
                for i, result in enumerate(retrieval_results, 1):
                    logger.info(f"检索结果 {i}: 文档名={result.document_name}, 相似度={result.similarity:.2%}")
                context_parts = []
                context_parts.append("以下是来自私有知识库的相关文档内容：\n")

                for i, result in enumerate(retrieval_results, 1):
                    context_parts.append(f"\n【文档 {i}】{result.document_name}（相似度: {result.similarity:.2%}）")
                    context_parts.append(result.content)

                context = "\n".join(context_parts)

                # 构建参考文档列表
                doc_list = "\n".join([f"- {result.document_name}" for result in retrieval_results])

                system_message = {
                    "role": "system",
                    "content": f"""你是一个专业的技术助手。当用户提供私有文档内容时，请基于这些文档内容回答问题。

重要规则：
1. 只基于提供的文档内容回答，不要编造信息
2. 如果文档中没有相关信息，请明确告知用户
3. 在回答末尾必须标注参考了哪些文档，格式如下：
   【参考文档】
   - 文档名1
   - 文档名2
4. 如果文档内容不完整，可以合理推断但要说明是基于推断

参考文档：
{context}

请确保在回答末尾以【参考文档】为标题列出所有参考的文件名。"""
                }

                messages.insert(0, system_message)
                logger.info(f"已添加系统消息，包含 {len(retrieval_results)} 条文档作为上下文，参考文档列表: {[r.document_name for r in retrieval_results]}")
            else:
                logger.info(f"未找到相关文档，使用通用模式。知识库: {request.knowledge_base_name}, 问题: {last_user_message}")

        api_url = llm_config.get("api_url", LLM_API_URL)
        api_key = llm_config.get("api_key", "")
        model = request.model or llm_config.get("model", DEFAULT_MODEL)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": [
                {"role": m.role if hasattr(m, 'role') else m.get('role'), 
                 "content": m.content if hasattr(m, 'content') else m.get('content', '')}
                for m in messages
            ],
            "temperature": request.temperature or 0.7,
            "max_tokens": request.max_tokens or 2000
        }

        # 如果是流式请求，添加stream参数
        if request.stream:
            payload["stream"] = True
            logger.info(f"流式调用 LLM API: {api_url}")
            
            async def stream_chat_response():
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream("POST", api_url, headers=headers, json=payload) as response:
                        if response.status_code != 200:
                            error_detail = await response.aread()
                            logger.error(f"LLM API 流式调用失败: {response.status_code} - {error_detail}")
                            yield f"data: {json.dumps({'error': f'LLM API 调用失败: {error_detail}'})}\n\n"
                            return
                        
                        full_content = ""
                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line or line == "data: [DONE]":
                                continue
                            
                            if line.startswith("data: "):
                                data_str = line[6:]  # 去掉"data: "前缀
                                try:
                                    if data_str:
                                        data = json.loads(data_str)
                                        choices = data.get("choices", [])
                                        if choices:
                                            delta = choices[0].get("delta", {})
                                            content = delta.get("content", "")
                                            if content:
                                                full_content += content
                                                # 发送流式数据给客户端
                                                yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
                                except json.JSONDecodeError:
                                    logger.warning(f"无法解析流式数据: {data_str}")
                                    continue
                        
                        # 发送完整消息
                        yield f"data: {json.dumps({'type': 'complete', 'content': full_content})}\n\n"
            
            return StreamingResponse(
                stream_chat_response(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # 非流式调用（原有逻辑）
            logger.info(f"同步调用 LLM API: {api_url}")

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(api_url, headers=headers, json=payload)

                if response.status_code != 200:
                    error_detail = response.text
                    logger.error(f"LLM API 调用失败: {response.status_code} - {error_detail}")
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"LLM API 调用失败: {error_detail}"
                    )

                result = response.json()

                assistant_message = result.get("choices", [{}])[0].get("message", {})
                assistant_content = assistant_message.get("content", "")

                logger.info("LLM 响应成功")

                return {
                    "code": 200,
                    "message": "success",
                    "data": {
                        "role": "assistant",
                        "content": assistant_content,
                        "usage": result.get("usage", {})
                    }
                }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"对话处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"对话处理失败: {str(e)}")
