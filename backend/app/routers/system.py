from fastapi import APIRouter
from app.models.skill import SystemHealth
from app.services.chroma_service import chroma_service
from app.services.storage import knowledge_base_storage, document_storage, storage
from app.utils.logger import logger

router = APIRouter(prefix="/system", tags=["system"])


def _count_excel_documents() -> int:
    """统计Excel文档数量"""
    count = 0
    for key in storage.get_all().keys():
        if key.startswith("excel_doc_"):
            count += 1
    return count


@router.get("/health", response_model=dict)
async def get_system_health():
    try:
        collections = chroma_service.list_collections()
        total_vectors = sum(
            chroma_service.get_collection_count(col) for col in collections
        )

        excel_docs_count = _count_excel_documents()
        total_docs_count = document_storage.count() + excel_docs_count

        health = SystemHealth(
            status="healthy",
            version="1.0.0",
            chroma_status="connected",
            embedding_model="BAAI/bge-large-zh-v1.5",
            knowledge_base_count=knowledge_base_storage.count(),
            total_documents=total_docs_count,
            total_vectors=total_vectors
        )

        return {
            "code": 200,
            "message": "success",
            "data": health.model_dump()
        }
    except Exception as e:
        logger.error(f"健康检查失败: {str(e)}")
        return {
            "code": 500,
            "message": "系统异常",
            "data": {
                "status": "unhealthy",
                "error": str(e)
            }
        }


@router.get("/info", response_model=dict)
async def get_system_info():
    return {
        "code": 200,
        "message": "success",
        "data": {
            "name": "个人私有文档 Skill 系统",
            "version": "1.0.0",
            "description": "100% 本地运行的个人私有文档检索系统",
            "features": [
                "本地向量数据库（Chroma）",
                "本地嵌入模型（BGE）",
                "支持 MD/TXT/PDF/DOCX 文档",
                "标准 OpenAI Function Calling 接口",
                "浏览器可视化管理"
            ]
        }
    }


@router.get("/debug/storage-keys", response_model=list)
async def get_storage_keys():
    """调试接口：获取 storage.get_all() 的所有键"""
    keys = list(storage.get_all().keys())
    logger.debug(f"Storage keys count: {len(keys)}, keys: {keys}")
    return keys