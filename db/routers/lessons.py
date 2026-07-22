from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..session import get_db
from ..crud.lessons import lesson_crud
from ..models.lessons import Lesson
from ..schemas.lessons import LessonCreate, LessonRead, LessonUpdate
from services import lesson_translation_service

router = APIRouter(prefix="/lessons", tags=["lessons"])

@router.post("", response_model=LessonRead)
def create_lesson(payload: LessonCreate, db: Session = Depends(get_db)):
    return lesson_crud.create(db, payload)

@router.get("", response_model=List[LessonRead])
def list_lessons(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    status: Optional[str] = None,
    language_code: Optional[str] = None,
    hikmah_tree_id: Optional[int] = None,
    skip: int = 0,
    limit: int = Query(50, le=200),
    order_by: Optional[str] = "order_position",
    language: str = Query(
        "english",
        description="Selected display language (e.g. 'arabic', 'farsi', 'urdu', 'german', "
        "'bahasa melayu', 'french'). Defaults to English -- no translation lookup performed. "
        "NOT the same as the existing language_code filter, which selects the lesson's "
        "SOURCE language.",
    ),
):
    query = db.query(Lesson)
    if q:
        like = f"%{q}%"
        query = query.filter((Lesson.title.ilike(like)) | (Lesson.summary.ilike(like)))
    if tag:
        query = query.filter(Lesson.tags.contains([tag]))
    if status:
        query = query.filter(Lesson.status == status)
    if language_code:
        query = query.filter(Lesson.language_code == language_code)
    if hikmah_tree_id is not None:
        query = query.filter(Lesson.hikmah_tree_id == hikmah_tree_id)

    if order_by in {"order_position", "created_at", "updated_at"}:
        query = query.order_by(getattr(Lesson, order_by).asc())
    else:
        query = query.order_by(Lesson.id.asc())

    results = query.offset(skip).limit(limit).all()
    lesson_translation_service.apply_translations(
        db, "lesson", results, fields=["title", "summary"], language=language
    )
    return results

@router.get("/{lesson_id}", response_model=LessonRead)
def get_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    language: str = Query(
        "english",
        description="Selected display language (e.g. 'arabic', 'farsi', 'urdu', 'german', "
        "'bahasa melayu', 'french'). Defaults to English -- no translation lookup performed. "
        "NOT the same as the existing language_code filter, which selects the lesson's "
        "SOURCE language.",
    ),
):
    obj = lesson_crud.get(db, lesson_id)
    if not obj:
        raise HTTPException(404, "Lesson not found")
    lesson_translation_service.apply_translations(
        db, "lesson", [obj], fields=["title", "summary"], language=language
    )
    return obj

@router.patch("/{lesson_id}", response_model=LessonRead)
def update_lesson(lesson_id: int, payload: LessonUpdate, db: Session = Depends(get_db)):
    obj = lesson_crud.get(db, lesson_id)
    if not obj:
        raise HTTPException(404, "Lesson not found")
    return lesson_crud.update(db, obj, payload)

@router.delete("/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: int, db: Session = Depends(get_db)):
    obj = lesson_crud.get(db, lesson_id)
    if not obj:
        raise HTTPException(404, "Lesson not found")
    lesson_crud.delete(db, obj)
    return
