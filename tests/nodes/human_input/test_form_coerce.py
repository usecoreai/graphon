"""Tests for form submission coercion."""

import pytest

from graphon.nodes.human_input.entities import (
    FormInput,
    HumanInputSubmissionValidationError,
    coerce_backend_input_submission_values,
    coerce_form_input_submission_values,
)
from graphon.nodes.human_input.enums import FormInputType


def test_coerce_number_from_string() -> None:
    inputs = [FormInput(type=FormInputType.NUMBER, output_variable_name="n")]
    out = coerce_form_input_submission_values(inputs=inputs, form_data={"n": "42"})
    assert out == {"n": 42}


def test_coerce_number_float() -> None:
    inputs = [FormInput(type=FormInputType.NUMBER, output_variable_name="n")]
    out = coerce_form_input_submission_values(inputs=inputs, form_data={"n": "3.5"})
    assert out == {"n": 3.5}


def test_coerce_checkbox() -> None:
    inputs = [FormInput(type=FormInputType.CHECKBOX, output_variable_name="ok")]
    assert coerce_form_input_submission_values(inputs=inputs, form_data={"ok": "true"}) == {"ok": True}
    assert coerce_form_input_submission_values(inputs=inputs, form_data={"ok": "false"}) == {"ok": False}


def test_coerce_json_object() -> None:
    inputs = [FormInput(type=FormInputType.JSON, output_variable_name="j")]
    out = coerce_form_input_submission_values(inputs=inputs, form_data={"j": '{"a": 1}'})
    assert out == {"j": {"a": 1}}


def test_coerce_invalid_number_raises() -> None:
    inputs = [FormInput(type=FormInputType.NUMBER, output_variable_name="n")]
    with pytest.raises(HumanInputSubmissionValidationError):
        coerce_form_input_submission_values(inputs=inputs, form_data={"n": "x"})


def test_coerce_backend_combined() -> None:
    inv = [FormInput(type=FormInputType.TEXT_INPUT, output_variable_name="a")]
    post = [FormInput(type=FormInputType.NUMBER, output_variable_name="b")]
    out = coerce_backend_input_submission_values(
        invocation_inputs=inv,
        post_fill_inputs=post,
        form_data={"a": "hi", "b": "2"},
    )
    assert out == {"a": "hi", "b": 2}


def test_form_input_legacy_text_input_alias() -> None:
    fi = FormInput.model_validate(
        {
            "type": "text_input",
            "output_variable_name": "x",
            "default": None,
        },
    )
    assert fi.type == FormInputType.TEXT_INPUT
