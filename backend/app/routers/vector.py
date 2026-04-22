from typing import Optional
from fastapi import APIRouter, HTTPException
from app.services.chroma_service import chroma_service
from app.services.rag_service import rag_service
from app.services.storage import knowledge_base_storage, document_storage
from app.services.advanced_chunker import advanced_chunker
from app.utils.backup import backup_manager
from app.utils.logger import logger

router = APIRouter(prefix="/vectors", tags=["vectors"])


def _kb_exists(kb_id: str) -> bool:
    return kb_id in knowledge_base_storage.get_all()


def _get_kb_name(kb_id: str) -> Optional[str]:
    kb_data = knowledge_base_storage.get(kb_id)
    return kb_data.get('name') if kb_data else None


@router.post("/rebuild/{kb_id}")
async def rebuild_vectors(kb_id: str):
    """
    重建知识库的向量索引
    1. 清空现有向量
    2. 重新分块所有文档
    3. 重新生成并存储向量
    """
    if not _kb_exists(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    
    logger.info(f"开始重建知识库向量: {kb_id}")
    
    # Step 1: 清空现有向量
    chroma_service.reset_collection(kb_id)
    logger.info(f"清空知识库 {kb_id} 的现有向量")
    
    # Step 2: 获取该知识库下的所有文档
    all_docs = document_storage.get_all()
    kb_docs = {
        doc_id: doc_data 
        for doc_id, doc_data in all_docs.items() 
        if doc_data.get('knowledge_base_id') == kb_id
    }
    
    if not kb_docs:
        logger.info(f"知识库 {kb_id} 下没有文档，无需重建向量")
        return {
            "code": 200,
            "message": "向量重建成功，知识库中没有文档",
            "data": {
                "documents_processed": 0,
                "vectors_created": 0
            }
        }
    
    logger.info(f"找到 {len(kb_docs)} 个文档，开始重新生成向量...")
    
    # Step 3: 重新生成所有文档的向量
    total_vectors = 0
    total_chunks = 0
    
    for doc_id, doc_data in kb_docs.items():
        try:
            content = doc_data.get('content', '')
            doc_name = doc_data.get('name', '未知文档')
            
            if not content:
                logger.warning(f"文档 {doc_name} (ID: {doc_id}) 内容为空，跳过")
                continue
            
            # 使用高级分块器重新分块
            chunks = advanced_chunker.chunk_text(
                text=content,
                document_id=doc_id,
                document_name=doc_name
            )
            
            if not chunks:
                logger.warning(f"文档 {doc_name} 分块结果为空，跳过")
                continue
            
            # 准备元数据和文本
            metadatas = []
            texts = []
            
            for chunk in chunks:
                # ChromaDB 只支持简单类型：str, int, float, bool
                # 需要将复杂类型转换为字符串
                child_ids = chunk.get('child_ids', [])
                parent_id = chunk.get('parent_id')
                
                # 处理不支持的类型
                child_ids_str = ','.join(child_ids) if child_ids else ''
                parent_id_str = str(parent_id) if parent_id is not None else ''
                
                metadata = {
                    "document_id": str(chunk["document_id"]),
                    "document_name": str(chunk["document_name"]),
                    "chunk_index": int(chunk["chunk_index"]),
                    "total_chunks": int(chunk["total_chunks"]),
                    "is_parent": bool(chunk.get('is_parent', False)),
                    "id": str(chunk["id"]),
                    "child_ids_str": child_ids_str,  # list 转字符串
                    "parent_id_str": parent_id_str,  # None/str 转字符串
                }
                
                metadatas.append(metadata)
                texts.append(chunk["content"])
            
            # 添加向量
            success = chroma_service.add_vectors(
                collection_name=kb_id,
                documents=texts,
                metadatas=metadatas,
                ids=[chunk["id"] for chunk in chunks]
            )
            
            if success:
                # 更新文档的向量计数
                doc_data['chunk_count'] = len([c for c in chunks if not c.get('is_parent', False)])
                doc_data['vector_count'] = len(chunks)
                document_storage.set(doc_id, doc_data)
                
                total_vectors += len(chunks)
                total_chunks += 1
                logger.info(f"文档 {doc_name} 向量重建成功: {len(chunks)} 个块")
            else:
                logger.error(f"文档 {doc_name} 向量存储失败")
                
        except Exception as e:
            logger.error(f"处理文档 {doc_id} 时出错: {str(e)}")
            continue
    
    logger.info(f"知识库 {kb_id} 向量重建完成: 处理 {total_chunks} 个文档，生成 {total_vectors} 个向量")
    
    return {
        "code": 200,
        "message": "向量重建成功",
        "data": {
            "documents_processed": total_chunks,
            "vectors_created": total_vectors
        }
    }


@router.get("/retrieve")
async def retrieve_vectors(
    query: str,
    knowledge_base_name: Optional[str] = None,
    top_k: int = 5,
    content_length: Optional[int] = 500
):
    results = rag_service.retrieve(
        query=query,
        knowledge_base_name=knowledge_base_name,
        top_k=top_k
    )

    if content_length and content_length > 0:
        for r in results:
            if len(r.content) > content_length:
                r.content = r.content[:content_length] + "...(内容已截断)"

    return {
        "code": 200,
        "message": "检索成功",
        "data": [r.model_dump() for r in results],
        "total": len(results)
    }


@router.post("/backup/{kb_id}")
async def backup_vectors(kb_id: str):
    if not _kb_exists(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    kb_name = _get_kb_name(kb_id)
    backup_path = backup_manager.create_backup(kb_name)

    if not backup_path:
        raise HTTPException(status_code=500, detail="备份创建失败")

    return {
        "code": 200,
        "message": "备份创建成功",
        "data": {
            "backup_path": backup_path
        }
    }


@router.post("/restore/{kb_id}")
async def restore_vectors(kb_id: str, backup_path: str):
    if not _kb_exists(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    success = backup_manager.restore_backup(backup_path, kb_id)
    if not success:
        raise HTTPException(status_code=500, detail="备份还原失败")

    return {
        "code": 200,
        "message": "备份还原成功"
    }


@router.get("/backups")
async def list_backups():
    backups = backup_manager.list_backups()

    return {
        "code": 200,
        "message": "success",
        "data": backups,
        "total": len(backups)
    }


@router.delete("/backup/{backup_name}")
async def delete_backup(backup_name: str):
    backup_path = backup_manager.backup_path / backup_name
    success = backup_manager.delete_backup(str(backup_path))

    if not success:
        raise HTTPException(status_code=500, detail="删除备份失败")

    return {
        "code": 200,
        "message": "备份删除成功"
    }


@router.get("/stats/{kb_id}")
async def get_vector_stats(kb_id: str):
    if not _kb_exists(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    count = chroma_service.get_collection_count(kb_id)

    return {
        "code": 200,
        "message": "success",
        "data": {
            "knowledge_base_id": kb_id,
            "vector_count": count
        }
    }


@router.get("/document/{kb_id}/{document_id}")
async def get_document_vectors(kb_id: str, document_id: str):
    if not _kb_exists(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    kb_data = knowledge_base_storage.get(kb_id)
    kb_name = kb_data.get('name') if kb_data else None
    
    if not kb_name:
        raise HTTPException(status_code=404, detail="知识库名称未找到")

    try:
        collection = chroma_service.get_collection(kb_id)
        if not collection:
            return {
                "code": 200,
                "message": "知识库集合不存在或为空",
                "data": {
                    "document_id": document_id,
                    "vectors": [],
                    "total": 0
                }
            }

        all_data = collection.get(include=["documents", "metadatas", "embeddings"])
        
        all_ids = all_data.get("ids", [])
        all_metadatas = all_data.get("metadatas", [])
        all_documents = all_data.get("documents", [])
        all_embeddings = all_data.get("embeddings", [])
        
        vectors = []
        for i in range(len(all_ids)):
            if i >= len(all_metadatas):
                metadata = {}
            else:
                metadata = all_metadatas[i]
            
            if not isinstance(metadata, dict):
                metadata = {}
            
            if metadata.get("document_id") == document_id:
                embedding = all_embeddings[i] if i < len(all_embeddings) else None
                
                vectors.append({
                    "id": all_ids[i],
                    "content": all_documents[i] if i < len(all_documents) else "",
                    "metadata": metadata,
                    "embedding_dimension": len(embedding) if embedding is not None else 0,
                    "embedding_preview": list(embedding[:10]) if embedding is not None else []
                })

        logger.info(f"获取文档 {document_id} 的向量数据，共 {len(vectors)} 条")

        return {
            "code": 200,
            "message": "success",
            "data": {
                "document_id": document_id,
                "knowledge_base_id": kb_id,
                "knowledge_base_name": kb_name,
                "vectors": vectors,
                "total": len(vectors)
            }
        }
    except Exception as e:
        logger.error(f"获取文档向量失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取文档向量失败: {str(e)}")
