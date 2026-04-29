from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional, Dict, Any, List
from datetime import datetime


class ChatRequest(BaseModel):
    user_query: str
    session_id: str
    language: str
    config: Optional[Dict[str, Any]] = None  # Optional agent configuration for agentic endpoint


class ElaborationRequest(BaseModel):
    selected_text: str
    context_text: str
    hikmah_tree_name: str
    lesson_name: str
    lesson_summary: str
    user_id: str = None  # Optional: If provided, memory agent will take notes


class ReferenceRequest(BaseModel):
    user_query: str


# schemas for Primers API

class PersonalizedPrimerRequest(BaseModel):
    user_id: str
    lesson_id: int
    force_refresh: bool = False
    filter: bool = False


class PersonalizedPrimerResponse(BaseModel):
    personalized_bullets: List[str]
    generated_at: Optional[datetime] = None
    from_cache: bool
    stale: bool = False
    personalized_available: bool


class BaselinePrimerResponse(BaseModel):
    lesson_id: int
    baseline_bullets: List[str]
    glossary: dict = {}
    updated_at: Optional[datetime] = None


# schemas for Hikmah page quizzes

class QuizChoiceResponse(BaseModel):
    id: int
    choice_key: str
    choice_text: str
    order_position: int


class QuizQuestionResponse(BaseModel):
    id: int
    prompt: str
    order_position: int
    choices: List[QuizChoiceResponse]
    correct_choice_id: int
    explanation: Optional[str] = None


class LessonPageQuizQuestionsResponse(BaseModel):
    lesson_content_id: int
    questions: List[QuizQuestionResponse]


class SubmitLessonPageQuizAnswerRequest(BaseModel):
    user_id: str
    question_id: int = Field(..., gt=0)
    selected_choice_id: int = Field(..., gt=0)
    answered_at: Optional[datetime] = None


class QuizSubmissionAckResponse(BaseModel):
    status: str = "received"


# Authoring CRUD schemas

class QuizChoiceWrite(BaseModel):
    choice_key: str = Field(..., min_length=1)
    choice_text: str = Field(..., min_length=1)
    order_position: int = Field(default=1, ge=1)
    is_correct: bool = False


class QuizQuestionCreateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    explanation: Optional[str] = None
    tags: Optional[List[str]] = None
    order_position: int = Field(default=1, ge=1)
    is_active: bool = True
    choices: List[QuizChoiceWrite]

    @model_validator(mode="after")
    def validate_choices(self):
        if len(self.choices) < 2:
            raise ValueError("A quiz question must include at least 2 choices")

        correct_count = sum(1 for choice in self.choices if choice.is_correct)
        if correct_count != 1:
            raise ValueError("Exactly one choice must be marked as correct")

        keys = [choice.choice_key for choice in self.choices]
        if len(set(keys)) != len(keys):
            raise ValueError("Each choice_key must be unique within a question")

        return self


class QuizQuestionPutRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    explanation: Optional[str] = None
    tags: Optional[List[str]] = None
    order_position: int = Field(default=1, ge=1)
    is_active: bool = True
    choices: List[QuizChoiceWrite]

    @model_validator(mode="after")
    def validate_choices(self):
        if len(self.choices) < 2:
            raise ValueError("A quiz question must include at least 2 choices")

        correct_count = sum(1 for choice in self.choices if choice.is_correct)
        if correct_count != 1:
            raise ValueError("Exactly one choice must be marked as correct")

        keys = [choice.choice_key for choice in self.choices]
        if len(set(keys)) != len(keys):
            raise ValueError("Each choice_key must be unique within a question")

        return self


class QuizQuestionPatchRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, min_length=1)
    explanation: Optional[str] = None
    tags: Optional[List[str]] = None
    order_position: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None


class QuizQuestionAdminResponse(QuizQuestionResponse):
    lesson_content_id: int
    tags: Optional[List[str]] = None
    is_active: bool


class LessonPageQuizQuestionsAdminResponse(BaseModel):
    lesson_content_id: int
    questions: List[QuizQuestionAdminResponse]


# schemas for Feedback API

class FeedbackRequest(BaseModel):
    rating: Literal["like", "dislike"]
    comment: Optional[str] = None
    user_query: str
    chatbot_response: str


class FeedbackResponse(BaseModel):
    ok: bool
    message: str
