from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from app.routers import (
    knowledge_base_router,
    document_router,
    vector_router,
    skill_router,
    system_router,
    excel_doc_router,
    chat_router,
    agent_router,
    agent_template_router,
)
from app.utils.logger import logger
from app.config import settings
from app.services.schedule_service import schedule_task


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 50)
    logger.info("个人私有文档 Skill 系统启动")
    logger.info(f"服务地址: http://{settings.host}:{settings.port}")
    logger.info("=" * 50)
    
    await schedule_task.start()
    
    yield
    
    await schedule_task.stop()
    logger.info("系统关闭")


app = FastAPI(
    title="个人私有文档 Skill 系统",
    description="100% 本地运行的个人私有文档检索系统",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://127.0.0.1:3002"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CharsetMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if "content-type" in response.headers:
            content_type = response.headers["content-type"]
            if "charset" not in content_type.lower():
                response.headers["content-type"] = content_type + "; charset=utf-8"
        return response


app.add_middleware(CharsetMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局异常: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": f"服务器错误: {str(exc)}",
            "data": None
        }
    )


app.include_router(document_router, prefix="/api")
app.include_router(vector_router, prefix="/api")
app.include_router(skill_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(excel_doc_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(agent_template_router, prefix="/api")
app.include_router(knowledge_base_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "message": "个人私有文档 Skill 系统 API",
        "version": "1.0.0",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
