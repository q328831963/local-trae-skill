from typing import List
from datetime import datetime
import uuid
from fastapi import APIRouter, HTTPException
from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
)
from app.services.chroma_service import chroma_service
from app.services.storage import knowledge_base_storage, document_storage, storage
from app.services.kb_summary_service import (
    generate_kb_summary,
    update_kb_summary,
    regenerate_all_summaries,
    get_kb_summary_info
)
from app.utils.logger import logger

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now()


def _get_kb_doc_count(kb_id: str) -> int:
    """获取知识库文档总数（普通文档 + Excel文档）"""
    # 统计普通文档数量
    doc_count = sum(
        1 for doc_data in (document_storage.get_all() or {}).values()
        if doc_data.get('knowledge_base_id') == kb_id
    )
    
    # 统计Excel文档数量
    excel_count = sum(
        1 for d in [storage.get(k) for k in storage.get_all().keys() if k.startswith('excel_doc_')]
        if d and d.get('knowledge_base_id') == kb_id
    )
    
    return doc_count + excel_count


def _get_all_knowledge_bases() -> dict:
    result = {}
    for kb_id, kb_data in knowledge_base_storage.get_all().items():
        result[kb_id] = KnowledgeBase(
            id=kb_data['id'],
            name=kb_data['name'],
            description=kb_data.get('description'),
            document_count=kb_data.get('document_count', 0),
            vector_count=kb_data.get('vector_count', 0),
            summary=kb_data.get('summary'),
            summary_updated_at=_parse_datetime(kb_data.get('summary_updated_at')) if kb_data.get('summary_updated_at') else None,
            created_at=_parse_datetime(kb_data['created_at']),
            updated_at=_parse_datetime(kb_data['updated_at'])
        )
    return result


@router.post("/", response_model=KnowledgeBaseResponse)
async def create_knowledge_base(kb_data: KnowledgeBaseCreate):
    kb_id = str(uuid.uuid4())
    now = datetime.now()
    kb = KnowledgeBase(
        id=kb_id,
        name=kb_data.name,
        description=kb_data.description,
        document_count=0,
        vector_count=0,
        created_at=now,
        updated_at=now
    )

    success = chroma_service.create_collection(kb_id)
    if not success:
        raise HTTPException(status_code=500, detail="创建 Chroma 集合失败")

    knowledge_base_storage.set(kb_id, kb.model_dump())
    logger.info(f"创建知识库: {kb.name} (ID: {kb_id})")

    return KnowledgeBaseResponse(
        code=200,
        message="知识库创建成功",
        data=kb
    )


@router.get("/", response_model=dict)
async def list_knowledge_bases():
    kbs_dict = _get_all_knowledge_bases()
    kbs = list(kbs_dict.values())
    return {
        "code": 200,
        "message": "success",
        "data": [
            {
                **kb.model_dump(),
                "document_count": _get_kb_doc_count(kb.id),
                "vector_count": chroma_service.get_collection_count(kb.id)
            }
            for kb in kbs
        ],
        "total": len(kbs)
    }


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(kb_id: str):
    kbs_dict = _get_all_knowledge_bases()
    if kb_id not in kbs_dict:
        raise HTTPException(status_code=404, detail="知识库不存在")

    kb = kbs_dict[kb_id]
    vector_count = chroma_service.get_collection_count(kb_id)

    # 从kb.model_dump()创建字典，更新document_count和vector_count
    kb_dict = kb.model_dump()
    # 移除可能已存在的字段，避免重复
    kb_dict.pop('document_count', None)
    kb_dict.pop('vector_count', None)
    # 设置新的值
    kb_dict["document_count"] = _get_kb_doc_count(kb_id)
    kb_dict["vector_count"] = vector_count
    
    return KnowledgeBaseResponse(
        code=200,
        message="success",
        data=KnowledgeBase(**kb_dict)
    )


@router.put("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(kb_id: str, kb_data: KnowledgeBaseUpdate):
    kbs_dict = _get_all_knowledge_bases()
    if kb_id not in kbs_dict:
        raise HTTPException(status_code=404, detail="知识库不存在")

    kb = kbs_dict[kb_id]
    if kb_data.name is not None:
        kb.name = kb_data.name
    if kb_data.description is not None:
        kb.description = kb_data.description
    kb.updated_at = datetime.now()

    knowledge_base_storage.set(kb_id, kb.model_dump())
    logger.info(f"更新知识库: {kb.name} (ID: {kb_id})")

    return KnowledgeBaseResponse(
        code=200,
        message="知识库更新成功",
        data=kb
    )


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: str):
    kbs_dict = _get_all_knowledge_bases()
    if kb_id not in kbs_dict:
        raise HTTPException(status_code=404, detail="知识库不存在")

    success = chroma_service.delete_collection(kb_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除 Chroma 集合失败")

    knowledge_base_storage.delete(kb_id)
    logger.info(f"删除知识库: {kb_id}")

    return {
        "code": 200,
        "message": "知识库删除成功"
    }


@router.post("/{kb_id}/summary/generate")
async def generate_summary(kb_id: str):
    """为指定知识库生成摘要"""
    kbs_dict = _get_all_knowledge_bases()
    if kb_id not in kbs_dict:
        raise HTTPException(status_code=404, detail="知识库不存在")
    
    kb = kbs_dict[kb_id]
    
    summary_data = await generate_kb_summary(kb_id)
    
    if not summary_data:
        raise HTTPException(
            status_code=500, 
            detail="摘要生成失败，请检查是否已配置 LLM API Key"
        )
    
    update_kb_summary(kb_id, summary_data)
    
    return {
        "code": 200,
        "message": "摘要生成成功",
        "data": {
            "kb_id": kb_id,
            "kb_name": kb.name,
            "summary": summary_data.get("summary", ""),
            "topics": summary_data.get("topics", []),
            "key_content": summary_data.get("key_content", ""),
            "document_count": summary_data.get("document_count", 0)
        }
    }


@router.get("/{kb_id}/summary")
async def get_summary(kb_id: str):
    """获取知识库的摘要信息"""
    kbs_dict = _get_all_knowledge_bases()
    if kb_id not in kbs_dict:
        raise HTTPException(status_code=404, detail="知识库不存在")
    
    kb = kbs_dict[kb_id]
    
    return {
        "code": 200,
        "message": "success",
        "data": {
            "kb_id": kb_id,
            "kb_name": kb.name,
            "summary": kb.summary,
            "summary_updated_at": kb.summary_updated_at,
            "has_summary": bool(kb.summary)
        }
    }


@router.post("/summaries/regenerate-all")
async def regenerate_all():
    """重新生成所有知识库的摘要"""
    results = await regenerate_all_summaries()
    
    return {
        "code": 200,
        "message": f"批量生成完成 - 成功: {results['success']}, 失败: {results['failed']}",
        "data": results
    }
