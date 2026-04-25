from __future__ import annotations

import json
from typing import Any, Dict, Type, TypeVar

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def model_to_json(model: BaseModel) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json()
    return model.json()


def model_from_json(model_cls: Type[ModelT], payload: str) -> ModelT:
    if hasattr(model_cls, "model_validate_json"):
        return model_cls.model_validate_json(payload)  # type: ignore[attr-defined]
    return model_cls.parse_raw(payload)


def model_from_dict(model_cls: Type[ModelT], payload: Dict[str, Any]) -> ModelT:
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)  # type: ignore[attr-defined]
    return model_cls.parse_obj(payload)


def json_dumps(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True)

