"""
Excel 文档路由
提供 Excel 文档的 CRUD 全流程接口
"""
from typing import List, Optional, Any
from datetime import datetime
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from app.models.excel_document import (
    ExcelDocument,
    ExcelDocumentCreate,
    ExcelDocumentUpdate,
    ExcelDocumentResponse,
    ExcelDocumentListResponse,
    ChunkMode,
    ChunkConfig,
    ChunkPreviewResponse,
    ParsePreviewResponse,
)
from app.services.excel_parser import excel_parser
from app.services.excel_chunker import excel_chunker
from app.services.chroma_service import chroma_service
from app.services.storage import knowledge_base_storage, storage, document_storage
from app.utils.logger import logger

router = APIRouter(prefix="/excel-doc", tags=["excel-documents"])

EXCEL_DOC_TYPE = "excel"


def _to_metadata_value(value: Any) -> Any:
    """将值转换为 Chroma 可接受的 metadata 格式"""
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    return str(value)


def _get_excel_storage():
    return getattr(storage, '_excel_docs', {}) or {}


def _save_excel_storage(data: dict):
    for key, value in data.items():
        storage.set(f"excel_doc_{key}", value)


def _get_excel_doc(doc_id: str) -> Optional[ExcelDocument]:
    doc_data = storage.get(f"excel_doc_{doc_id}")
    if not doc_data:
        return None
    return _parse_excel_doc(doc_data)


def _parse_excel_doc(doc_data: dict) -> ExcelDocument:
    sheets = []
    for s in doc_data.get('sheets', []):
        from app.models.excel_document import SheetInfo
        sheets.append(SheetInfo(**s))

    return ExcelDocument(
        id=doc_data['id'],
        name=doc_data['name'],
        knowledge_base_id=doc_data['knowledge_base_id'],
        file_path=doc_data.get('file_path'),
        size=doc_data.get('size', 0),
        sheet_count=doc_data.get('sheet_count', 0),
        sheets=sheets,
        chunk_mode=ChunkMode(doc_data.get('chunk_mode', 'row_level')),
        chunk_count=doc_data.get('chunk_count', 0),
        vector_count=doc_data.get('vector_count', 0),
        created_at=_parse_datetime(doc_data.get('created_at')),
        updated_at=_parse_datetime(doc_data.get('updated_at'))
    )


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now()


def _get_kb_ids() -> set:
    return set(knowledge_base_storage.get_all().keys())


def _update_kb_doc_count(kb_id: str):
    kb_data = knowledge_base_storage.get(kb_id)
    if kb_data:
        # 统计Excel文档数量
        excel_count = sum(
            1 for d in [storage.get(k) for k in storage.get_all().keys() if k.startswith('excel_doc_')]
            if d and d.get('knowledge_base_id') == kb_id
        )
        
        # 统计普通文档数量
        doc_count = sum(
            1 for doc_data in (document_storage.get_all() or {}).values()
            if doc_data.get('knowledge_base_id') == kb_id
        )
        
        total = excel_count + doc_count
        logger.info(f"更新知识库文档计数: {kb_id}, Excel文档数={excel_count}, 普通文档数={doc_count}, 总计={total}")
        
        kb_data['document_count'] = total
        kb_data['updated_at'] = datetime.now().isoformat()
        success = knowledge_base_storage.set(kb_id, kb_data)
        if not success:
            logger.error(f"保存知识库文档计数失败: {kb_id}")


@router.post("/upload", response_model=ExcelDocumentResponse)
async def upload_excel(
    knowledge_base_id: str = Form(...),
    file: UploadFile = File(...)
):
    """
    上传 Excel 文件
    解析文件元数据，保存到临时目录，返回文档信息
    """
    kb_ids = _get_kb_ids()
    if knowledge_base_id not in kb_ids:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if not file.filename or not any(ext in file.filename.lower() for ext in ['.xlsx', '.xls']):
        raise HTTPException(status_code=400, detail="仅支持 xlsx/xls 格式")

    temp_dir = Path("./data/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / file.filename

    try:
        content = await file.read()
        temp_file.write_bytes(content)

        is_valid, error_msg = excel_parser.validate_file(str(temp_file))
        if not is_valid:
            temp_file.unlink()
            raise HTTPException(status_code=400, detail=f"文件验证失败: {error_msg}")

        doc_id = str(uuid.uuid4())
        now = datetime.now()
        sheets_info = excel_parser.get_sheets_info(str(temp_file))
        file_info = excel_parser.get_file_info(str(temp_file))

        doc_data = {
            'id': doc_id,
            'name': file.filename,
            'knowledge_base_id': knowledge_base_id,
            'file_path': str(temp_file),
            'size': file_info['size'],
            'sheet_count': len(sheets_info),
            'sheets': [s.model_dump() for s in sheets_info],
            'chunk_mode': 'row_level',
            'chunk_count': 0,
            'vector_count': 0,
            'created_at': now.isoformat(),
            'updated_at': now.isoformat()
        }

        storage.set(f"excel_doc_{doc_id}", doc_data)

        doc = _parse_excel_doc(doc_data)
        logger.info(f"Excel 文档上传: {file.filename} (ID: {doc_id})")

        return ExcelDocumentResponse(
            code=200,
            message="上传成功",
            data=doc
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Excel 上传失败: {str(e)}")
        if temp_file.exists():
            temp_file.unlink()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.post("/parse-preview", response_model=ParsePreviewResponse)
async def parse_preview(
    file_path: str = Form(...),
    sheet_name: Optional[str] = Form(None)
):
    """
    解析 Excel 文件，返回表格预览
    """
    is_valid, error_msg = excel_parser.validate_file(file_path)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    previews = excel_parser.get_preview(file_path, sheet_name)

    return ParsePreviewResponse(
        code=200,
        message="解析成功",
        data=previews
    )


@router.post("/chunk-preview", response_model=ChunkPreviewResponse)
async def chunk_preview(
    file_path: str = Form(...),
    chunk_mode: ChunkMode = Form(ChunkMode.ROW_LEVEL),
    sheet_name: Optional[str] = Form(None),
    semantic_threshold: float = Form(0.7),
    include_headers: bool = Form(True)
):
    """
    预览分块效果
    """
    is_valid, error_msg = excel_parser.validate_file(file_path)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    config = ChunkConfig(
        chunk_mode=chunk_mode,
        semantic_threshold=semantic_threshold,
        include_headers=include_headers
    )

    chunks = excel_chunker.preview_chunks(file_path, config, sheet_name)

    return ChunkPreviewResponse(
        code=200,
        message="分块预览成功",
        data=chunks,
        total=len(chunks)
    )


@router.post("/chunk-and-store", response_model=ExcelDocumentResponse)
async def chunk_and_store(
    doc_id: str = Form(...),
    chunk_mode: ChunkMode = Form(ChunkMode.ROW_LEVEL),
    sheet_name: Optional[str] = Form(None),
    semantic_threshold: float = Form(0.7),
    include_headers: bool = Form(True)
):
    """
    执行分块并存储到向量库
    """
    doc = _get_excel_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Excel 文档不存在")

    config = ChunkConfig(
        chunk_mode=chunk_mode,
        semantic_threshold=semantic_threshold,
        include_headers=include_headers
    )

    chunks = excel_chunker.chunk_file(
        doc.file_path, config, doc_id, doc.name, sheet_name
    )

    if not chunks:
        raise HTTPException(status_code=400, detail="分块结果为空")

    metadatas = [
        {
            "document_id": _to_metadata_value(chunk["document_id"]),
            "document_name": _to_metadata_value(chunk["document_name"]),
            "sheet_name": _to_metadata_value(chunk.get("sheet_name")),
            "chunk_index": int(chunk["chunk_index"]) if chunk.get("chunk_index") is not None else 0,
            "row_range": _to_metadata_value(chunk.get("row_range")),
            "topic": _to_metadata_value(chunk.get("topic")),
            "doc_type": EXCEL_DOC_TYPE
        }
        for chunk in chunks
    ]

    texts = [chunk["content"] for chunk in chunks]
    chunk_ids = [str(chunk["id"]) for chunk in chunks]

    success = chroma_service.add_vectors(
        collection_name=doc.knowledge_base_id,
        documents=texts,
        metadatas=metadatas,
        ids=chunk_ids
    )

    if not success:
        raise HTTPException(status_code=500, detail="向量存储失败")

    doc_data = storage.get(f"excel_doc_{doc_id}")
    doc_data['chunk_mode'] = chunk_mode.value
    doc_data['chunk_count'] = len(chunks)
    doc_data['vector_count'] = len(chunks)
    doc_data['updated_at'] = datetime.now().isoformat()
    storage.set(f"excel_doc_{doc_id}", doc_data)

    _update_kb_doc_count(doc.knowledge_base_id)

    logger.info(f"Excel 文档分块入库: {doc.name}, 向量数={len(chunks)}")

    return ExcelDocumentResponse(
        code=200,
        message="分块入库成功",
        data=_parse_excel_doc(doc_data)
    )


@router.get("/knowledge-base/{kb_id}", response_model=ExcelDocumentListResponse)
async def list_excel_documents(kb_id: str):
    """
    获取知识库下的所有 Excel 文档
    """
    kb_ids = _get_kb_ids()
    if kb_id not in kb_ids:
        raise HTTPException(status_code=404, detail="知识库不存在")

    docs = []
    for key in storage.get_all().keys():
        if key.startswith('excel_doc_'):
            doc_data = storage.get(key)
            if doc_data and doc_data.get('knowledge_base_id') == kb_id:
                docs.append(_parse_excel_doc(doc_data))

    return ExcelDocumentListResponse(
        code=200,
        message="success",
        data=docs,
        total=len(docs)
    )


@router.get("/{doc_id}", response_model=ExcelDocumentResponse)
async def get_excel_document(doc_id: str):
    """
    获取 Excel 文档详情
    """
    doc = _get_excel_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Excel 文档不存在")

    return ExcelDocumentResponse(
        code=200,
        message="success",
        data=doc
    )


@router.delete("/{doc_id}")
async def delete_excel_document(doc_id: str):
    """
    删除 Excel 文档及关联向量
    """
    doc = _get_excel_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Excel 文档不存在")

    chroma_service.delete_vectors(
        collection_name=doc.knowledge_base_id,
        ids=[f"{doc_id}_chunk_{i}" for i in range(doc.chunk_count)]
    )

    storage.delete(f"excel_doc_{doc_id}")

    if doc.file_path and Path(doc.file_path).exists():
        Path(doc.file_path).unlink()

    _update_kb_doc_count(doc.knowledge_base_id)

    logger.info(f"删除 Excel 文档: {doc_id}")

    return {
        "code": 200,
        "message": "删除成功"
    }


@router.post("/re-chunk/{doc_id}", response_model=ExcelDocumentResponse)
async def re_chunk_document(
    doc_id: str,
    chunk_mode: ChunkMode = Query(ChunkMode.ROW_LEVEL),
    sheet_name: Optional[str] = Query(None),
    semantic_threshold: float = Query(0.7),
    include_headers: bool = Query(True)
):
    """
    重新分块文档
    先删除旧向量，再重新分块入库
    """
    doc = _get_excel_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Excel 文档不存在")

    chroma_service.delete_vectors(
        collection_name=doc.knowledge_base_id,
        ids=[f"{doc_id}_chunk_{i}" for i in range(doc.chunk_count)]
    )

    config = ChunkConfig(
        chunk_mode=chunk_mode,
        semantic_threshold=semantic_threshold,
        include_headers=include_headers
    )

    chunks = excel_chunker.chunk_file(
        doc.file_path, config, doc_id, doc.name, sheet_name
    )

    if not chunks:
        raise HTTPException(status_code=400, detail="分块结果为空")

    metadatas = [
        {
            "document_id": _to_metadata_value(chunk["document_id"]),
            "document_name": _to_metadata_value(chunk["document_name"]),
            "sheet_name": _to_metadata_value(chunk.get("sheet_name")),
            "chunk_index": int(chunk["chunk_index"]) if chunk.get("chunk_index") is not None else 0,
            "row_range": _to_metadata_value(chunk.get("row_range")),
            "topic": _to_metadata_value(chunk.get("topic")),
            "doc_type": EXCEL_DOC_TYPE
        }
        for chunk in chunks
    ]

    success = chroma_service.add_vectors(
        collection_name=doc.knowledge_base_id,
        documents=[chunk["content"] for chunk in chunks],
        metadatas=metadatas,
        ids=[str(chunk["id"]) for chunk in chunks]
    )

    if not success:
        raise HTTPException(status_code=500, detail="向量存储失败")

    doc_data = storage.get(f"excel_doc_{doc_id}")
    doc_data['chunk_mode'] = chunk_mode.value
    doc_data['chunk_count'] = len(chunks)
    doc_data['vector_count'] = len(chunks)
    doc_data['updated_at'] = datetime.now().isoformat()
    storage.set(f"excel_doc_{doc_id}", doc_data)

    logger.info(f"Excel 文档重新分块: {doc.name}, 新向量数={len(chunks)}")

    return ExcelDocumentResponse(
        code=200,
        message="重新分块成功",
        data=_parse_excel_doc(doc_data)
    )
