"""Pydantic output models as OpenAI strict-mode JSON schemas."""

from typing import Any

from pydantic import BaseModel


def schema_name(model: type[BaseModel]) -> str:
    """The `text.format.name` a model declares as `schema_name: ClassVar[str]`."""
    name = getattr(model, "schema_name", None)
    if not isinstance(name, str):
        raise TypeError(f"{model.__name__} must declare schema_name: ClassVar[str]")
    return name


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """All properties required, no extra keys, nullable as type lists, no $ref, titles, defaults."""
    schema = model.model_json_schema()
    return _strict(schema, schema.get("$defs", {}))


def _strict(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    if ref := node.get("$ref"):
        return _strict(defs[ref.rsplit("/", 1)[-1]], defs)
    if "anyOf" in node:
        return _merge_options([_strict(option, defs) for option in node["anyOf"]])
    result = {key: node[key] for key in ("type", "enum") if key in node}
    if "items" in node:
        result["items"] = _strict(node["items"], defs)
    if "properties" in node:
        result["properties"] = {
            name: _strict(prop, defs) for name, prop in node["properties"].items()
        }
        result["required"] = list(node["properties"])
        result["additionalProperties"] = False
    return result


def _merge_options(options: list[dict[str, Any]]) -> dict[str, Any]:
    """`int | None` becomes {"type": ["integer", "null"]}; richer unions stay anyOf."""
    if all(option.keys() == {"type"} for option in options):
        return {"type": [option["type"] for option in options]}
    return {"anyOf": options}
