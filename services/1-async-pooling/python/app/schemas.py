from pydantic import BaseModel


class RecommendationItem(BaseModel):
    movie_id: int
    title: str
    predicted_rating: float


class SimilarItem(BaseModel):
    movie_id: int
    title: str
    similarity: float


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
