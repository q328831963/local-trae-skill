from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.models.skill import (
    SkillConfig,
    SkillMetadata,
    RetrievalResult,
    RetrievalRequest,
    RetrievalResponse,
    SkillConfigResponse,
)
from app.services.rag_service import rag_service
from app.services.storage import skill_config_storage
from app.utils.logger import logger

router = APIRouter(prefix="/skill", tags=["skill"])


def _load_skill_config() -> SkillConfig:
    config_data = skill_config_storage.get("default")
    if config_data:
        return SkillConfig(
            name=config_data.get('name', 'knowledge_retrieval'),
            description=config_data.get('description', '从本地知识库中检索相关文档内容'),
            top_k=config_data.get('top_k', 5),
            similarity_threshold=config_data.get('similarity_threshold', 0.5)
        )
    return SkillConfig()


def _save_skill_config(config: SkillConfig):
    skill_config_storage.set("default", config.model_dump())


skill_config = _load_skill_config()


class UpdateSkillConfigRequest(BaseModel):
    description: Optional[str] = None
    top_k: Optional[int] = Field(None, ge=1, le=20)
    similarity_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)


@router.get("/metadata", response_model=dict)
async def get_skill_metadata():
    metadata = {
        "type": "function",
        "function": {
            "name": skill_config.name,
            "description": skill_config.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户完整问题，用于本地知识库检索"
                    },
                    "knowledge_base_name": {
                        "type": "string",
                        "description": "指定检索某个知识库，为空则全库检索"
                    },
                    "top_k": {
                        "type": "integer",
                        "default": skill_config.top_k,
                        "description": "返回结果数量"
                    }
                },
                "required": ["query"]
            }
        }
    }

    logger.info("获取 Skill 元数据")

    return {
        "code": 200,
        "message": "success",
        "data": metadata
    }


@router.post("/retrieve", response_model=RetrievalResponse)
async def retrieve_documents(request: RetrievalRequest):
    try:
        results = rag_service.retrieve(
            query=request.query,
            knowledge_base_name=request.knowledge_base_name,
            top_k=request.top_k
        )

        logger.info(f"Skill 检索完成，返回 {len(results)} 个结果")

        return RetrievalResponse(
            code=200,
            message="检索成功",
            data=results,
            total=len(results)
        )
    except Exception as e:
        logger.error(f"Skill 检索失败: {str(e)}")
        raise HTTPException(status_code=500, detail="检索失败")


@router.get("/config", response_model=SkillConfigResponse)
async def get_skill_config():
    return SkillConfigResponse(
        code=200,
        message="success",
        data=skill_config
    )


@router.put("/config", response_model=SkillConfigResponse)
async def update_skill_config(request: UpdateSkillConfigRequest):
    global skill_config
    if request.description is not None:
        skill_config.description = request.description
    if request.top_k is not None:
        skill_config.top_k = request.top_k
    if request.similarity_threshold is not None:
        skill_config.similarity_threshold = request.similarity_threshold

    _save_skill_config(skill_config)
    logger.info(f"更新 Skill 配置: {skill_config.model_dump()}")

    return SkillConfigResponse(
        code=200,
        message="配置更新成功",
        data=skill_config
    )


@router.post("/test")
async def test_skill(query: str, knowledge_base_name: Optional[str] = None, top_k: int = 5):
    try:
        results = rag_service.retrieve(
            query=query,
            knowledge_base_name=knowledge_base_name,
            top_k=top_k
        )

        return {
            "code": 200,
            "message": "测试完成",
            "data": {
                "query": query,
                "results_count": len(results),
                "results": [
                    {
                        "document_name": r.document_name,
                        "content_preview": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                        "similarity": r.similarity
                    }
                    for r in results
                ]
            }
        }
    except Exception as e:
        logger.error(f"Skill 测试失败: {str(e)}")
        raise HTTPException(status_code=500, detail="测试失败")
