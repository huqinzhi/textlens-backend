"""
OCR 识别模块路由
处理图片上传和OCR文字识别相关接口
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.schemas.image import OCRResponse
from app.features.ocr.service import OCRService

router = APIRouter()


@router.post("/recognize", response_model=OCRResponse)
async def recognize_image(
    file: UploadFile = File(..., description="支持 JPG/PNG/WEBP，最大 10MB"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    图片 OCR 文字识别接口

    接收用户上传的图片，上传至 S3/R2，
    调用 Google Cloud Vision API 进行 OCR 识别，
    返回识别出的文字块列表（含坐标、置信度等信息）。

    支持格式：JPG、PNG、WEBP，单文件最大 10MB。
    识别耗时目标：< 3 秒。

    [file] 上传的图片文件
    [current_user] 当前登录用户（JWT 鉴权）
    [db] 数据库会话
    返回 OCRResponse 包含图片 ID 和识别出的文字块列表
    """
    # 验证文件类型
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}. Allowed: JPG, PNG, WEBP",
        )

    ocr_service = OCRService(db)
    return await ocr_service.recognize(file, current_user)
