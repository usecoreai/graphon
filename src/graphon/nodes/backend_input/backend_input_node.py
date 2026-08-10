from __future__ import annotations

import logging
from collections.abc import Generator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, override

from graphon.entities.graph_init_params import GraphInitParams
from graphon.entities.pause_reason import BackendInputRequired
from graphon.enums import (
    BuiltinNodeTypes,
    NodeExecutionType,
    WorkflowNodeExecutionStatus,
)
from graphon.node_events.base import NodeEventBase, NodeRunResult
from graphon.node_events.node import (
    BackendInputFormFilledEvent,
    BackendInputFormTimeoutEvent,
    PauseRequestedEvent,
    StreamCompletedEvent,
)
from graphon.nodes.base.node import Node
from graphon.nodes.human_input.human_input_node import HumanInputNode
from graphon.nodes.human_input.enums import HumanInputFormStatus, PlaceholderType
from graphon.nodes.runtime import (
    HumanInputFormStateProtocol,
    HumanInputNodeRuntimeProtocol,
)
from graphon.runtime.graph_runtime_state import GraphRuntimeState
from graphon.workflow_type_encoder import WorkflowRuntimeTypeConverter

from .constants import BACKEND_INPUT_SUBMIT_ACTION_ID
from .entities import BackendInputNodeData, build_backend_input_form_content_markdown

logger = logging.getLogger(__name__)


class BackendInputNode(Node[BackendInputNodeData]):
    node_type = BuiltinNodeTypes.BACKEND_INPUT
    execution_type = NodeExecutionType.BRANCH

    _TIMEOUT_HANDLE = "__timeout"

    _node_data: BackendInputNodeData

    @override
    def __init__(
        self,
        node_id: str,
        config: BackendInputNodeData,
        *,
        graph_init_params: GraphInitParams,
        graph_runtime_state: GraphRuntimeState,
        runtime: HumanInputNodeRuntimeProtocol,
        form_repository: object | None = None,
    ) -> None:
        super().__init__(
            node_id=node_id,
            config=config,
            graph_init_params=graph_init_params,
            graph_runtime_state=graph_runtime_state,
        )
        if form_repository is not None:
            with_form_repository = getattr(
                runtime,
                "with_form_repository",
                None,
            )
            if callable(with_form_repository):
                updated_runtime = with_form_repository(form_repository)
                if not isinstance(updated_runtime, HumanInputNodeRuntimeProtocol):
                    msg = "with_form_repository() must return a HumanInput runtime"
                    raise TypeError(msg)
                runtime = updated_runtime
        self._runtime: HumanInputNodeRuntimeProtocol = runtime

    @classmethod
    @override
    def version(cls) -> str:
        return "1"

    def resolve_default_values(self) -> Mapping[str, Any]:
        variable_pool = self.graph_runtime_state.variable_pool
        resolved_defaults: dict[str, Any] = {}
        for form_input in self._node_data.all_form_inputs():
            if (default_value := form_input.default) is None:
                continue
            if default_value.type == PlaceholderType.CONSTANT:
                continue
            resolved_value = variable_pool.get(default_value.selector)
            if resolved_value is None:
                continue
            resolved_defaults[form_input.output_variable_name] = (
                WorkflowRuntimeTypeConverter().value_to_json_encodable_recursive(
                    resolved_value.value,
                )
            )
        return resolved_defaults

    def _render_markdown_before_submission(self) -> str:
        raw = build_backend_input_form_content_markdown(
            method_name=self._node_data.method_name,
            invocation_inputs=self._node_data.invocation_inputs,
            post_fill_inputs=self._node_data.post_fill_inputs,
        )
        rendered = self.graph_runtime_state.variable_pool.convert_template(raw)
        return rendered.markdown

    def _backend_input_required_event(
        self,
        form_entity: HumanInputFormStateProtocol,
    ) -> BackendInputRequired:
        node_data = self._node_data
        return BackendInputRequired(
            form_id=form_entity.id,
            method_name=node_data.method_name,
            invocation_inputs=list(node_data.invocation_inputs),
            post_fill_inputs=list(node_data.post_fill_inputs),
            node_id=self.id,
            node_title=node_data.title,
            resolved_default_values=dict(self.resolve_default_values()),
        )

    def _form_to_pause_event(
        self,
        form_entity: HumanInputFormStateProtocol,
    ) -> PauseRequestedEvent:
        return PauseRequestedEvent(reason=self._backend_input_required_event(form_entity))

    @override
    def _run(self) -> Generator[NodeEventBase, None, None]:
        form = self._runtime.get_form(node_id=self.id)
        if form is None:
            form_entity = self._runtime.create_form(
                node_id=self.id,
                node_data=self._node_data,
                rendered_content=self._render_markdown_before_submission(),
                resolved_default_values=self.resolve_default_values(),
            )
            logger.info(
                "Backend Input node suspended workflow for form. node_id=%s, form_id=%s",
                self.id,
                form_entity.id,
            )
            yield self._form_to_pause_event(form_entity)
            return

        if form.status in frozenset((
            HumanInputFormStatus.TIMEOUT,
            HumanInputFormStatus.EXPIRED,
        )) or form.expiration_time <= datetime.now(UTC).replace(tzinfo=None):
            yield BackendInputFormTimeoutEvent(
                node_title=self._node_data.title,
                expiration_time=form.expiration_time,
            )
            yield StreamCompletedEvent(
                node_run_result=NodeRunResult(
                    status=WorkflowNodeExecutionStatus.SUCCEEDED,
                    outputs={},
                    edge_source_handle=self._TIMEOUT_HANDLE,
                ),
            )
            return

        if not form.submitted:
            yield self._form_to_pause_event(form)
            return

        selected_action_id = form.selected_action_id
        if selected_action_id is None:
            msg = (
                f"selected_action_id should not be None when form submitted, "
                f"form_id={form.id}"
            )
            raise AssertionError(msg)
        submitted_inputs = dict(form.submitted_data or {})
        field_names = [
            fi.output_variable_name for fi in self._node_data.all_form_inputs()
        ]
        rendered_content = HumanInputNode.render_form_content_with_outputs(
            form.rendered_content,
            submitted_inputs,
            field_names,
        )
        yield BackendInputFormFilledEvent(
            node_title=self._node_data.title,
            rendered_content=rendered_content,
            action_id=selected_action_id,
            action_text="Submit",
        )
        yield StreamCompletedEvent(
            node_run_result=NodeRunResult(
                status=WorkflowNodeExecutionStatus.SUCCEEDED,
                inputs=submitted_inputs,
                outputs=dict(submitted_inputs),
                edge_source_handle=selected_action_id,
            ),
        )

    @classmethod
    @override
    def _extract_variable_selector_to_variable_mapping(
        cls,
        *,
        graph_config: Mapping[str, Any],
        node_id: str,
        node_data: BackendInputNodeData,
    ) -> Mapping[str, Sequence[str]]:
        _ = graph_config
        return node_data.extract_variable_selector_to_variable_mapping(node_id)
