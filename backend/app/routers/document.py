from typing import List
from datetime import datetime
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from app.models.document import (
    Document,
    DocumentCreate,
    DocumentUpdate,
    DocumentResponse,
    DocumentListResponse,
    DocumentType,
)
from app.services.document_parser import document_parser
from app.services.advanced_chunker import advanced_chunker
from app.services.chroma_service import chroma_service
from app.services.storage import document_storage, knowledge_base_storage, storage
from app.utils.logger import logger

router = APIRouter(prefix="/documents", tags=["documents"])


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now()


def _get_all_documents() -> dict:
    result = {}
    for doc_id, doc_data in document_storage.get_all().items():
        result[doc_id] = Document(
            id=doc_data['id'],
            name=doc_data['name'],
            content=doc_data.get('content'),
            document_type=doc_data['document_type'],
            knowledge_base_id=doc_data['knowledge_base_id'],
            file_path=doc_data.get('file_path'),
            size=doc_data.get('size', 0),
            chunk_count=doc_data.get('chunk_count', 0),
            vector_count=doc_data.get('vector_count', 0),
            created_at=_parse_datetime(doc_data['created_at']),
            updated_at=_parse_datetime(doc_data['updated_at'])
        )
    return result


def _get_kb_ids() -> set:
    return set(knowledge_base_storage.get_all().keys())


def _update_kb(kb_id: str):
    kb_data = knowledge_base_storage.get(kb_id)
    if kb_data:
        kb_data['updated_at'] = datetime.now().isoformat()
        knowledge_base_storage.set(kb_id, kb_data)


def _get_kb_doc_count(kb_id: str) -> int:
    # 统计普通文档数量
    doc_count = sum(
        1 for doc_data in document_storage.get_all().values()
        if doc_data.get('knowledge_base_id') == kb_id
    )
    
    # 统计Excel文档数量
    excel_count = sum(
        1 for d in [storage.get(k) for k in storage.get_all().keys() if k.startswith('excel_doc_')]
        if d and d.get('knowledge_base_id') == kb_id
    )
    
    return doc_count + excel_count


@router.post("/", response_model=DocumentResponse)
async def create_document(doc_data: DocumentCreate):
    kb_ids = _get_kb_ids()
    if doc_data.knowledge_base_id not in kb_ids:
        raise HTTPException(status_code=404, detail="知识库不存在")

    doc_id = str(uuid.uuid4())
    now = datetime.now()
    doc = Document(
        id=doc_id,
        name=doc_data.name,
        content=doc_data.content,
        document_type=doc_data.document_type,
        knowledge_base_id=doc_data.knowledge_base_id,
        file_path=None,
        size=len(doc_data.content.encode('utf-8')),
        chunk_count=0,
        vector_count=0,
        created_at=now,
        updated_at=now
    )

    # 使用高级分块器（支持语义重叠、上下文增强、特殊内容保护）
    chunks = advanced_chunker.chunk_text(
        doc_data.content,
        doc_id,
        doc_data.name
    )
    doc.chunk_count = len([c for c in chunks if not c.get('is_parent', False)])  # 只统计子块

    if chunks:
        metadatas = []
        texts = []
        
        for chunk in chunks:
            metadata = {
                "document_id": chunk["document_id"],
                "document_name": chunk["document_name"],
                "chunk_index": chunk["chunk_index"],
                "total_chunks": chunk["total_chunks"],
                "is_parent": chunk.get('is_parent', False),
                "id": chunk["id"]
            }
            
            # 父子块关系
            if chunk.get('is_parent', False):
                metadata["child_ids"] = chunk.get('child_ids', [])
            else:
                metadata["parent_id"] = chunk.get('parent_id', None)
            
            metadatas.append(metadata)
            texts.append(chunk["content"])
        
        logger.info(f"准备添加 {len(chunks)} 个块（包括 {len([c for c in chunks if c.get('is_parent', False)])} 个父块）到向量库")

        success = chroma_service.add_vectors(
            collection_name=doc_data.knowledge_base_id,
            documents=texts,
            metadatas=metadatas,
            ids=[chunk["id"] for chunk in chunks]
        )

        if success:
            doc.vector_count = len(chunks)
        else:
            raise HTTPException(status_code=500, detail="向量存储失败")

    document_storage.set(doc_id, doc.model_dump())
    
    kb_data = knowledge_base_storage.get(doc_data.knowledge_base_id)
    if kb_data:
        kb_data['document_count'] = _get_kb_doc_count(doc_data.knowledge_base_id)
        kb_data['updated_at'] = now.isoformat()
        knowledge_base_storage.set(doc_data.knowledge_base_id, kb_data)

    logger.info(f"创建文档: {doc.name} (ID: {doc_id})")

    return DocumentResponse(
        code=200,
        message="文档创建成功",
        data=doc
    )


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    knowledge_base_id: str = Form(...),
    file: UploadFile = File(...)
):
    kb_ids = _get_kb_ids()
    if knowledge_base_id not in kb_ids:
        raise HTTPException(status_code=404, detail="知识库不存在")

    file_type = file.filename.split('.')[-1].lower()
    if file_type not in ['md', 'txt', 'pdf', 'docx']:
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    temp_dir = Path("./data/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / file.filename

    try:
        content = await file.read()
        temp_file.write_bytes(content)

        text_content = document_parser.parse_file(str(temp_file), file_type)
        if not text_content:
            raise HTTPException(status_code=500, detail="文档解析失败")

        doc_id = str(uuid.uuid4())
        now = datetime.now()
        doc = Document(
            id=doc_id,
            name=file.filename,
            content=text_content,
            document_type=DocumentType(file_type),
            knowledge_base_id=knowledge_base_id,
            file_path=str(temp_file),
            size=len(content),
            chunk_count=0,
            vector_count=0,
            created_at=now,
            updated_at=now
        )

        chunks = document_parser.chunk_text(text_content, doc_id, file.filename)
        doc.chunk_count = len(chunks)

        if chunks:
            metadatas = [
                {
                    "document_id": chunk["document_id"],
                    "document_name": chunk["document_name"],
                    "chunk_index": chunk["chunk_index"],
                    "total_chunks": chunk["total_chunks"]
                }
                for chunk in chunks
            ]
            texts = [chunk["text"] for chunk in chunks]

            success = chroma_service.add_vectors(
                collection_name=knowledge_base_id,
                documents=texts,
                metadatas=metadatas,
                ids=[chunk["id"] for chunk in chunks]
            )

            if success:
                doc.vector_count = len(chunks)
            else:
                raise HTTPException(status_code=500, detail="向量存储失败")

        document_storage.set(doc_id, doc.model_dump())
        
        kb_data = knowledge_base_storage.get(knowledge_base_id)
        if kb_data:
            kb_data['document_count'] = _get_kb_doc_count(knowledge_base_id)
            kb_data['updated_at'] = now.isoformat()
            knowledge_base_storage.set(knowledge_base_id, kb_data)

        logger.info(f"上传文档: {file.filename} (ID: {doc_id})")

        return DocumentResponse(
            code=200,
            message="文档上传成功",
            data=doc
        )
    finally:
        if temp_file.exists():
            temp_file.unlink()


@router.get("/knowledge-base/{kb_id}", response_model=DocumentListResponse)
async def list_documents(kb_id: str):
    kb_ids = _get_kb_ids()
    if kb_id not in kb_ids:
        raise HTTPException(status_code=404, detail="知识库不存在")

    docs_dict = _get_all_documents()
    docs = [doc for doc in docs_dict.values() if doc.knowledge_base_id == kb_id]

    return DocumentListResponse(
        code=200,
        message="success",
        data=docs,
        total=len(docs)
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str):
    docs_dict = _get_all_documents()
    if doc_id not in docs_dict:
        raise HTTPException(status_code=404, detail="文档不存在")

    return DocumentResponse(
        code=200,
        message="success",
        data=docs_dict[doc_id]
    )


@router.put("/{doc_id}", response_model=DocumentResponse)
async def update_document(doc_id: str, doc_data: DocumentUpdate):
    docs_dict = _get_all_documents()
    if doc_id not in docs_dict:
        raise HTTPException(status_code=404, detail="文档不存在")

    doc = docs_dict[doc_id]
    kb_id = doc.knowledge_base_id

    if doc_data.name is not None:
        doc.name = doc_data.name
    if doc_data.content is not None:
        old_chunks_count = doc.chunk_count

        chroma_service.delete_vectors(
            collection_name=kb_id,
            ids=[f"{doc_id}_chunk_{i}" for i in range(old_chunks_count)]
        )

        doc.content = doc_data.content
        chunks = document_parser.chunk_text(doc_data.content, doc_id, doc.name)
        doc.chunk_count = len(chunks)

        if chunks:
            metadatas = [
                {
                    "document_id": chunk["document_id"],
                    "document_name": chunk["document_name"],
                    "chunk_index": chunk["chunk_index"],
                    "total_chunks": chunk["total_chunks"]
                }
                for chunk in chunks
            ]
            texts = [chunk["text"] for chunk in chunks]

            success = chroma_service.add_vectors(
                collection_name=kb_id,
                documents=texts,
                metadatas=metadatas,
                ids=[chunk["id"] for chunk in chunks]
            )

            if success:
                doc.vector_count = len(chunks)

    doc.updated_at = datetime.now()
    document_storage.set(doc_id, doc.model_dump())
    _update_kb(kb_id)
    
    logger.info(f"更新文档: {doc.name} (ID: {doc_id})")

    return DocumentResponse(
        code=200,
        message="文档更新成功",
        data=doc
    )


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    docs_dict = _get_all_documents()
    if doc_id not in docs_dict:
        raise HTTPException(status_code=404, detail="文档不存在")

    doc = docs_dict[doc_id]
    kb_id = doc.knowledge_base_id

    chroma_service.delete_vectors(
        collection_name=kb_id,
        ids=[f"{doc_id}_chunk_{i}" for i in range(doc.chunk_count)]
    )

    document_storage.delete(doc_id)
    
    kb_data = knowledge_base_storage.get(kb_id)
    if kb_data:
        kb_data['document_count'] = _get_kb_doc_count(kb_id)
        kb_data['updated_at'] = datetime.now().isoformat()
        knowledge_base_storage.set(kb_id, kb_data)

    logger.info(f"删除文档: {doc_id}")

    return {
        "code": 200,
        "message": "文档删除成功"
    }
