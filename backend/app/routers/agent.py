"""
智能体路由 - 知识库选择智能体
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import httpx
from app.services.storage import knowledge_base_storage, skill_config_storage
from app.utils.logger import logger

router = APIRouter(prefix="/agent", tags=["agent"])

LLM_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"


class KBSelectionRequest(BaseModel):
    query: str = Field(..., description="用户的问题")
    selected_kb_names: Optional[List[str]] = Field(
        None, 
        description="用户选择的知识库名称列表，为空则由AI自动判断"
    )


class KnowledgeBaseInfo(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    summary: Optional[str] = None
    document_count: int = 0


class KBRecommendation(BaseModel):
    knowledge_base: KnowledgeBaseInfo
    reason: str = Field(..., description="推荐该知识库的理由")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度")


class KBSelectionResponse(BaseModel):
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


def _get_all_knowledge_bases() -> List[KnowledgeBaseInfo]:
    """获取所有知识库信息（包括摘要）"""
    kb_data = knowledge_base_storage.get_all() or {}
    knowledge_bases = []
    
    for kb_id, kb_info in kb_data.items():
        knowledge_bases.append(KnowledgeBaseInfo(
            id=kb_id,
            name=kb_info.get("name", ""),
            description=kb_info.get("description", ""),
            summary=kb_info.get("summary", ""),
            document_count=kb_info.get("document_count", 0)
        ))
    
    return knowledge_bases


def _build_kb_selection_prompt(
    query: str, 
    knowledge_bases: List[KnowledgeBaseInfo]
) -> str:
    """构建知识库选择的提示词（使用摘要）"""
    kb_list = []
    for kb in knowledge_bases:
        if kb.summary:
            kb_list.append(f"- {kb.name}:\n  摘要: {kb.summary}\n  文档数: {kb.document_count}")
        elif kb.description:
            kb_list.append(f"- {kb.name}: {kb.description}（{kb.document_count}个文档）")
        else:
            kb_list.append(f"- {kb.name}（{kb.document_count}个文档，无摘要）")
    
    kb_text = "\n".join(kb_list) if kb_list else "（当前还没有创建任何知识库）"
    
    prompt = f"""你是一个知识库选择助手。用户提出了一个问题，你需要判断应该查询哪些知识库来获取相关信息。

【重要提示】
1. 优先根据知识库的摘要（summary）来判断相关性
2. 摘要包含了知识库的主要内容和主题，能帮助你更准确地判断
3. 如果某个知识库的摘要与用户问题高度相关，应优先推荐

用户问题：{query}

可用的知识库（包含摘要信息）：
{kb_text}

请分析用户的问题，选择最相关的知识库，并给出推荐理由。

请按以下JSON格式返回结果（只返回JSON，不要有其他内容）：
{{
    "recommendations": [
        {{
            "knowledge_base_name": "知识库名称",
            "reason": "推荐该知识库的理由，请说明为什么这个知识库与问题相关",
            "confidence": 0.95
        }}
    ],
    "analysis": "对用户问题的简要分析，说明你选择了哪些知识库"
}}

注意事项：
1. 仔细阅读每个知识库的摘要，判断其与问题的相关性
2. 只推荐与问题真正相关的知识库，不要为了展示而推荐
3. confidence 表示置信度，0-1之间，越高表示越确定
4. 如果有多个知识库相关，可以推荐多个，但优先推荐最相关的
5. 如果没有知识库与问题相关，返回空的recommendations数组
6. 只需要返回JSON，不要有其他解释或文字
"""
    return prompt


@router.post("/kb-selector", response_model=KBSelectionResponse)
async def select_knowledge_bases(http_request: Request, kb_request: KBSelectionRequest):
    """知识库选择智能体 - 分析用户问题并推荐相关知识库"""
    try:
        logger.info(f"收到KB选择请求，查询参数: {kb_request.query}")
        logger.info(f"查询类型: {type(kb_request.query)}, 长度: {len(kb_request.query)}")
        logger.info(f"查询repr: {repr(kb_request.query)}")
        logger.info(f"查询字节: {kb_request.query.encode('utf-8', errors='replace')}")
        # 记录原始请求体以调试编码问题
        logger.info(f"请求头: {dict(http_request.headers)}")
        raw_body = await http_request.body()
        logger.info(f"原始请求体字节: {raw_body}")
        logger.info(f"原始请求体解码 (UTF-8): {raw_body.decode('utf-8', errors='replace')}")
        logger.info(f"原始请求体解码 (GBK): {raw_body.decode('gbk', errors='replace')}")
        
        llm_config = _get_llm_config()
        
        if not llm_config.get("api_key"):
            raise HTTPException(
                status_code=400, 
                detail="请先在 LLM 配置中设置 API Key"
            )
        
        knowledge_bases = _get_all_knowledge_bases()
        
        if not knowledge_bases:
            return {
                "code": 200,
                "message": "success",
                "data": {
                    "has_knowledge_bases": False,
                    "user_selected": False,
                    "recommendations": [],
                    "analysis": "当前还没有创建任何知识库，请先在知识库管理中创建知识库并上传文档。"
                }
            }
        
        if kb_request.selected_kb_names:
            return {
                "code": 200,
                "message": "success",
                "data": {
                    "has_knowledge_bases": True,
                    "user_selected": True,
                    "selected_kb_names": kb_request.selected_kb_names,
                    "recommendations": [],
                    "analysis": f"用户已手动选择知识库：{', '.join(kb_request.selected_kb_names)}"
                }
            }
        
        prompt = _build_kb_selection_prompt(kb_request.query, knowledge_bases)
        logger.debug(f"提示词片段（前500字符）: {prompt[:500]}")
        
        api_url = llm_config.get("api_url", LLM_API_URL)
        api_key = llm_config.get("api_key", "")
        model = llm_config.get("model", DEFAULT_MODEL)
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1000
        }
        
        logger.info(f"KB Selector: 正在分析问题 - {kb_request.query}")
        logger.debug(f"查询原始内容 - repr: {repr(kb_request.query)}, bytes: {kb_request.query.encode('utf-8', errors='replace')}")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(api_url, headers=headers, json=payload)
            
            if response.status_code != 200:
                error_detail = response.text
                logger.error(f"KB Selector LLM 调用失败: {response.status_code} - {error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"LLM 调用失败: {error_detail}"
                )
            
            result = response.json()
            assistant_content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            logger.info("KB Selector: 分析完成")
            
            import json
            try:
                selection_result = json.loads(assistant_content)
                recommendations = selection_result.get("recommendations", [])
                analysis = selection_result.get("analysis", "")
                
                matched_recommendations = []
                for rec in recommendations:
                    kb_name = rec.get("knowledge_base_name", "")
                    kb = next((k for k in knowledge_bases if k.name == kb_name), None)
                    if kb:
                        matched_recommendations.append({
                            "knowledge_base": {
                                "id": kb.id,
                                "name": kb.name,
                                "description": kb.description,
                                "summary": kb.summary,
                                "document_count": kb.document_count
                            },
                            "reason": rec.get("reason", ""),
                            "confidence": rec.get("confidence", 0.5)
                        })
                
                return {
                    "code": 200,
                    "message": "success",
                    "data": {
                        "has_knowledge_bases": len(matched_recommendations) > 0,
                        "user_selected": False,
                        "recommendations": matched_recommendations,
                        "analysis": analysis,
                        "all_knowledge_bases": [
                            {
                                "id": kb.id,
                                "name": kb.name,
                                "description": kb.description,
                                "summary": kb.summary,
                                "document_count": kb.document_count
                            }
                            for kb in knowledge_bases
                        ]
                    }
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"KB Selector: 解析LLM响应失败 - {e}")
                return {
                    "code": 200,
                    "message": "success",
                    "data": {
                        "has_knowledge_bases": False,
                        "user_selected": False,
                        "recommendations": [],
                        "analysis": "无法解析AI响应，建议您手动选择知识库。",
                        "all_knowledge_bases": [
                            {
                                "id": kb.id,
                                "name": kb.name,
                                "description": kb.description,
                                "summary": kb.summary,
                                "document_count": kb.document_count
                            }
                            for kb in knowledge_bases
                        ]
                    }
                }
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"KB Selector 处理失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"知识库选择失败: {str(e)}")
