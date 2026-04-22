"""
智能体模板管理路由 - 列出所有内置智能体和提示词模板
"""
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.utils.logger import logger

router = APIRouter(prefix="/agent-template", tags=["agent-template"])


class PromptTemplate(BaseModel):
    name: str = Field(..., description="提示词模板名称")
    description: str = Field(..., description="提示词模板描述")
    content: str = Field(..., description="提示词模板内容")
    variables: List[str] = Field(default_factory=list, description="提示词模板中使用的变量列表")
    version: str = Field(default="1.0", description="提示词模板版本")
    last_updated: str = Field(..., description="最后更新时间")


class Agent(BaseModel):
    id: str = Field(..., description="智能体唯一标识符")
    name: str = Field(..., description="智能体名称")
    description: str = Field(..., description="智能体功能描述")
    type: str = Field(..., description="智能体类型: selector, assistant, analyzer等")
    templates: List[PromptTemplate] = Field(..., description="该智能体使用的提示词模板列表")
    status: str = Field(default="active", description="智能体状态: active, deprecated等")
    created_at: str = Field(..., description="创建时间")


class AgentListResponse(BaseModel):
    code: int
    message: str
    data: List[Dict[str, Any]]


# 内置智能体和提示词模板定义
BUILT_IN_AGENTS = {
    "kb_selector": {
        "id": "kb_selector",
        "name": "知识库选择智能体",
        "description": "分析用户问题并智能推荐最相关的知识库，帮助用户快速找到所需信息。",
        "type": "selector",
        "status": "active",
        "created_at": "2026-04-20T10:00:00.000000",
        "templates": [
            {
                "name": "知识库选择提示词",
                "description": "用于分析用户问题并推荐相关知识库的提示词模板",
                "content": """你是一个知识库选择助手。用户提出了一个问题，你需要判断应该查询哪些知识库来获取相关信息。

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
6. 只需要返回JSON，不要有其他解释或文字""",
                "variables": ["query", "kb_text"],
                "version": "1.0",
                "last_updated": "2026-04-20T14:22:13.493068"
            }
        ]
    },
    "chat_assistant": {
        "id": "chat_assistant",
        "name": "通用对话助手",
        "description": "基于私有文档的智能对话助手，能够理解用户问题并从知识库中检索相关信息进行回答。",
        "type": "assistant",
        "status": "active",
        "created_at": "2026-04-20T10:00:00.000000",
        "templates": [
            {
                "name": "RAG系统提示词",
                "description": "用于检索增强生成的系统提示词模板，当有相关文档时使用",
                "content": """你是一个专业的技术助手。当用户提供私有文档内容时，请基于这些文档内容回答问题。

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

请确保在回答末尾以【参考文档】为标题列出所有参考的文件名。""",
                "variables": ["context"],
                "version": "1.0",
                "last_updated": "2026-04-20T14:22:13.493068"
            }
        ]
    },
    "kb_summary": {
        "id": "kb_summary",
        "name": "知识库摘要生成器",
        "description": "自动分析知识库中的文档内容，生成简洁准确的摘要，帮助用户快速了解知识库主题。",
        "type": "analyzer",
        "status": "active",
        "created_at": "2026-04-20T10:00:00.000000",
        "templates": [
            {
                "name": "知识库摘要生成提示词",
                "description": "用于从多个文档片段生成知识库摘要的提示词模板",
                "content": """你是一个专业的知识库分析助手。请根据以下文档内容，为这个知识库生成一个简洁准确的摘要。

知识库名称：{kb_name}
知识库描述：{kb_description}
文档数量：{doc_count}

文档内容片段：
{content}

请生成一个简洁的摘要，要求：
1. 长度控制在200-300字
2. 说明知识库的主要内容和主题
3. 描述知识库的用途和目标用户
4. 突出知识库的核心价值和信息密度
5. 使用简洁专业的语言，避免冗余

请按以下JSON格式返回：
{{
    "summary": "生成的摘要内容",
    "key_topics": ["主题1", "主题2", "主题3"],
    "usage_scenario": "使用场景描述"
}}""",
                "variables": ["kb_name", "kb_description", "doc_count", "content"],
                "version": "1.0",
                "last_updated": "2026-04-20T14:22:13.493068"
            }
        ]
    }
}


@router.get("/", response_model=AgentListResponse)
async def list_agent_templates():
    """
    获取所有内置智能体及其提示词模板列表
    
    Returns:
        包含所有智能体和模板信息的列表
    """
    try:
        agents = []
        for agent_id, agent_data in BUILT_IN_AGENTS.items():
            # 转换模板列表
            templates = []
            for template in agent_data.get("templates", []):
                templates.append(PromptTemplate(**template))
            
            # 构建智能体对象
            agent = Agent(
                id=agent_data["id"],
                name=agent_data["name"],
                description=agent_data["description"],
                type=agent_data["type"],
                templates=templates,
                status=agent_data.get("status", "active"),
                created_at=agent_data.get("created_at", "")
            )
            
            agents.append(agent.model_dump())
        
        return {
            "code": 200,
            "message": "success",
            "data": agents
        }
        
    except Exception as e:
        logger.error(f"获取智能体模板列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取智能体模板列表失败: {str(e)}")


@router.get("/{agent_id}", response_model=dict)
async def get_agent_template(agent_id: str):
    """
    获取指定智能体的详细信息和提示词模板
    
    Args:
        agent_id: 智能体ID
    
    Returns:
        智能体详细信息
    """
    try:
        if agent_id not in BUILT_IN_AGENTS:
            raise HTTPException(status_code=404, detail=f"智能体不存在: {agent_id}")
        
        agent_data = BUILT_IN_AGENTS[agent_id]
        templates = [
            PromptTemplate(**template) 
            for template in agent_data.get("templates", [])
        ]
        
        agent = Agent(
            id=agent_data["id"],
            name=agent_data["name"],
            description=agent_data["description"],
            type=agent_data["type"],
            templates=templates,
            status=agent_data.get("status", "active"),
            created_at=agent_data.get("created_at", "")
        )
        
        return {
            "code": 200,
            "message": "success",
            "data": agent.model_dump()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取智能体详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取智能体详情失败: {str(e)}")
