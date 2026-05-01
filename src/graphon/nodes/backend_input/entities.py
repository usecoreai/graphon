"""Backend Input node entities (method + invocation/post-fill fields, single submit)."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Self, assert_never

from pydantic import BaseModel, Field, field_validator, model_validator

from graphon.entities.base_node_data import BaseNodeData
from graphon.enums import BuiltinNodeTypes, NodeType
from graphon.nodes.human_input.entities import FormInput
from graphon.nodes.human_input.enums import PlaceholderType, TimeoutUnit


def build_backend_input_form_content_markdown(
    *,
    method_name: str,
    invocation_inputs: Sequence[FormInput],
    post_fill_inputs: Sequence[FormInput],
) -> str:
    """Markdown with `{{#$output.name#}}` placeholders for existing form UIs."""
    parts: list[str] = []
    if method_name.strip():
        parts.append(f"### {method_name.strip()}\n\n")
    for form_input in invocation_inputs:
        parts.append("{{#$output." + form_input.output_variable_name + "#}}\n\n")
    for form_input in post_fill_inputs:
        parts.append("{{#$output." + form_input.output_variable_name + "#}}\n\n")
    return "".join(parts).rstrip()


class BackendInputNodeData(BaseNodeData):
    type: NodeType = BuiltinNodeTypes.BACKEND_INPUT
    method_name: str = ""
    invocation_inputs: list[FormInput] = Field(default_factory=list)
    post_fill_inputs: list[FormInput] = Field(default_factory=list)
    timeout: int = 36
    timeout_unit: TimeoutUnit = TimeoutUnit.HOUR

    @model_validator(mode="after")
    def _validate_unique_field_names(self) -> Self:
        seen: set[str] = set()
        for form_input in self.invocation_inputs + self.post_fill_inputs:
            name = form_input.output_variable_name
            if name in seen:
                msg = f"duplicated output_variable_name '{name}' across invocation/post_fill inputs"
                raise ValueError(msg)
            seen.add(name)
        return self

    def expiration_time(self, start_time: datetime) -> datetime:
        match self.timeout_unit:
            case TimeoutUnit.HOUR:
                return start_time + timedelta(hours=self.timeout)
            case TimeoutUnit.DAY:
                return start_time + timedelta(days=self.timeout)
            case _:
                assert_never(self.timeout_unit)

    def all_form_inputs(self) -> list[FormInput]:
        return list(self.invocation_inputs) + list(self.post_fill_inputs)

    def extract_variable_selector_to_variable_mapping(
        self,
        node_id: str,
    ) -> Mapping[str, Sequence[str]]:
        variable_mappings: dict[str, Sequence[str]] = {}

        def _add_from_inputs(inputs: Sequence[FormInput]) -> None:
            for form_input in inputs:
                default_value = form_input.default
                if default_value is None:
                    continue
                if default_value.type == PlaceholderType.CONSTANT:
                    continue
                default_value_key = ".".join(default_value.selector)
                qualified_variable_mapping_key = f"{node_id}.#{default_value_key}#"
                variable_mappings[qualified_variable_mapping_key] = default_value.selector

        _add_from_inputs(self.invocation_inputs)
        _add_from_inputs(self.post_fill_inputs)
        return variable_mappings
