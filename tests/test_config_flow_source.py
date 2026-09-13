"""Source-level config-flow regressions without importing Home Assistant."""

from __future__ import annotations

import ast
from pathlib import Path

CONFIG_FLOW = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "localtrailerhire"
    / "config_flow.py"
)
SOURCE = CONFIG_FLOW.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _class(name: str) -> ast.ClassDef:
    return next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == name)


def _method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    return next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def test_initial_setup_exposes_and_persists_opt_in_auto_review_options():
    config_flow = _class("LocalTrailerHireConfigFlow")
    options_step = _method(config_flow, "async_step_options")
    names = [node.id for node in ast.walk(options_step) if isinstance(node, ast.Name)]

    # Each key appears in both the submitted options mapping and the form schema.
    assert names.count("CONF_AUTO_REVIEW") >= 2
    assert names.count("CONF_AUTO_REVIEW_RATING") >= 2
    assert names.count("CONF_AUTO_REVIEW_CONTENT") >= 2
    assert "DEFAULT_AUTO_REVIEW" in names


def test_options_flow_uses_current_no_arg_config_entry_contract():
    config_flow = _class("LocalTrailerHireConfigFlow")
    factory = _method(config_flow, "async_get_options_flow")
    calls = [
        node
        for node in ast.walk(factory)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "LocalTrailerHireOptionsFlow"
    ]
    assert len(calls) == 1
    assert calls[0].args == []
    assert calls[0].keywords == []

    options_flow = _class("LocalTrailerHireOptionsFlow")
    assert all(
        not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != "__init__"
        for node in options_flow.body
    )
    assert any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr == "config_entry"
        for node in ast.walk(options_flow)
    )


def test_refresh_token_replaces_password_in_initial_and_reauth_flows():
    config_flow = _class("LocalTrailerHireConfigFlow")
    options_source = ast.unparse(_method(config_flow, "async_step_options"))
    reauth_source = ast.unparse(_method(config_flow, "async_step_reauth_confirm"))

    assert "self._password and (not self._refresh_token)" in options_source
    assert "data.pop(CONF_PASSWORD, None)" in reauth_source
    assert "user_input.get(CONF_PASSWORD) and (not new_refresh_token)" in reauth_source
